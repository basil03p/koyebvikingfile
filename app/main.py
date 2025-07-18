from fastapi import FastAPI, Request, Form, UploadFile
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
    return None  # Return None when authenticated

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
        
    except Exception as e:
        print(f"Upload error: {e}")
    
    return RedirectResponse("/dashboard", status_code=302)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
