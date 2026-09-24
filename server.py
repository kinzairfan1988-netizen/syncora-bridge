import os
import json
import re
import html as html_lib
import sqlite3
import asyncio
import time
import base64
import shutil
import urllib.request
import urllib.parse
import urllib.error
from typing import Dict, Optional, List, Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
MANUAL_GEMINI_KEY = ""
ACTIVE_GEMINI_KEY = GEMINI_API_KEY or MANUAL_GEMINI_KEY

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)

DB_PATH = os.path.join(BASE_DIR, "syncora.db")

def get_db():
    fallback = os.path.join(os.environ.get("TEMP", "/tmp"), "syncora.db")
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.cursor().execute("CREATE TABLE IF NOT EXISTS _test (id INT)")
        conn.commit()
        return conn
    except Exception:
        conn = sqlite3.connect(fallback, timeout=10)
        conn.cursor().execute("CREATE TABLE IF NOT EXISTS _test (id INT)")
        conn.commit()
        return conn

def init_db():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                phone TEXT PRIMARY KEY,
                display_name TEXT DEFAULT '',
                about_status TEXT DEFAULT 'Hey there! I am using Syncora.',
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

app = FastAPI(title="Syncora Calling & Chat Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def serve_index(room: Optional[str] = None):
    index_file = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    static_index = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(static_index):
        return FileResponse(static_index)
    return HTMLResponse("<h2>index.html file nahi mili. Barah-e-karam index.html file banayein.</h2>")

def get_chat_id(u1: str, u2: str) -> str:
    cleaned = sorted([u1.strip(), u2.strip()])
    return f"chat_{cleaned[0]}_{cleaned}"

class LoginReq(BaseModel):
    phone: str

class ProfileUpdateReq(BaseModel):
    phone: str
    display_name: Optional[str] = ""
    about_status: Optional[str] = ""
    avatar_url: Optional[str] = ""

class ContactReq(BaseModel):
    user_phone: str
    contact_phone: str

class TranslateReq(BaseModel):
    text: str
    target_lang: str = "en"

class VoiceTranslateReq(BaseModel):
    audio_url: str
    target_lang: str = "en"

ROMAN_URDU_QUICK_MAP = {
    "kaisy hain": "How are you?",
    "kaise hain": "How are you?",
    "kaise ho": "How are you?",
    "kese ho": "How are you?",
    "kese hain": "How are you?",
    "kya hal hai": "How are you?",
    "kya haal hai": "How are you?",
    "theek ho": "Are you okay?",
    "thik ho": "Are you okay?",
    "kahan ho": "Where are you?",
    "kidhar ho": "Where are you?",
    "kya kar rahe ho": "What are you doing?",
    "kya kr rhe ho": "What are you doing?",
    "shukriya": "Thank you",
    "shukria": "Thank you",
    "salam": "Hello",
    "assalam o alaikum": "Peace be upon you",
    "khuda hafiz": "Goodbye",
    "allah hafiz": "Goodbye",
    "main theek hoon": "I am fine",
    "main theek": "I am fine",
    "theek hon": "I am fine"
}

def call_gemini(payload: dict) -> Optional[dict]:
    if not ACTIVE_GEMINI_KEY:
        return None
    models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash-latest"]
    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={ACTIVE_GEMINI_KEY}"
        headers = {"Content-Type": "application/json"}
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as he:
            if he.code == 404:
                continue
            break
        except Exception:
            break
    return None

def free_web_translate(text: str, target_lang: str = "en") -> str:
    clean_lower = text.strip().lower()
    if target_lang == "en" and clean_lower in ROMAN_URDU_QUICK_MAP:
        return ROMAN_URDU_QUICK_MAP[clean_lower]

    try:
        url = f"https://translate.google.com/m?sl=auto&tl={target_lang}&q={urllib.parse.quote(text)}"
        req = urllib.request.Request(
            url, 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
            match = re.search(r'class="result-container">([^<]+)<', content)
            if match:
                res_clean = html_lib.unescape(match.group(1)).strip()
                if "sacrifice" not in res_clean.lower():
                    return res_clean
    except Exception:
        pass

    return text

def gemini_translate_text(text: str, target_lang: str = "en") -> str:
    clean_lower = text.strip().lower()
    if target_lang == "en" and clean_lower in ROMAN_URDU_QUICK_MAP:
        return ROMAN_URDU_QUICK_MAP[clean_lower]

    if ACTIVE_GEMINI_KEY:
        prompt = f"""Translate accurately into target language: '{target_lang}'.
Input may be in Roman Urdu, Urdu, Hindi, English.
Keep conversational meaning. Return ONLY the translated string without quotes.
Input: {text}"""
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 500}
        }
        res = call_gemini(payload)
        if res and "candidates" in res and res["candidates"]:
            try:
                return res["candidates"][0]["content"]["parts"][0]["text"].strip()
            except Exception:
                pass

    return free_web_translate(text, target_lang)

def gemini_translate_voice(filepath: str, mime_type: str, target_lang: str = "en") -> dict:
    if not os.path.exists(filepath):
        return {"transcript": "", "translated_text": ""}

    if ACTIVE_GEMINI_KEY:
        try:
            with open(filepath, "rb") as f:
                b64_audio = base64.b64encode(f.read()).decode("utf-8")

            prompt = f"""Listen to this audio note (Urdu/Hindi/English).
1. Transcribe the spoken words.
2. Translate into target language: '{target_lang}'.
Return JSON: {{\"transcript\": \"...\", \"translated_text\": \"...\"}}"""

            payload = {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": mime_type, "data": b64_audio}}
                    ]
                }],
                "generationConfig": {"temperature": 0.2, "response_mime_type": "application/json"}
            }
            res = call_gemini(payload)
            if res and "candidates" in res and res["candidates"]:
                raw_json = res["candidates"][0]["content"]["parts"][0]["text"].strip()
                return json.loads(raw_json)
        except Exception:
            pass

    return {"transcript": "", "translated_text": ""}

class SocketManager:
    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}
        self.rooms: Dict[str, Set[str]] = {}

    async def connect(self, client_id: str, ws: WebSocket):
        await ws.accept()
        self.connections[client_id] = ws

    def join_room(self, room: str, client_id: str):
        if room not in self.rooms:
            self.rooms[room] = set()
        self.rooms[room].add(client_id)

    def disconnect(self, client_id: str):
        if client_id in self.connections:
            del self.connections[client_id]
        for room, members in list(self.rooms.items()):
            if client_id in members:
                members.remove(client_id)

    def is_online(self, client_id: str) -> bool:
        return client_id in self.connections

    async def send_to(self, client_id: str, message: dict):
        if client_id in self.connections:
            try:
                await self.connections[client_id].send_json(message)
            except Exception:
                self.disconnect(client_id)

    async def broadcast_room(self, room: str, sender_id: str, message: dict):
        if room in self.rooms:
            for member in list(self.rooms[room]):
                if member != sender_id:
                    await self.send_to(member, message)

ws_mgr = SocketManager()

@app.post("/api/user/profile/update")
async def update_profile(req: ProfileUpdateReq):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users 
            SET display_name = ?, about_status = ?, avatar_url = ? 
            WHERE phone = ?
        """, (req.display_name or "", req.about_status or "", req.avatar_url or "", req.phone.strip()))
        conn.commit()
        conn.close()
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/api/user/profile/{phone}")
async def get_profile(phone: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT phone, display_name, about_status, avatar_url FROM users WHERE phone = ?", (phone.strip(),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"phone": row[0], "display_name": row or row[0], "about_status": row, "avatar_url": row}
    return {"phone": phone, "display_name": phone, "about_status": "Hey there!", "avatar_url": ""}

@app.post("/api/user/profile/update")
async def update_profile(req: ProfileUpdateReq):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE users 
            SET display_name = ?, about_status = ?, avatar_url = ? 
            WHERE phone = ?
        """, (req.display_name or "", req.about_status or "", req.avatar_url or "", req.phone.strip()))
        conn.commit()
        conn.close()
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.post("/api/contacts/add")
async def add_contact(req: ContactReq):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (phone, display_name) VALUES (?, ?)", (req.contact_phone.strip(), req.contact_phone.strip()))
        cursor.execute("INSERT OR IGNORE INTO user_contacts (user_phone, contact_phone) VALUES (?, ?)", (req.user_phone.strip(), req.contact_phone.strip()))
        conn.commit()
        conn.close()
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/api/contacts/{phone}")
async def get_contacts(phone: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT u.phone, u.display_name, u.about_status, u.avatar_url 
        FROM user_contacts c 
        JOIN users u ON c.contact_phone = u.phone 
        WHERE c.user_phone = ?
    """, (phone.strip(),))
    rows = cursor.fetchall()
    conn.close()
    contacts = []
    for r in rows:
        contacts.append({
            "phone": r[0],
            "display_name": r or r[0],
            "about_status": r,
            "avatar_url": r,
            "online": ws_mgr.is_online(r[0])
        })
    return {"contacts": contacts}

@app.post("/api/translate")
async def translate_text(req: TranslateReq):
    translated = gemini_translate_text(req.text, req.target_lang)
    return {"original": req.text, "translated": translated, "target_lang": req.target_lang}

@app.post("/api/translate/voice")
async def translate_voice_api(req: VoiceTranslateReq):
    filename = os.path.basename(req.audio_url)
    filepath = os.path.join(UPLOAD_DIR, filename)
    mime_type = "audio/webm"
    if filename.endswith(".wav"):
        mime_type = "audio/wav"
    elif filename.endswith(".mp3"):
        mime_type = "audio/mp3"
    elif filename.endswith(".ogg"):
        mime_type = "audio/ogg"

    result = gemini_translate_voice(filepath, mime_type, req.target_lang)
    return result

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    filename = f"{int(time.time()*1000)}_{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"url": f"/uploads/{filename}", "filename": filename}

@app.get("/api/messages/{chat_id}")
async def get_messages(chat_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, chat_id, sender, receiver, msg_type, content, translated_content, lang, status, created_at FROM messages WHERE chat_id = ? ORDER BY id ASC", (chat_id,))
    rows = cursor.fetchall()
    conn.close()
    msgs = []
    for r in rows:
        msgs.append({
            "id": r[0],
            "chat_id": r,
            "sender": r,
            "receiver": r,
            "msg_type": r,
            "content": r,
            "translated_content": r,
            "lang": r[7],
            "status": r[8],
            "created_at": r[9]
        })
    return {"messages": msgs}

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    client_id = client_id.strip()
    await ws_mgr.connect(client_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            action = msg.get("action")
            room = msg.get("room")
            receiver = msg.get("receiver", "").strip()

            if action == "join_room" and room:
                ws_mgr.join_room(room, client_id)
                await ws_mgr.broadcast_room(room, client_id, {"action": "user_joined", "sender": client_id})

            elif action in ["call_offer", "call_answer", "ice_candidate", "call_reject", "call_end"]:
                msg["sender"] = client_id
                if room:
                    await ws_mgr.broadcast_room(room, client_id, msg)
                elif receiver:
                    await ws_mgr.send_to(receiver, msg)

            elif action == "chat_message":
                chat_id = get_chat_id(client_id, receiver)
                content = msg.get("content", "")
                msg_type = msg.get("msg_type", "text")
                target_lang = msg.get("target_lang", "en")
                translated = ""

                if msg_type == "text" and content:
                    translated = gemini_translate_text(content, target_lang)
                elif msg_type == "voice" and content:
                    filename = os.path.basename(content)
                    filepath = os.path.join(UPLOAD_DIR, filename)
                    v_res = gemini_translate_voice(filepath, "audio/webm", target_lang)
                    translated = v_res.get("translated_text", "")

                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO messages (chat_id, sender, receiver, msg_type, content, translated_content, lang)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (chat_id, client_id, receiver, msg_type, content, translated, target_lang))
                msg_id = cursor.lastrowid
                conn.commit()
                conn.close()

                payload = {
                    "action": "new_message",
                    "id": msg_id,
                    "chat_id": chat_id,
                    "sender": client_id,
                    "receiver": receiver,
                    "msg_type": msg_type,
                    "content": content,
                    "translated_content": translated,
                    "lang": target_lang,
                    "status": "sent"
                }

                await ws_mgr.send_to(receiver, payload)
                await ws_mgr.send_to(client_id, payload)

    except WebSocketDisconnect:
        ws_mgr.disconnect(client_id)
    except Exception:
        ws_mgr.disconnect(client_id)
