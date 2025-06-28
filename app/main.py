from fastapi import FastAPI, Request, Form, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

import requests
import json
import os
import shutil
import tempfile
import uvicorn

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

# === Entrypoint ===
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))