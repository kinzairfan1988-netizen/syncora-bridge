import os
import shutil
import json
import urllib.request
import urllib.parse
import base64
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Syncora Terminal - Clean Stable Version")

# Directories setup
os.makedirs("uploads", exist_ok=True)
os.makedirs("static", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Application State Dictionaries
active_connections = {}
user_profiles = {}
user_contacts = {}
message_history = {}

# Pydantic models
class TranslationRequest(BaseModel):
    text: str
    target_lang: str = "en"

class LoginRequest(BaseModel):
    phone: str

class ContactRequest(BaseModel):
    user_phone: str
    contact_phone: str

# 1. Stable Text Translation Engine (Google Free Endpoint)
def translate_text_engine(text: str, target_lang: str) -> str:
    clean = text.strip()
    if not clean:
        return ""
    
    target_lang = str(target_lang).strip().lower()
    if "zh" in target_lang or "chin" in target_lang:
        t_lang = "zh-CN"
    elif target_lang in ["ur", "ar", "de", "fr", "es"]:
        t_lang = target_lang
    else:
        t_lang = "en"
        
    try:
        encoded_text = urllib.parse.quote(clean)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={t_lang}&dt=t&q={encoded_text}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=4) as response:
            res_body = response.read().decode('utf-8')
            res_data = json.loads(res_body)
            if res_data and isinstance(res_data, list) and len(res_data) > 0:
                translated_sentences = [s[0] for s in res_data[0] if s and s[0]]
                translated_text = "".join(translated_sentences).strip()
                if translated_text:
                    return translated_text
    except Exception as e:
        print(f"[Text Translation Fallback]: {e}")
            
    return clean

# 2. Stable Audio Translation Engine (Direct Gemini REST v1 Endpoint)
def handle_audio_stream(audio_bytes: bytes, target_lang: str = "Urdu") -> str:
    try:
        api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
        if not api_key:
            return "Audio translation error: GEMINI_API_KEY missing."
        
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
        
        # Correct and stable v1 endpoint for gemini-1.5-flash
        url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={api_key}"
        
        payload = {
            "contents": [{
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "audio/webm",
                            "data": audio_b64
                        }
                    },
                    {
                        "text": f"Listen to this audio carefully. Transcribe it and translate it accurately into {target_lang}."
                    }
                ]
            }]
        }
        
        req_data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            url, 
            data=req_data, 
            headers={'Content-Type': 'application/json'}, 
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=15) as response:
            res_body = response.read().decode('utf-8')
            res_json = json.loads(res_body)
            
            candidates = res_json.get("candidates", [])
            if candidates:
                parts = candidates.get("content", {}).get("parts", [])
                if parts:
                    return parts.get("text", "Translation generated.")
            
            return "Audio translation error: Empty response."
            
    except Exception as e:
        print(f"[Gemini Audio Error]: {e}")
        return f"Audio translation error: {str(e)}"

# Root Route: Serves the Clean Frontend Terminal
@app.get("/", response_class=HTMLResponse)
def read_root():
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Syncora Clean Terminal</title>
    <style>
        body { background: #0b0e14; color: #f7fafc; font-family: sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .card { background: #121721; border: 1px solid #2d3748; padding: 30px; border-radius: 16px; text-align: center; width: 350px; }
        input { width: 100%; padding: 12px; margin-bottom: 15px; background: #1a202c; border: 1px solid #2d3748; color: #fff; border-radius: 8px; outline: none; }
        button { width: 100%; padding: 12px; background: #f59e0b; color: #000; font-weight: bold; border: none; border-radius: 8px; cursor: pointer; }
    </style>
</head>
<body>
    <div class="card">
        <h2>Syncora Fresh Start</h2>
        <p style="font-size: 13px; color: #a0aec0; margin-bottom: 20px;">System is stable and clean.</p>
        <input type="tel" id="phone" placeholder="Enter Mobile Number">
        <button onclick="startApp()">Enter Terminal</button>
    </div>
    <script>
        function startApp() {
            const p = document.getElementById('phone').value.trim();
            if(p) {
                localStorage.setItem('syncora_user_phone', p);
                alert('Logged in successfully as ' + p);
                location.reload();
            } else {
                alert('Please enter a valid number.');
            }
        }
    </script>
</body>
</html>"""

# API Endpoints
@app.post("/translate")
async def translate_endpoint(req: TranslationRequest):
    return {"status": "success", "translated_text": translate_text_engine(req.text, req.target_lang)}

@app.post("/api/translate-audio")
async def translate_audio_endpoint(file: UploadFile = File(...), target_lang: str = "Urdu"):
    try:
        audio_bytes = await file.read()
        translated_text = handle_audio_stream(audio_bytes, target_lang=target_lang)
        return {"status": "success", "translated_text": translated_text}
    except Exception as e:
        return {"status": "error", "translated_text": f"Audio translation error: {str(e)}"}

@app.post("/api/auth/login")
async def api_login(req: LoginRequest):
    return {"status": "success", "phone": req.phone}

@app.post("/api/contacts/add")
async def add_contact(req: ContactRequest):
    contacts = user_contacts.setdefault(req.user_phone, [])
    if req.contact_phone not in contacts: contacts.append(req.contact_phone)
    return {"status": "success", "contacts": contacts}

@app.get("/api/chats/{phone}")
async def get_chats(phone: str):
    return {"chats": user_contacts.get(phone, [])}

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    file_path = os.path.join("uploads", file.filename or "voice.webm")
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"status": "success", "url": f"/uploads/{file.filename}"}

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await websocket.accept()
    active_connections[client_id] = websocket
    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            # Echo back or handle messages
            await websocket.send_text(json.dumps({"action": "ack", "data": data}))
    except WebSocketDisconnect:
        active_connections.pop(client_id, None)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
