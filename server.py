import os
import json
import sqlite3
import asyncio
import time
import base64
import urllib.request
import urllib.parse
import urllib.error
from typing import Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# AGAR ENVIRONMENT VARIABLE KA MASLA HO TO APNI KEY YAHAN DIRECT PASTE KAREIN:
MANUAL_GEMINI_KEY = ""  # Maslan: "AIzaSy..."

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

class VoiceTranslateRequest(BaseModel):
    audio_url: str
    target_lang: str = "en"

def get_chat_id(u1: str, u2: str) -> str:
    cleaned = sorted([u1.strip(), u2.strip()])
    return f"chat_{cleaned[0]}_{cleaned}"

def _call_gemini_text_api(text: str, target_lang: str) -> str:
    clean = text.strip()
    if not clean:
        return ""
    
    target_lang = target_lang.strip().lower()
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip() or MANUAL_GEMINI_KEY.strip()
    
    if not gemini_key:
        print("\n[ERROR]: GEMINI_API_KEY nahi mili!\n")
        return clean

    lang_map = {
        "ur": "Urdu (Nastaliq script)",
        "en": "English",
        "ar": "Arabic",
        "de": "German",
        "fr": "French",
        "es": "Spanish",
        "hi": "Hindi",
        "roman_ur": "Roman Urdu"
    }
    target_name = lang_map.get(target_lang, "English")
    
    prompt = (
        f"You are a real-time translator for an audio calling and messaging app. "
        f"Translate the following spoken message accurately into {target_name}. "
        f"The input might be in Urdu script, Roman Urdu, Hindi, or English. "
        f"Return ONLY the direct translated sentence with no extra explanation, no quotes, and no notes:\n{clean}"
    )
    
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}]
    }).encode('utf-8')
    
    candidate_models = [
        "gemini-flash-latest",
        "gemini-pro",
        "gemini-1.5-flash",
        "gemini-1.5-pro"
    ]
    
    for model_name in candidate_models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
        req = urllib.request.Request(
            url, 
            data=payload, 
            headers={'Content-Type': 'application/json'}, 
            method='POST'
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                res_body = response.read().decode('utf-8')
                res_data = json.loads(res_body)
                candidates = res_data.get("candidates", [])
                if candidates:
                    content_obj = candidates[0].get("content", {})
                    parts = content_obj.get("parts", [])
                    if parts:
                        out_text = parts[0].get("text", "").strip()
                        if out_text:
                            print(f"[Gemini Translated via {model_name}]: '{clean}' -> '{out_text}'")
                            return out_text
        except urllib.error.HTTPError as he:
            print(f"[API Notice on {model_name} - HTTP {he.code}]: Agla model try kar rahe hain...")
            continue
        except Exception as e:
            print(f"[API Error on {model_name}]: {e}")
            continue
            
    return clean

def _call_gemini_audio_api(audio_filepath: str, target_lang: str) -> str:
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip() or MANUAL_GEMINI_KEY.strip()
    if not gemini_key or not os.path.exists(audio_filepath):
        return ""

    try:
        with open(audio_filepath, "rb") as f:
            audio_bytes = f.read()
        base64_audio = base64.b64encode(audio_bytes).decode("utf-8")
        
        lang_map = {
            "ur": "Urdu (Nastaliq script)",
            "en": "English",
            "ar": "Arabic",
            "de": "German",
            "fr": "French",
            "es": "Spanish",
            "hi": "Hindi",
            "roman_ur": "Roman Urdu"
        }
        target_name = lang_map.get(target_lang.strip().lower(), "English")
        
        prompt = (
            f"Listen to this audio voice note carefully. "
            f"The person is speaking in Urdu, Roman Urdu, Hindi, or English. "
            f"Translate the spoken words accurately into {target_name}. "
            f"Return ONLY the direct translated sentence with no quotation marks, no timestamps, and no extra explanation."
        )
        
        payload = json.dumps({
            "contents": [{
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "audio/webm",
                            "data": base64_audio
                        }
                    },
                    {"text": prompt}
                ]
            }]
        }).encode('utf-8')
        
        candidate_models = ["gemini-flash-latest", "gemini-1.5-pro", "gemini-pro"]
        
        for model_name in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
            req = urllib.request.Request(
                url, 
                data=payload, 
                headers={'Content-Type': 'application/json'}, 
                method='POST'
            )
            try:
                with urllib.request.urlopen(req, timeout=12) as response:
                    res_body = response.read().decode('utf-8')
                    res_data = json.loads(res_body)
                    candidates = res_data.get("candidates", [])
                    if candidates:
                        content_obj = candidates[0].get("content", {})
                        parts = content_obj.get("parts", [])
                        if parts:
                            out_text = parts[0].get("text", "").strip()
                            if out_text:
                                print(f"[Gemini Audio Translated via {model_name}]: '{out_text}'")
                                return out_text
            except Exception:
                continue
    except Exception as e:
        print(f"[Audio Translation Error]: {e}")
        
    return ""

async def translate_via_gemini(text: str, target_lang: str) -> str:
    return await asyncio.to_thread(_call_gemini_text_api, text, target_lang)

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
            return {"phone": phone, "display_name": row[0] or "", "about_status": row or "", "avatar_url": row or ""}
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
        cursor.execute(
            "INSERT INTO users (phone, display_name, about_status, avatar_url) VALUES (?, ?, ?, ?) ON CONFLICT(phone) DO UPDATE SET display_name=?, about_status=?, avatar_url=?", 
            (phone, display_name, about_status, avatar_url, display_name, about_status, avatar_url)
        )
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
    print(f"[/translate API Hit]: Text='{clean}', Target='{req.target_lang}'")
    translated = await translate_via_gemini(clean, req.target_lang)
    return {"translated_text": translated}

@app.post("/api/translate-voice")
async def translate_voice_endpoint(req: VoiceTranslateRequest):
    filename = os.path.basename(req.audio_url)
    filepath = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(filepath):
        translated = await asyncio.to_thread(_call_gemini_audio_api, filepath, req.target_lang)
        return {"translated_text": translated}
    return {"translated_text": ""}

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
        cursor.execute(
            "SELECT id, sender, receiver, msg_type, content, translated_content, lang, status, created_at FROM messages WHERE chat_id = ? ORDER BY id ASC", 
            (chat_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        messages = []
        for r in rows:
            messages.append({
                "id": r[0], "sender": r, "receiver": r, "msg_type": r,
                "content": r, "translated_content": r, "lang": r[6], "status": r[7], "time": str(r[8])[-8:-3]
            })
        return {"messages": messages}
    except Exception:
        return {"messages": []}

@app.post("/api/upload")
async def upload_media(file: UploadFile = File(...)):
    orig_name = file.filename or "voice.webm"
    _, ext = os.path.splitext(orig_name)
    if not ext:
        ext = ".webm"
        
    new_filename = f"{os.urandom(8).hex()}{ext}"
    filepath = os.path.join(UPLOAD_DIR, new_filename)
    with open(filepath, "wb") as f:
        f.write(await file.read())
    return {"url": f"/uploads/{new_filename}"}

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
                content = payload.get("content", "").strip()
                speech_text = payload.get("speech_text", "").strip()
                lang = payload.get("lang", "en")
                translated = payload.get("translated", "").strip()

                print(f"[WS Chat]: Type={msg_type}, Content='{content}', Speech='{speech_text}', FrontTrans='{translated}'")

                # Text Message Translation
                if msg_type == "text" and content and (not translated or translated.lower() == content.lower()):
                    translated = await translate_via_gemini(content, lang)

                # Voice Note Translation
                elif msg_type == "voice" and (not translated or translated.strip() == ""):
                    if speech_text:
                        print(f"[Voice Translation]: Spoken text '{speech_text}' translate ho raha hai...")
                        translated = await translate_via_gemini(speech_text, lang)
                    else:
                        filename = os.path.basename(content)
                        filepath = os.path.join(UPLOAD_DIR, filename)
                        if os.path.exists(filepath):
                            print(f"[Voice Translation]: Audio file '{filename}' direct translate ho rahi hai...")
                            translated = await asyncio.to_thread(_call_gemini_audio_api, filepath, lang)

                try:
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO messages (chat_id, sender, receiver, msg_type, content, translated_content, lang, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (chat_id, sender, receiver, msg_type, content, translated, lang, "delivered" if manager.is_online(receiver) else "sent")
                    )
                    msg_id = cursor.lastrowid
                    conn.commit()
                    conn.close()
                except Exception as e:
                    print(f"[DB Error]: {e}")
                    msg_id = 9999

                await manager.send_to_user(receiver, {
                    "action": "new_message", 
                    "id": msg_id, 
                    "sender": sender,
                    "content": content, 
                    "speech_text": speech_text,
                    "translated": translated, 
                    "msg_type": msg_type,
                    "lang": lang, 
                    "time": "now", 
                    "status": "delivered"
                })

            elif action == "call_live_caption":
                spoken_text = payload.get("text", "").strip()
                target_lang = payload.get("target_lang", "en")
                
                translated_caption = ""
                if spoken_text:
                    translated_caption = await translate_via_gemini(spoken_text, target_lang)

                payload["translated_text"] = translated_caption
                await manager.send_to_user(receiver, payload)

            elif action == "call_signal":
                await manager.send_to_user(receiver, payload)

    except WebSocketDisconnect:
        manager.disconnect(phone)
    except Exception as e:
        print(f"[WS Error]: {e}")
        manager.disconnect(phone)

@app.get("/")
async def serve_index():
    index_file = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return JSONResponse(status_code=404, content={"error": "index.html not found"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
