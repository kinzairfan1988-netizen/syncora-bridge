import os
import json
import re
import html as html_lib
import sqlite3
import asyncio
import time
import base64
import urllib.request
import urllib.parse
import urllib.error
from typing import Dict, Optional
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

app = FastAPI(title="Syncora Terminal Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

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

# گوگل جیمنائی کو نئے ماڈلز کے ساتھ کال کرنے والا فنکشن
def call_gemini(payload: dict) -> Optional[dict]:
    if not ACTIVE_GEMINI_KEY:
        return None
    # نئے فعال ماڈلز کی لسٹ (404 سے بچنے کے لیے)
    models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash-latest", "gemini-1.5-flash"]
    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={ACTIVE_GEMINI_KEY}"
        headers = {"Content-Type": "application/json"}
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as he:
            if he.code == 404:
                continue  # اگر ماڈل 404 دے تو اگلا ماڈل ٹرائی کریں
            print(f"[Gemini Error]: {he}")
            break
        except Exception as e:
            print(f"[Gemini Error]: {e}")
            break
    return None

# بغیر 429 ایرر کے 100% کام کرنے والا ٹرانسلیشن فال بیک
def free_web_translate(text: str, target_lang: str = "en") -> str:
    try:
        url = f"https://translate.google.com/m?sl=auto&tl={target_lang}&q={urllib.parse.quote(text)}"
        req = urllib.request.Request(
            url, 
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
            match = re.search(r'class="result-container">([^<]+)<', content)
            if match:
                return html_lib.unescape(match.group(1)).strip()
    except Exception as e:
        print(f"[Web Translate Error]: {e}")

    # متبادل MyMemory ٹرانسلیٹ
    try:
        url2 = f"https://api.mymemory.translated.net/get?q={urllib.parse.quote(text)}&langpair=autodetect|{target_lang}"
        req2 = urllib.request.Request(url2, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req2, timeout=8) as resp2:
            data = json.loads(resp2.read().decode("utf-8"))
            if "responseData" in data and "translatedText" in data["responseData"]:
                res_txt = data["responseData"]["translatedText"].strip()
                if res_txt and not res_txt.startswith("MYMEMORY"):
                    return res_txt
    except Exception:
        pass

    return text

def gemini_translate_text(text: str, target_lang: str = "en") -> str:
    if not text.strip():
        return ""

    if ACTIVE_GEMINI_KEY:
        prompt = f"""Translate this message accurately into target language: '{target_lang}'.
Input may be in Roman Urdu, Urdu script, Hindi, English, Punjabi or mixed colloquial language.
Rules:
- Keep the natural spoken meaning and feeling.
- Return ONLY the translated string without quotes or explanations.

Text:
{text}"""
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

    # فال بیک ترجمہ جو 429 کے بغیر چلتا ہے
    return free_web_translate(text, target_lang)

def gemini_translate_voice(filepath: str, mime_type: str, target_lang: str = "en") -> dict:
    if not os.path.exists(filepath):
        return {"transcript": "", "translated_text": "Audio file not found"}

    if ACTIVE_GEMINI_KEY:
        try:
            with open(filepath, "rb") as f:
                b64_audio = base64.b64encode(f.read()).decode("utf-8")

            prompt = f"""Listen to this voice recording (it may be in Urdu, Roman Urdu, Hindi, English, etc.).
1. Transcribe the exact words spoken into original text.
2. Translate the speech into target language: '{target_lang}'.
Return ONLY a valid JSON object formatted as:
{{"transcript": "<exact original speech>", "translated_text": "<translated speech>"}}"""

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
        except Exception as e:
            print(f"[Gemini Voice Error]: {e}")

    return {"transcript": "", "translated_text": ""}

class SocketManager:
    def __init__(self):
        self.connections: Dict[str, WebSocket] = {}

    async def connect(self, phone: str, ws: WebSocket):
        await ws.accept()
        self.connections[phone] = ws

    def disconnect(self, phone: str):
        if phone in self.connections:
            del self.connections[phone]

    def is_online(self, phone: str) -> bool:
        return phone in self.connections

    async def send_to(self, phone: str, message: dict):
        if phone in self.connections:
            try:
                await self.connections[phone].send_json(message)
            except Exception:
                self.disconnect(phone)

ws_mgr = SocketManager()

@app.post("/api/auth/login")
async def login_api(req: LoginReq):
    phone = req.phone.strip()
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (phone, display_name) VALUES (?, ?)", (phone, phone))
        conn.commit()
        conn.close()
    except Exception:
        pass
    return {"status": "ok", "phone": phone}

@app.get("/api/user/profile/{phone}")
async def get_profile(phone: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT phone, display_name, about_status, avatar_url FROM users WHERE phone = ?", (phone.strip(),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"phone": row[0], "display_name": row or row[0], "about_status": row, "avatar_url": row[3]}
    return {"phone": phone, "display_name": phone, "about_status": "Hey there!", "avatar_url": ""}

@app.post("/api/user/profile/update")
async def update_profile(req: ProfileUpdateReq):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (phone, display_name, about_status, avatar_url)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(phone) DO UPDATE SET
            display_name = excluded.display_name,
            about_status = excluded.about_status,
            avatar_url = excluded.avatar_url
    """, (req.phone.strip(), req.display_name, req.about_status, req.avatar_url))
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.get("/api/user/status/{phone}")
async def get_status(phone: str):
    return {"phone": phone, "online": ws_mgr.is_online(phone.strip())}

@app.post("/api/contacts/add")
async def add_contact(req: ContactReq):
    u = req.user_phone.strip()
    c = req.contact_phone.strip()
    if u and c and u != c:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO user_contacts (user_phone, contact_phone) VALUES (?, ?)", (u, c))
        cursor.execute("INSERT OR IGNORE INTO user_contacts (contact_phone, user_phone) VALUES (?, ?)", (c, u))
        conn.commit()
        conn.close()
    return {"status": "ok"}

@app.get("/api/chats/{phone}")
async def get_chats(phone: str):
    p = phone.strip()
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT contact_phone FROM user_contacts WHERE user_phone = ?", (p,))
    contacts = [r[0] for r in cursor.fetchall()]
    cursor.execute("""
        SELECT DISTINCT CASE WHEN sender = ? THEN receiver ELSE sender END as partner
        FROM messages WHERE sender = ? OR receiver = ?
    """, (p, p, p))
    msg_partners = [r[0] for r in cursor.fetchall() if r[0] != p]
    conn.close()
    return {"chats": sorted(list(set(contacts + msg_partners)))}

@app.get("/api/messages/{phone}/{partner}")
async def get_messages(phone: str, partner: str):
    chat_id = get_chat_id(phone, partner)
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, sender, receiver, msg_type, content, translated_content, lang, status, created_at
            FROM messages WHERE chat_id = ? ORDER BY id ASC
        """, (chat_id,))
        rows = cursor.fetchall()
        conn.close()
        messages = []
        for r in rows:
            messages.append({
                "id": r[0],
                "sender": r,
                "receiver": r,
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
async def upload_file(file: UploadFile = File(...)):
    orig = file.filename or "file.webm"
    _, ext = os.path.splitext(orig)
    if not ext:
        ext = ".webm"
    fname = f"{int(time.time())}_{os.urandom(4).hex()}{ext}"
    fpath = os.path.join(UPLOAD_DIR, fname)
    with open(fpath, "wb") as out:
        out.write(await file.read())
    return {"url": f"/uploads/{fname}", "filename": fname}

@app.post("/translate")
async def translate_text_endpoint(req: TranslateReq):
    translated = await asyncio.to_thread(gemini_translate_text, req.text, req.target_lang)
    return {"status": "ok", "original": req.text, "translated_text": translated, "target_lang": req.target_lang}

@app.post("/api/translate/voice")
async def translate_voice_endpoint(req: VoiceTranslateReq):
    clean_url = req.audio_url.split("?")[0]
    fname = os.path.basename(clean_url)
    fpath = os.path.join(UPLOAD_DIR, fname)
    _, ext = os.path.splitext(fname)
    mime_map = {".webm": "audio/webm", ".wav": "audio/wav", ".mp3": "audio/mp3", ".m4a": "audio/m4a"}
    mime = mime_map.get(ext.lower(), "audio/webm")
    result = await asyncio.to_thread(gemini_translate_voice, fpath, mime, req.target_lang)
    return {"status": "ok", **result, "target_lang": req.target_lang}

@app.websocket("/ws/{phone}")
async def websocket_handler(ws: WebSocket, phone: str):
    p = phone.strip()
    await ws_mgr.connect(p, ws)
    try:
        while True:
            data = await ws.receive_json()
            action = data.get("action")

            if action == "ping":
                await ws.send_json({"action": "pong"})

            elif action == "chat_message":
                receiver = data.get("receiver", "").strip()
                msg_type = data.get("msg_type", "text")
                content = data.get("content", "")
                translated = data.get("translated", "")
                lang = data.get("lang", "en")

                chat_id = get_chat_id(p, receiver)
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO messages (chat_id, sender, receiver, msg_type, content, translated_content, lang)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (chat_id, p, receiver, msg_type, content, translated, lang))
                msg_id = cursor.lastrowid
                conn.commit()
                conn.close()

                out_payload = {
                    "action": "new_message",
                    "id": msg_id,
                    "sender": p,
                    "receiver": receiver,
                    "msg_type": msg_type,
                    "content": content,
                    "translated": translated,
                    "lang": lang,
                    "time": time.strftime("%H:%M"),
                    "status": "sent"
                }
                if receiver:
                    await ws_mgr.send_to(receiver, out_payload)
                await ws_mgr.send_to(p, out_payload)

            elif action == "call_signal":
                receiver = data.get("receiver", "").strip()
                if receiver:
                    data["sender"] = p
                    if ws_mgr.is_online(receiver):
                        await ws_mgr.send_to(receiver, data)
                    else:
                        await ws.send_json({
                            "action": "call_status",
                            "status": "offline"
                        })

            elif action == "call_live_caption":
                receiver = data.get("receiver", "").strip()
                if receiver:
                    data["sender"] = p
                    await ws_mgr.send_to(receiver, data)

    except WebSocketDisconnect:
        ws_mgr.disconnect(p)
    except Exception as e:
        print(f"[WS Error {p}]: {e}")
        ws_mgr.disconnect(p)

@app.get("/")
async def serve_home():
    idx = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(idx):
        return FileResponse(idx)
    return HTMLResponse("<h3>Syncora Terminal Ready. Place index.html here.</h3>")
