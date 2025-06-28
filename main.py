from fastapi import FastAPI, Request, Form, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import requests, json, os, shutil, tempfile
import uvicorn

app = FastAPI()
templates = Jinja2Templates(directory="templates")

APP_PASSWORD = os.getenv("APP_PASSWORD", "supersecret123")
SESSIONS = set()
HASH_FILE = "hashes.json"

def save_hash(entry):
    try:
        data = []
        if os.path.exists(HASH_FILE):
            with open(HASH_FILE, "r") as f:
                data = json.load(f)
        data.append(entry)
        with open(HASH_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving hash: {e}")

def load_hashes():
    try:
        if os.path.exists(HASH_FILE):
            with open(HASH_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"Error loading hashes: {e}")
    return []

def check_auth(request: Request):
    token = request.cookies.get("token")
    if token not in SESSIONS:
        return RedirectResponse("/login", status_code=302)
    return None

@app.get("/", response_class=HTMLResponse)
async def home():
    return RedirectResponse("/login")

@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    try:
        return templates.TemplateResponse("login.html", {"request": request})
    except Exception as e:
        return HTMLResponse(f"<h1>Template Error</h1><p>Please ensure templates/login.html exists</p><p>Error: {e}</p>")

@app.post("/login", response_class=HTMLResponse)
async def login(request: Request, password: str = Form(...)):
    if password == APP_PASSWORD:
        token = os.urandom(12).hex()
        SESSIONS.add(token)
        resp = RedirectResponse("/dashboard", status_code=302)
        resp.set_cookie(key="token", value=token)
        return resp
    try:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid password."})
    except Exception as e:
        return HTMLResponse(f"<h1>Template Error</h1><p>Invalid password. Please ensure templates/login.html exists</p>")

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    auth = check_auth(request)
    if auth is not None:
        return auth
    hashes = load_hashes()
    try:
        return templates.TemplateResponse("dashboard.html", {"request": request, "hashes": hashes})
    except Exception as e:
        return HTMLResponse(f"<h1>Dashboard</h1><p>Template Error: Please ensure templates/dashboard.html exists</p><p>Hashes: {hashes}</p>")

@app.post("/upload", response_class=HTMLResponse)
async def upload_file(request: Request, file: UploadFile = Form(...), user_hash: str = Form(...)):
    auth = check_auth(request)
    if auth is not None:
        return auth
    
    try:
        server_resp = requests.get("https://vikingfile.com/api/get-server", timeout=10).json()
        server_url = server_resp["server"]
        
        # Use tempfile for better cross-platform compatibility
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            shutil.copyfileobj(file.file, temp_file)
            temp_path = temp_file.name
        
        with open(temp_path, "rb") as f:
            response = requests.post(server_url, files={"file": (file.filename, f)}, data={"user": user_hash}, timeout=30)
        
        # Clean up temp file
        os.unlink(temp_path)
        
        if response.status_code == 200:
            result = response.json()
            save_hash(result)
        else:
            print(f"Upload failed with status: {response.status_code}")
        
    except requests.exceptions.RequestException as e:
        print(f"Network error during upload: {e}")
    except Exception as e:
        print(f"Upload error: {e}")
    
    return RedirectResponse("/dashboard", status_code=302)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
