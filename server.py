import os
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
    t_lang = target_lang if target_lang in ["ur", "en", "ar", "de", "fr", "es"] else "en"
    
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
        print(f"[Google Translate Engine Error]: {e}")
        
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
    return {"status": "ok", "phone": req.phone.strip()}

@app.post("/api/contacts/add")
async def add_permanent_contact(req: dict):
    return {"status": "ok"}

@app.get("/api/user/status/{phone}")
async def get_user_status(phone: str):
    return {"phone": phone, "online": manager.is_online(phone.strip())}

@app.get("/api/user/profile/{phone}")
async def get_user_profile(phone: str):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT display_name, about_status, avatar_url FROM users WHERE phone = ?", (phone,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {"phone": phone, "display_name": row[0] or "", "about_status": row[1] or "", "avatar_url": row[2] or ""}
    except Exception:
        pass
    return {"phone": phone, "display_name": "", "about_status": "Hey there! I am using Syncora.", "avatar_url": ""}

@app.post("/api/user/profile/update")
async def update_user_profile(req: dict):
    phone = req.get("phone", "").strip()
    display_name = req.get("display_name", "").strip()
    about_status = req.get("about_status", "").strip()
    avatar_url = req.get("avatar_url", "").strip()
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (phone, display_name, about_status, avatar_url) VALUES (?, ?, ?, ?) ON CONFLICT(phone) DO UPDATE SET display_name=?, about_status=?, avatar_url=?", 
                       (phone, display_name, about_status, avatar_url, display_name, about_status, avatar_url))
        conn.commit()
        conn.close()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/translate")
async def translate_text(req: TranslationRequest):
    clean = req.text.strip()
    if not clean:
        return {"translated_text": ""}
    translated = translate_via_gemini(clean, req.target_lang)
    return {"translated_text": translated}

@app.post("/api/tts")
async def text_to_speech(req: dict):
    # Generates translated speech audio file using Google TTS backend
    text = req.get("text", "").strip()
    lang = req.get("lang", "en").strip()
    if not text:
        return {"url": ""}
    try:
        encoded_text = urllib.parse.quote(text)
        tts_url = f"https://translate.google.com/translate_tts?ie=UTF-8&q={encoded_text}&tl={lang}&client=tw-ob"
        req_tts = urllib.request.Request(tts_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_tts, timeout=10) as response:
            audio_data = response.read()
            filename = f"tts_{os.urandom(6).hex()}.mp3"
            filepath = os.path.join(UPLOAD_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(audio_data)
            return {"url": f"/uploads/{filename}"}
    except Exception as e:
        print(f"[TTS Error]: {e}")
    return {"url": ""}

@app.get("/api/chats/{phone}")
async def get_user_chats(phone: str):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT contact_phone FROM user_contacts WHERE user_phone = ?", (phone,))
        rows = cursor.fetchall()
        conn.close()
        return {"chats": [r[0] for r in rows]}
    except Exception:
        return {"chats": []}

@app.get("/api/messages/{phone}/{partner}")
async def get_conversation(phone: str, partner: str):
    chat_id = get_chat_id(phone, partner)
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, sender, receiver, msg_type, content, translated_content, lang, status, created_at FROM messages WHERE chat_id = ? ORDER BY id ASC", (chat_id,))
        rows = cursor.fetchall()
        conn.close()
        messages = []
        for r in rows:
            messages.append({
                "id": r[0], "sender": r[1], "receiver": r[2], "msg_type": r[3],
                "content": r[4], "translated_content": r[5], "lang": r[6], "status": r[7], "time": str(r[8])[-8:-3]
            })
        return {"messages": messages}
    except Exception:
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
                sender = phone
                chat_id = get_chat_id(sender, receiver)
                msg_type = payload.get("msg_type", "text")
                content = payload.get("content", "")
                translated = payload.get("translated", "")
                lang = payload.get("lang", "en")
                
                try:
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute("INSERT INTO messages (chat_id, sender, receiver, msg_type, content, translated_content, lang, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   (chat_id, sender, receiver, msg_type, content, translated, lang, "delivered" if manager.is_online(receiver) else "sent"))
                    msg_id = cursor.lastrowid
                    conn.commit()
                    conn.close()
                except Exception:
                    msg_id = 9999

                await manager.send_to_user(receiver, {
                    "action": "new_message", "id": msg_id, "sender": sender,
                    "content": content, "translated": translated, "msg_type": msg_type,
                    "lang": lang, "time": "now", "status": "delivered"
                })
            elif action in ["call_signal", "call_live_caption"]:
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
