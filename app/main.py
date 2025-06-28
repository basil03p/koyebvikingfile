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

    try:
        server_resp = requests.get("https://vikingfile.com/api/get-server", timeout=10).json()
        server_url = server_resp["server"]

        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            shutil.copyfileobj(file.file, temp_file)
            temp_path = temp_file.name

        with open(temp_path, "rb") as f:
            response = requests.post(server_url, files={"file": (file.filename, f)}, data={"user": user_hash}, timeout=30)

        os.unlink(temp_path)

        if response.status_code == 200:
            result = response.json()
            save_hash(result)

    except Exception as e:
        print(f"Upload error: {e}")

    return RedirectResponse("/dashboard", status_code=302)

@app.post("/upload-remote", response_class=HTMLResponse)
async def upload_remote_file(request: Request, file_url: str = Form(...), user_hash: str = Form(...)):
    auth = check_auth(request)
    if isinstance(auth, RedirectResponse):
        return auth

    try:
        # Get VikingFile server
        server_resp = requests.get("https://vikingfile.com/api/get-server", timeout=10).json()
        server_url = server_resp["server"]

        # Download the remote file
        file_response = requests.get(file_url, timeout=30, stream=True)
        file_response.raise_for_status()

        # Extract filename from URL or use a default
        filename = file_url.split("/")[-1] or "remote_file"
        if "?" in filename:
            filename = filename.split("?")[0]

        # Save to temporary file
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            for chunk in file_response.iter_content(chunk_size=8192):
                temp_file.write(chunk)
            temp_path = temp_file.name

        # Upload to VikingFile
        with open(temp_path, "rb") as f:
            response = requests.post(server_url, files={"file": (filename, f)}, data={"user": user_hash}, timeout=30)

        os.unlink(temp_path)

        if response.status_code == 200:
            result = response.json()
            save_hash(result)

    except Exception as e:
        print(f"Remote upload error: {e}")

    return RedirectResponse("/dashboard", status_code=302)

# === Entrypoint ===
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))