# VikingFile Uploader App

A FastAPI uploader with password login and VikingFile integration.

## 🚀 Quick start

### Local Development
```bash
cd app
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Docker
```bash
docker build -t viking-uploader .
docker run -p 8000:8000 viking-uploader
```

### Replit
1. Fork this repository to your Replit account
2. Click "Run" button
3. Access the app at the provided URL

## 🌐 Environment
Password is hardcoded in main.py as APP_PASSWORD or set via environment variable.

## 🔥 Deploy on Koyeb
Build: docker build -t app .
Run: docker run -p $PORT:8000 app
