import os
import json
import urllib.request
import urllib.parse
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Syncora Terminal - Stable Server")

# Directories setup
os.makedirs("uploads", exist_ok=True)
os.makedirs("static", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/static", StaticFiles(directory="static"), name="static")

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

class ProfileRequest(BaseModel):
    phone: str
    display_name: str = ""
    about_status: str = ""
    avatar_url: str = ""

# Stable Translation Engine
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
        with urllib.request.urlopen(req, timeout=6) as response:
            res_body = response.read().decode('utf-8')
            res_data = json.loads(res_body)
            if res_data and isinstance(res_data, list) and len(res_data) > 0:
                translated_sentences = [s[0] for s in res_data[0] if s and s[0]]
                translated_text = "".join(translated_sentences).strip()
                if translated_text:
                    return translated_text
    except Exception as e:
        print(f"[Translation Error]: {e}")
        
    return clean

# Root Route: Serves the frontend
@app.get("/", response_class=HTMLResponse)
def read_root():
    index_path = "static/index.html"
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>Error: static/index.html not found. Please place your HTML file inside the 'static' folder.</h3>"

# Translation Endpoint
@app.post("/translate")
async def translate_endpoint(req: TranslationRequest):
    try:
        translated = translate_text_engine(req.text, req.target_lang)
        return {
            "status": "success",
            "original": req.text,
            "target_lang": req.target_lang,
            "translated_text": translated
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Auth & Profile Endpoints
@app.post("/api/auth/login")
async def api_login(req: LoginRequest):
    user_profiles[req.phone] = user_profiles.get(req.phone, {"phone": req.phone, "display_name": "", "about_status": ""})
    return {"status": "success", "phone": req.phone}

@app.get("/api/user/profile/{phone}")
async def get_profile(phone: str):
    return user_profiles.get(phone, {"phone": phone, "display_name": "", "about_status": "", "avatar_url": ""})

@app.post("/api/user/profile/update")
async def update_profile(req: ProfileRequest):
    user_profiles[req.phone] = req.dict()
    return {"status": "success"}

@app.get("/api/user/status/{phone}")
async def get_user_status(phone: str):
    return {"phone": phone, "online": phone in active_connections}

@app.post("/api/contacts/add")
async def add_contact(req: ContactRequest):
    contacts = user_contacts.setdefault(req.user_phone, [])
    if req.contact_phone not in contacts:
        contacts.append(req.contact_phone)
    return {"status": "success", "contacts": contacts}

@app.get("/api/chats/{phone}")
async def get_chats(phone: str):
    chats = user_contacts.get(phone, [])
    return {"chats": chats}

@app.get("/api/messages/{user1}/{user2}")
async def get_messages(user1: str, user2: str):
    key = tuple(sorted([user1, user2]))
    msgs = message_history.get(key, [])
    return {"messages": msgs}

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    file_path = os.path.join("uploads", file.filename or "file.bin")
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"status": "success", "url": f"/uploads/{file.filename}"}

@app.post("/api/stt")
async def speech_to_text(file: UploadFile = File(...)):
    file_path = os.path.join("uploads", file.filename or "voice.webm")
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"status": "success", "text": "voice message note", "url": f"/uploads/{file.filename}"}

# WebSocket for real-time messaging & WebRTC signaling
@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await websocket.accept()
    active_connections[client_id] = websocket
    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            action = data.get("action")
            
            if action == "ping":
                await websocket.send_text(json.dumps({"action": "pong"}))
                continue
                
            receiver = data.get("receiver")
            
            if action == "chat_message":
                msg_record = {
                    "id": str(os.urandom(4).hex()),
                    "sender": client_id,
                    "content": data.get("content"),
                    "translated_content": data.get("translated"),
                    "msg_type": data.get("msg_type", "text"),
                    "time": "now",
                    "lang": data.get("lang", "en")
                }
                key = tuple(sorted([client_id, receiver]))
                message_history.setdefault(key, []).append(msg_record)
                
                if receiver in active_connections:
                    await active_connections[receiver].send_text(json.dumps({
                        "action": "new_message",
                        **msg_record
                    }))
            
            elif action in ["call_signal", "call_live_caption"]:
                if receiver in active_connections:
                    await active_connections[receiver].send_text(raw_data)
                    
    except WebSocketDisconnect:
        if client_id in active_connections:
            del active_connections[client_id]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
