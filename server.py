import os
import json
import sqlite3
import asyncio
import time
import base64
import urllib.request
import urllib.parse
from typing import Dict, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Gemini API Key سیٹ کریں (ماحولیاتی متغیر یا براہِ راست یہاں درج کریں)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
MANUAL_GEMINI_KEY = ""  # ضرورت پڑنے پر یہاں اپنی API Key درج کر سکتے ہیں
ACTIVE_GEMINI_KEY = GEMINI_API_KEY or MANUAL_GEMINI_KEY

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

DB_PATH = os.path.join(BASE_DIR, "syncora.db")

def get_db():
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20)
        conn.cursor().execute("SELECT 1")
        return conn
    except Exception:
        fallback = os.path.join(os.environ.get("TEMP", "/tmp"), "syncora.db")
        return sqlite3.connect(fallback, timeout=20)

def init_db():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                phone TEXT PRIMARY KEY,
                display_name TEXT,
                about_status TEXT DEFAULT 'Available',
                avatar_url TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_phone TEXT,
                contact_phone TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_phone, contact_phone)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT,
                sender TEXT,
                receiver TEXT,
                msg_type TEXT,
                content TEXT,
                translated_content TEXT,
                lang TEXT DEFAULT 'en',
                status TEXT DEFAULT 'sent',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB Init Error]: {e}")

init_db()

app = FastAPI(title="Syncora Call & Translation Server")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

def get_chat_id(u1: str, u2: str) -> str:
    cleaned = sorted([u1.strip(), u2.strip()])
    return f"chat_{cleaned[0]}_{cleaned[1]}"

# ڈیٹا ماڈلز
class DirectLoginRequest(BaseModel):
    phone: str
    display_name: Optional[str] = ""

class TranslationRequest(BaseModel):
    text: str
    target_lang: str = "en"

class VoiceTranslateRequest(BaseModel):
    audio_url: str
    target_lang: str = "en"

class ContactRequest(BaseModel):
    user_phone: str
    contact_phone: str

# Gemini API Helper فنکشنز
def call_gemini_api(payload: dict) -> Optional[dict]:
    api_key = ACTIVE_GEMINI_KEY
    if not api_key:
        return None
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=25) as response:
            res_data = response.read().decode("utf-8")
            return json.loads(res_data)
    except Exception as e:
        print(f"[Gemini API Error]: {e}")
        return None

def translate_text_with_gemini(text: str, target_lang: str = "en") -> str:
    if not text.strip():
        return ""
    if not ACTIVE_GEMINI_KEY:
        return text

    prompt = f"""You are an accurate, natural translator for messaging and live phone calls.
Translate the text into target language: '{target_lang}'.
Input can be in Urdu, Roman Urdu, Hindi, English, Punjabi, etc.
Rules:
- Preserve natural spoken meaning and tone.
- Return ONLY the translated string without extra quotes or commentary.

Text:
{text}"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 600}
    }
    
    result = call_gemini_api(payload)
    if result and "candidates" in result and result["candidates"]:
        try:
            return result["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception:
            pass
    return text

def translate_voice_with_gemini(filepath: str, mime_type: str, target_lang: str = "en") -> dict:
    if not os.path.exists(filepath):
        return {"transcript": "", "translated_text": "Audio file not found"}
    if not ACTIVE_GEMINI_KEY:
        return {"transcript": "Voice Note", "translated_text": f"[Set GEMINI_API_KEY for audio translation]"}

    try:
        with open(filepath, "rb") as af:
            audio_bytes = af.read()
        b64_audio = base64.b64encode(audio_bytes).decode("utf-8")

        prompt = f"""Listen to this audio note carefully (which may be in Urdu, Roman Urdu, Hindi, English, or Punjabi).
1. Transcribe the spoken words accurately into original text.
2. Translate the speech into target language: '{target_lang}'.
Return ONLY a valid JSON object matching:
{{"transcript": "<original spoken text>", "translated_text": "<translated speech>"}}"""

        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type, "data": b64_audio}}
                ]
            }],
            "generationConfig": {
                "temperature": 0.2,
                "response_mime_type": "application/json"
            }
        }

        result = call_gemini_api(payload)
        if result and "candidates" in result and result["candidates"]:
            raw_json = result["candidates"][0]["content"]["parts"][0]["text"].strip()
            return json.loads(raw_json)
    except Exception as e:
        print(f"[Voice Translation Error]: {e}")
    
    return {"transcript": "Voice note", "translated_text": "Translation processing failed"}

# WebSocket Connection Manager (کالز اور میسجز کے لیے)
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, phone: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[phone] = websocket

    def disconnect(self, phone: str):
        if phone in self.active_connections:
            del self.active_connections[phone]

    async def send_direct_message(self, phone: str, message: dict):
        if phone in self.active_connections:
            try:
                await self.active_connections[phone].send_json(message)
            except Exception:
                self.disconnect(phone)

manager = ConnectionManager()

# یوزر اور لاگ ان اینڈپوائنٹس
@app.post("/api/auth/login")
async def direct_login(req: DirectLoginRequest):
    phone = req.phone.strip()
    if not phone:
        return JSONResponse(status_code=400, content={"error": "Phone number required"})
    
    conn = get_db()
    cursor = conn.cursor()
    display_name = req.display_name or f"User {phone[-4:]}"
    cursor.execute("""
        INSERT INTO users (phone, display_name) VALUES (?, ?)
        ON CONFLICT(phone) DO UPDATE SET display_name=COALESCE(NULLIF(excluded.display_name, ''), users.display_name)
    """, (phone, display_name))
    conn.commit()
    conn.close()
    return {"status": "ok", "phone": phone, "display_name": display_name}

@app.post("/api/contacts/add")
async def add_contact(req: ContactRequest):
    u = req.user_phone.strip()
    c = req.contact_phone.strip()
    if not u or not c or u == c:
        return {"status": "ignored"}
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO user_contacts (user_phone, contact_phone) VALUES (?, ?)", (u, c))
    cursor.execute("INSERT OR IGNORE INTO user_contacts (contact_phone, user_phone) VALUES (?, ?)", (c, u))
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.get("/api/chats/{phone}")
async def get_chats(phone: str):
    phone = phone.strip()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT contact_phone FROM user_contacts WHERE user_phone = ?", (phone,))
    contacts = [row[0] for row in cursor.fetchall()]
    
    cursor.execute("""
        SELECT DISTINCT CASE WHEN sender = ? THEN receiver ELSE sender END as partner 
        FROM messages WHERE sender = ? OR receiver = ?
    """, (phone, phone, phone))
    msg_partners = [row[0] for row in cursor.fetchall() if row[0] != phone]
    
    all_partners = sorted(list(set(contacts + msg_partners)))
    conn.close()
    return {"chats": all_partners}

@app.get("/api/messages/{phone}/{partner}")
async def get_conversation(phone: str, partner: str):
    chat_id = get_chat_id(phone, partner)
    try:
        conn = get_db()
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
                "id": r[0],
                "sender": r[1],
                "receiver": r[2],
                "msg_type": r[3],
                "content": r[4],
                "translated_content": r[5],
                "lang": r[6],
                "status": r[7],
                "time": str(r[8])[-8:-3]
            })
        return {"messages": messages}
    except Exception as e:
        return {"messages": [], "error": str(e)}

@app.post("/api/upload")
async def upload_media(file: UploadFile = File(...)):
    orig_name = file.filename or "audio.webm"
    _, ext = os.path.splitext(orig_name)
    if not ext or len(ext) < 2:
        ext = ".webm"
        
    new_filename = f"{int(time.time())}_{os.urandom(6).hex()}{ext}"
    filepath = os.path.join(UPLOAD_DIR, new_filename)
    with open(filepath, "wb") as f:
        f.write(await file.read())
    return {"url": f"/uploads/{new_filename}", "filename": new_filename}

# ترجمہ اینڈپوائنٹس (ٹیکسٹ اور وائس میسج)
@app.post("/api/translate/text")
async def translate_text_endpoint(req: TranslationRequest):
    translated = await asyncio.to_thread(translate_text_with_gemini, req.text, req.target_lang)
    return {"status": "ok", "original": req.text, "translated_text": translated, "target_lang": req.target_lang}

@app.post("/api/translate/voice")
async def translate_voice_endpoint(req: VoiceTranslateRequest):
    url_clean = req.audio_url.split("?")[0]
    filename = os.path.basename(url_clean)
    filepath = os.path.join(UPLOAD_DIR, filename)
    
    _, ext = os.path.splitext(filename)
    mime_map = {
        ".webm": "audio/webm",
        ".wav": "audio/wav",
        ".mp3": "audio/mp3",
        ".m4a": "audio/m4a",
        ".ogg": "audio/ogg"
    }
    mime_type = mime_map.get(ext.lower(), "audio/webm")
    
    result = await asyncio.to_thread(translate_voice_with_gemini, filepath, mime_type, req.target_lang)
    return {"status": "ok", **result, "target_lang": req.target_lang}

# لائیو WebSocket اینڈپوائنٹ (چیٹ، کال سگنلنگ، لائیو کال سب ٹائٹلز)
@app.websocket("/ws/{phone}")
async def websocket_endpoint(websocket: WebSocket, phone: str):
    phone = phone.strip()
    await manager.connect(phone, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            event_type = data.get("type")
            to_phone = data.get("to")
            
            # 1. ریئل ٹائم چیٹ میسج
            if event_type == "chat_message":
                content = data.get("content", "")
                msg_type = data.get("msg_type", "text")
                target_lang = data.get("target_lang", "en")
                
                translated_content = ""
                if msg_type == "text" and content:
                    translated_content = await asyncio.to_thread(translate_text_with_gemini, content, target_lang)
                elif msg_type == "voice":
                    translated_content = data.get("translated_content", "")
                
                chat_id = get_chat_id(phone, to_phone)
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO messages (chat_id, sender, receiver, msg_type, content, translated_content, lang)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (chat_id, phone, to_phone, msg_type, content, translated_content, target_lang))
                msg_id = cursor.lastrowid
                conn.commit()
                conn.close()
                
                msg_payload = {
                    "type": "chat_message",
                    "id": msg_id,
                    "sender": phone,
                    "receiver": to_phone,
                    "msg_type": msg_type,
                    "content": content,
                    "translated_content": translated_content,
                    "lang": target_lang,
                    "time": time.strftime("%H:%M")
                }
                await manager.send_direct_message(phone, msg_payload)
                if to_phone:
                    await manager.send_direct_message(to_phone, msg_payload)

            # 2. WebRTC کال سگنلنگ
            elif event_type in ["call_invite", "call_accept", "call_reject", "call_end", "webrtc_offer", "webrtc_answer", "ice_candidate"]:
                if to_phone:
                    data["from"] = phone
                    await manager.send_direct_message(to_phone, data)
                    
            # 3. لائیو کال ٹرانسلیشن
            elif event_type == "call_speech_transcript":
                spoken_text = data.get("text", "")
                target_lang = data.get("target_lang", "en")
                if spoken_text and to_phone:
                    translated = await asyncio.to_thread(translate_text_with_gemini, spoken_text, target_lang)
                    sub_payload = {
                        "type": "call_subtitles",
                        "from": phone,
                        "original_text": spoken_text,
                        "translated_text": translated,
                        "target_lang": target_lang
                    }
                    await manager.send_direct_message(to_phone, sub_payload)
                    await manager.send_direct_message(phone, sub_payload)

    except WebSocketDisconnect:
        manager.disconnect(phone)
    except Exception as e:
        print(f"[WS Error {phone}]: {e}")
        manager.disconnect(phone)

# فرنٹ اینڈ سرور
@app.get("/")
async def get_index():
    index_path = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h2>Syncora Server is Running. Place index.html in the same directory.</h2>")
