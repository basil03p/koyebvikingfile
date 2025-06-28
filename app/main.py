from fastapi import FastAPI, Request, Form, UploadFile, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

import requests
import json
import os
import shutil
import tempfile
import uvicorn
import asyncio
from typing import List

from pathlib import Path

# === Setup FastAPI & Jinja2 ===
app = FastAPI()
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# === Globals ===
APP_PASSWORD = os.getenv("APP_PASSWORD", "supersecret123")
SESSIONS = set()
HASH_FILE = "hashes.json"

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_progress(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass

manager = ConnectionManager()

# === Helper functions ===
def save_hash(entry):
    data = []
    if os.path.exists(HASH_FILE):
        with open(HASH_FILE, "r") as f:
            data = json.load(f)
    data.append(entry)
    with open(HASH_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_hashes():
    if os.path.exists(HASH_FILE):
        with open(HASH_FILE, "r") as f:
            return json.load(f)
    return []

def check_auth(request: Request):
    token = request.cookies.get("token")
    if token not in SESSIONS:
        return RedirectResponse("/login", status_code=302)
    return None

# === Routes ===
@app.get("/", response_class=HTMLResponse)
async def home():
    return RedirectResponse("/login")

@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login", response_class=HTMLResponse)
async def login(request: Request, password: str = Form(...)):
    if password == APP_PASSWORD:
        token = os.urandom(12).hex()
        SESSIONS.add(token)
        resp = RedirectResponse("/dashboard", status_code=302)
        resp.set_cookie(key="token", value=token)
        return resp
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid password."})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    auth = check_auth(request)
    if isinstance(auth, RedirectResponse):
        return auth
    hashes = load_hashes()
    return templates.TemplateResponse("dashboard.html", {"request": request, "hashes": hashes})

@app.post("/upload", response_class=HTMLResponse)
async def upload_file(request: Request, file: UploadFile = Form(...), user_hash: str = Form(...)):
    auth = check_auth(request)
    if isinstance(auth, RedirectResponse):
        return auth

    temp_path = None
    try:
        # Get VikingFile server
        try:
            server_resp = requests.get("https://vikingfile.com/api/get-server", timeout=10)
            server_resp.raise_for_status()
            server_url = server_resp.json()["server"]
        except requests.exceptions.RequestException as e:
            print(f"Failed to get VikingFile server: {e}")
            return RedirectResponse("/dashboard", status_code=302)

        # Save uploaded file to temp location
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_path = temp_file.name
            shutil.copyfileobj(file.file, temp_file)

        # Upload to VikingFile with retry
        upload_success = False
        for attempt in range(2):
            try:
                with open(temp_path, "rb") as f:
                    response = requests.post(
                        server_url, 
                        files={"file": (file.filename, f)}, 
                        data={"user": user_hash}, 
                        timeout=(10, 120)
                    )
                response.raise_for_status()
                
                if response.status_code == 200:
                    result = response.json()
                    save_hash(result)
                    upload_success = True
                    print(f"Upload successful: {file.filename}")
                    break
                else:
                    print(f"Upload failed with status: {response.status_code}")
                    
            except requests.exceptions.RequestException as e:
                print(f"Upload attempt {attempt + 1} failed: {e}")
                if attempt == 0:  # Try once more
                    continue

        if not upload_success:
            print("Upload to VikingFile failed after retries")

    except Exception as e:
        print(f"Upload error: {e}")
    finally:
        # Clean up temp file
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception as e:
                print(f"Failed to delete temp file: {e}")

    return RedirectResponse("/dashboard", status_code=302)

@app.post("/upload-remote", response_class=HTMLResponse)
async def upload_remote_file(request: Request, file_url: str = Form(...), user_hash: str = Form(...)):
    auth = check_auth(request)
    if isinstance(auth, RedirectResponse):
        return auth

    try:
        # Get VikingFile server
        try:
            server_resp = requests.get("https://vikingfile.com/api/get-server", timeout=10)
            server_resp.raise_for_status()
            server_url = server_resp.json()["server"]
        except requests.exceptions.RequestException as e:
            print(f"Failed to get VikingFile server: {e}")
            return RedirectResponse("/dashboard", status_code=302)

        # Extract filename from URL
        filename = file_url.split("/")[-1].split("?")[0] or "remote_file"
        if not filename or filename == "":
            filename = "remote_file"

        # Use VikingFile's remote upload API
        upload_data = {
            "link": file_url,
            "user": user_hash,
            "name": filename
        }

        # Try remote upload with retries
        upload_success = False
        for attempt in range(3):
            try:
                print(f"Remote upload attempt {attempt + 1} for: {file_url}")
                upload_response = requests.post(
                    server_url, 
                    data=upload_data, 
                    timeout=(10, 300)  # 5 minute timeout for remote uploads
                )
                upload_response.raise_for_status()
                
                if upload_response.status_code == 200:
                    result = upload_response.json()
                    
                    # Check if the response contains an error
                    if "error" in result and result["error"] != "success":
                        print(f"VikingFile API error: {result.get('error', 'Unknown error')}")
                        break
                    
                    # Save successful upload
                    if "hash" in result and "url" in result:
                        save_hash(result)
                        upload_success = True
                        print(f"Remote upload successful: {result.get('name', filename)}")
                        break
                    else:
                        print(f"Unexpected response format: {result}")
                        
                else:
                    print(f"Upload failed with status: {upload_response.status_code}")
                    print(f"Response: {upload_response.text}")
                    
            except requests.exceptions.Timeout as e:
                print(f"Remote upload attempt {attempt + 1} timed out: {e}")
                if attempt < 2:  # Try again unless it's the last attempt
                    continue
            except requests.exceptions.RequestException as e:
                print(f"Remote upload attempt {attempt + 1} failed: {e}")
                if attempt < 2:  # Try again unless it's the last attempt
                    continue

        if not upload_success:
            print("Remote upload to VikingFile failed after all retries")

    except Exception as e:
        print(f"Remote upload error: {e}")

    return RedirectResponse("/dashboard", status_code=302)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

async def upload_single_remote_file(file_url: str, user_hash: str, index: int, total: int):
    """Upload a single remote file and send progress updates"""
    try:
        await manager.send_progress({
            "type": "progress",
            "index": index,
            "total": total,
            "url": file_url,
            "status": "starting",
            "message": f"Starting upload {index + 1}/{total}"
        })

        # Get VikingFile server
        try:
            server_resp = requests.get("https://vikingfile.com/api/get-server", timeout=10)
            server_resp.raise_for_status()
            server_url = server_resp.json()["server"]
        except requests.exceptions.RequestException as e:
            await manager.send_progress({
                "type": "progress",
                "index": index,
                "total": total,
                "url": file_url,
                "status": "error",
                "message": f"Failed to get server: {str(e)}"
            })
            return False

        # Extract filename from URL
        filename = file_url.split("/")[-1].split("?")[0] or f"remote_file_{index + 1}"
        if not filename or filename == "":
            filename = f"remote_file_{index + 1}"

        await manager.send_progress({
            "type": "progress",
            "index": index,
            "total": total,
            "url": file_url,
            "status": "uploading",
            "message": f"Uploading {filename}..."
        })

        # Use VikingFile's remote upload API
        upload_data = {
            "link": file_url,
            "user": user_hash,
            "name": filename
        }

        # Try remote upload with retries
        for attempt in range(3):
            try:
                upload_response = requests.post(
                    server_url, 
                    data=upload_data, 
                    timeout=(10, 300)
                )
                upload_response.raise_for_status()
                
                if upload_response.status_code == 200:
                    result = upload_response.json()
                    
                    # Check if the response contains an error
                    if "error" in result and result["error"] != "success":
                        await manager.send_progress({
                            "type": "progress",
                            "index": index,
                            "total": total,
                            "url": file_url,
                            "status": "error",
                            "message": f"API error: {result.get('error', 'Unknown error')}"
                        })
                        return False
                    
                    # Save successful upload
                    if "hash" in result and "url" in result:
                        save_hash(result)
                        await manager.send_progress({
                            "type": "progress",
                            "index": index,
                            "total": total,
                            "url": file_url,
                            "status": "completed",
                            "message": f"✅ {result.get('name', filename)} uploaded successfully",
                            "result": result
                        })
                        return True
                    else:
                        await manager.send_progress({
                            "type": "progress",
                            "index": index,
                            "total": total,
                            "url": file_url,
                            "status": "error",
                            "message": f"Unexpected response format"
                        })
                        return False
                        
                else:
                    if attempt < 2:
                        await manager.send_progress({
                            "type": "progress",
                            "index": index,
                            "total": total,
                            "url": file_url,
                            "status": "retrying",
                            "message": f"Retry {attempt + 1}/3..."
                        })
                        continue
                    else:
                        await manager.send_progress({
                            "type": "progress",
                            "index": index,
                            "total": total,
                            "url": file_url,
                            "status": "error",
                            "message": f"Upload failed with status: {upload_response.status_code}"
                        })
                        return False
                    
            except requests.exceptions.Timeout as e:
                if attempt < 2:
                    await manager.send_progress({
                        "type": "progress",
                        "index": index,
                        "total": total,
                        "url": file_url,
                        "status": "retrying",
                        "message": f"Timeout, retry {attempt + 1}/3..."
                    })
                    continue
                else:
                    await manager.send_progress({
                        "type": "progress",
                        "index": index,
                        "total": total,
                        "url": file_url,
                        "status": "error",
                        "message": f"Upload timed out after retries"
                    })
                    return False
            except requests.exceptions.RequestException as e:
                if attempt < 2:
                    await manager.send_progress({
                        "type": "progress",
                        "index": index,
                        "total": total,
                        "url": file_url,
                        "status": "retrying",
                        "message": f"Network error, retry {attempt + 1}/3..."
                    })
                    continue
                else:
                    await manager.send_progress({
                        "type": "progress",
                        "index": index,
                        "total": total,
                        "url": file_url,
                        "status": "error",
                        "message": f"Network error: {str(e)}"
                    })
                    return False

    except Exception as e:
        await manager.send_progress({
            "type": "progress",
            "index": index,
            "total": total,
            "url": file_url,
            "status": "error",
            "message": f"Unexpected error: {str(e)}"
        })
        return False

@app.post("/upload-bulk-remote", response_class=HTMLResponse)
async def upload_bulk_remote_files(
    request: Request, 
    background_tasks: BackgroundTasks,
    file_urls: str = Form(...), 
    user_hash: str = Form(...)
):
    auth = check_auth(request)
    if isinstance(auth, RedirectResponse):
        return auth

    # Parse URLs (split by newlines or commas)
    urls = []
    for line in file_urls.strip().split('\n'):
        line = line.strip()
        if line:
            # Also split by comma in case multiple URLs are on same line
            for url in line.split(','):
                url = url.strip()
                if url.startswith(('http://', 'https://')):
                    urls.append(url)

    if not urls:
        return RedirectResponse("/dashboard", status_code=302)

    # Start bulk upload in background
    async def bulk_upload_task():
        await manager.send_progress({
            "type": "bulk_start",
            "total": len(urls),
            "message": f"Starting bulk upload of {len(urls)} files..."
        })
        
        successful = 0
        for i, url in enumerate(urls):
            result = await upload_single_remote_file(url, user_hash, i, len(urls))
            if result:
                successful += 1
        
        await manager.send_progress({
            "type": "bulk_complete",
            "total": len(urls),
            "successful": successful,
            "failed": len(urls) - successful,
            "message": f"Bulk upload complete: {successful}/{len(urls)} successful"
        })

    background_tasks.add_task(bulk_upload_task)
    return RedirectResponse("/dashboard", status_code=302)

# === Entrypoint ===
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))