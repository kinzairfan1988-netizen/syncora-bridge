import os
import re
import json
import sqlite3
import urllib.request
import urllib.parse
from typing import Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

DB_PATH = os.path.join(BASE_DIR, "syncora.db")

def init_db():
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS users (phone TEXT PRIMARY KEY, display_name TEXT, about_status TEXT DEFAULT 'Hey there!', avatar_url TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE IF NOT EXISTS user_contacts (id INTEGER PRIMARY KEY AUTOINCREMENT, user_phone TEXT, contact_phone TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_phone, contact_phone))")
        cursor.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT, sender TEXT, receiver TEXT, msg_type TEXT, content TEXT, translated_content TEXT, lang TEXT DEFAULT 'en', status TEXT DEFAULT 'sent', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB Init Error]: {e}")

init_db()

app = FastAPI(title="Syncora Terminal")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

class DirectLoginRequest(BaseModel):
    phone: str

class TranslationRequest(BaseModel):
    text: str
    target_lang: str = "en"

def get_chat_id(u1: str, u2: str) -> str:
    cleaned = sorted([u1.strip(), u2.strip()])
    return f"chat_{cleaned[0]}_{cleaned[1]}"

def translate_via_gemini(text: str, target_lang: str) -> str:
    clean = text.strip()
    if not clean:
        return ""

    target_lang = target_lang.strip().lower()
    
    # 1. Google Translate GTX Free API (Fast & Reliable)
    try:
        q_enc = urllib.parse.quote(clean.encode('utf-8'))
        url_g = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_lang}&dt=t&q={q_enc}"
        req_g = urllib.request.Request(url_g, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_g, timeout=5) as response:
            res_json = json.loads(response.read().decode('utf-8'))
            if res_json and isinstance(res_json, list) and len(res_json) > 0 and res_json[0]:
                out = "".join([part[0] for part in res_json[0] if part and part[0]]).strip()
                if out:
                    return out
    except Exception as e:
        print(f"[GTX Translation Error]: {e}")

    # 2. Gemini API Fallback
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        try:
            lang_map = {"ur": "Urdu", "en": "English", "ar": "Arabic", "de": "German", "fr": "French", "es": "Spanish"}
            target_name = lang_map.get(target_lang, "English")
            prompt = f"Translate this text accurately into {target_name}. Return ONLY the translated text without quotation marks: {clean}"
            payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode('utf-8')
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
            req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=6) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                out_text = res_data.get("candidates", [])[0].get("content", {}).get("parts", [])[0].get("text", "").strip()
                if out_text:
                    return out_text
        except Exception as e:
            print(f"[Gemini API Error]: {e}")

    return clean

class ConnectionManager:
    def __init__(self):
        self.active_sessions: Dict[str, WebSocket] = {}

    async def connect(self, phone: str, websocket: WebSocket):
        await websocket.accept()
        self.active_sessions[phone] = websocket

    def disconnect(self, phone: str):
        if phone in self.active_sessions:
            del self.active_sessions[phone]

    def is_online(self, phone: str) -> bool:
        return phone.strip() in self.active_sessions

    async def send_to_user(self, phone: str, payload: dict):
        if phone in self.active_sessions:
            try:
                await self.active_sessions[phone].send_text(json.dumps(payload))
            except Exception:
                self.disconnect(phone)

manager = ConnectionManager()

@app.post("/api/auth/login")
async def direct_login(req: DirectLoginRequest):
    phone = req.phone.strip()
    return {"status": "ok", "phone": phone}

@app.post("/api/contacts/add")
async def add_permanent_contact(req: dict):
    return {"status": "ok"}

@app.get("/api/user/status/{phone}")
async def get_user_status(phone: str):
    return {"phone": phone, "online": manager.is_online(phone.strip())}

@app.post("/translate")
async def translate_text(req: TranslationRequest):
    clean = req.text.strip()
    if not clean:
        return {"translated_text": ""}
    target_lang = req.target_lang.strip().lower() if req.target_lang else "en"
    translated = translate_via_gemini(clean, target_lang)
    return {"translated_text": translated}

@app.get("/api/chats/{phone}")
async def get_user_chats(phone: str):
    return {"chats": []}

@app.get("/api/messages/{phone}/{partner}")
async def get_conversation(phone: str, partner: str):
    return {"messages": []}

@app.post("/api/upload")
async def upload_media(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[1] or ".webm"
    filename = f"{os.urandom(8).hex()}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(await file.read())
    return {"url": f"/uploads/{filename}"}

@app.websocket("/ws/{phone}")
async def socket_endpoint(websocket: WebSocket, phone: str):
    await manager.connect(phone, websocket)
    try:
        while True:
            raw_data = await websocket.receive_text()
            payload = json.loads(raw_data)
            action = payload.get("action")
            receiver = payload.get("receiver")

            if action == "ping":
                await websocket.send_text(json.dumps({"action": "pong"}))
                continue
            elif action == "chat_message":
                await manager.send_to_user(receiver, {
                    "action": "new_message",
                    "sender": phone,
                    "content": payload.get("content", ""),
                    "translated": payload.get("translated", ""),
                    "msg_type": payload.get("msg_type", "text"),
                    "lang": payload.get("lang", "en"),
                    "time": "now"
                })
            elif action == "call_live_caption":
                await manager.send_to_user(receiver, payload)
    except WebSocketDisconnect:
        manager.disconnect(phone)
    except Exception:
        manager.disconnect(phone)

@app.get("/")
async def serve_index():
    index_file = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return JSONResponse(status_code=404, content={"error": "index.html not found"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8080, reload=False)
