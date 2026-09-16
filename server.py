import os
import re
import json
import base64
import sqlite3
import urllib.request
import urllib.parse
from typing import Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

DB_PATH = os.path.join(BASE_DIR, "syncora.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            phone TEXT PRIMARY KEY,
            display_name TEXT,
            about_status TEXT DEFAULT 'Hey there! I am using Syncora.',
            avatar_url TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
            status TEXT DEFAULT 'sent',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    try:
        cursor.execute("ALTER TABLE messages ADD COLUMN status TEXT DEFAULT 'sent'")
    except Exception:
        pass

    conn.commit()
    conn.close()

init_db()

app = FastAPI(title="Syncora Terminal Core Engine")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# --- APNI GEMINI KEY YAHAN DIRECT PASTE KAREIN ---
RAW_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_KEY = RAW_KEY if RAW_KEY else "APNI_ASLI_GEMINI_API_KEY_YAHAN_LIKHEIN"

class DirectLoginRequest(BaseModel):
    phone: str

class TranslationRequest(BaseModel):
    text: str
    target_lang: str = "en"

class ProfileUpdate(BaseModel):
    phone: str
    display_name: str
    about_status: str
    avatar_url: str = ""

def get_chat_id(u1: str, u2: str) -> str:
    cleaned = sorted([u1.strip(), u2.strip()])
    return f"chat_{cleaned[0]}_{cleaned[1]}"

def is_urdu_or_arabic(text: str) -> bool:
    return bool(re.search(r'[\u0600-\u06FF]', text))

def translate_via_google(text: str, source: str, target: str) -> str:
    try:
        encoded = urllib.parse.quote(text.strip().encode('utf-8'))
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={source}&tl={target}&dt=t&q={encoded}"
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=7) as response:
            res_json = json.loads(response.read().decode('utf-8'))
            if res_json and isinstance(res_json, list) and len(res_json) > 0 and res_json[0]:
                out = "".join([part[0] for part in res_json[0] if part and part[0]]).strip()
                if out:
                    return out
    except Exception as e:
        print(f"[Google GTX Error]: {e}")
    return ""

def call_gemini_rest(prompt: str, inline_data: dict = None) -> str:
    if not GEMINI_KEY or GEMINI_KEY == "APNI_ASLI_GEMINI_API_KEY_YAHAN_LIKHEIN":
        return ""

    parts = [{"text": prompt}]
    if inline_data:
        parts.insert(0, {"inline_data": inline_data})

    payload = {
        "contents": [{"parts": parts}]
    }

    # Standard Direct REST Endpoints across models
    models_to_try = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash"]
    for m in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={GEMINI_KEY}"
        try:
            req_data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                url, 
                data=req_data, 
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req, timeout=12) as response:
                result = json.loads(response.read().decode('utf-8'))
                candidates = result.get("candidates", [])
                if candidates:
                    content = candidates[0].get("content", {})
                    c_parts = content.get("parts", [])
                    if c_parts and "text" in c_parts[0]:
                        ans = c_parts[0]["text"].strip().replace('"', '').replace("'", "")
                        if ans:
                            return ans
        except Exception as e:
            print(f"[REST Call Error {m}]: {e}")
            continue

    return ""

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

# --- AUTH & DIRECT LOGIN ---
@app.post("/api/auth/login")
async def direct_login(req: DirectLoginRequest):
    phone = req.phone.strip()
    if not phone or len(phone) < 7:
        return JSONResponse(status_code=400, content={"error": "Valid mobile number required"})

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (phone, display_name) VALUES (?, ?)", (phone, phone))
    conn.commit()
    conn.close()

    return {"status": "ok", "phone": phone}

# --- PRESENCE STATUS ---
@app.get("/api/user/status/{phone}")
async def get_user_status(phone: str):
    is_on = manager.is_online(phone.strip())
    return {"phone": phone, "online": is_on}

# --- PROFILE API ---
@app.get("/api/user/profile/{phone}")
async def get_user_profile(phone: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT phone, display_name, about_status, avatar_url, created_at FROM users WHERE phone = ?", (phone,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return {"phone": phone, "display_name": phone, "about_status": "Hey there! I am using Syncora.", "avatar_url": "", "created_at": "Recent"}
    return {
        "phone": row[0],
        "display_name": row[1] if row[1] else row[0],
        "about_status": row[2] if row[2] else "Hey there! I am using Syncora.",
        "avatar_url": row[3] if row[3] else "",
        "created_at": str(row[4])
    }

@app.post("/api/user/profile/update")
async def update_user_profile(req: ProfileUpdate):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (phone, display_name, about_status, avatar_url)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(phone) DO UPDATE SET
            display_name=excluded.display_name,
            about_status=excluded.about_status,
            avatar_url=CASE WHEN excluded.avatar_url != '' THEN excluded.avatar_url ELSE users.avatar_url END
    """, (req.phone.strip(), req.display_name.strip(), req.about_status.strip(), req.avatar_url.strip()))
    conn.commit()
    conn.close()
    return {"status": "ok", "message": "Profile updated successfully"}

# --- TEXT TRANSLATE ROUTE ---
@app.post("/translate")
async def translate_text(req: TranslationRequest):
    clean = req.text.strip()
    if not clean:
        return {"translated_text": ""}

    target_lang = req.target_lang.strip().lower() if req.target_lang else "en"
    has_script = is_urdu_or_arabic(clean)

    prompt = (
        f"Translate the following user input accurately into language code '{target_lang}'.\n"
        f"Input can be Roman Urdu, Urdu script, or Hindi.\n"
        f"- If Roman Urdu/Urdu and target is 'en', translate to clean natural English.\n"
        f"- If English and target is 'ur', translate to Urdu script.\n"
        f"Output ONLY the translated sentence, without any explanations or quotes:\n\n{clean}"
    )

    rest_ans = call_gemini_rest(prompt)
    if rest_ans:
        return {"translated_text": rest_ans}

    # Automatic Fail-Safe to Google Engine
    source_param = "ur" if has_script else "auto"
    g_res = translate_via_google(clean, source_param, target_lang)
    if g_res:
        return {"translated_text": g_res}

    return {"translated_text": clean}

# --- ACCURATE AUDIO TRANSLATION ---
@app.post("/api/translate-audio")
async def translate_audio_route(
    file_path: str = Form(...),
    target_lang: str = Form("en"),
    transcript_hint: str = Form("")
):
    chosen_target = target_lang.strip().lower() if target_lang else "en"
    translated_text = ""
    
    local_filename = os.path.basename(file_path)
    actual_path = os.path.join(UPLOAD_DIR, local_filename)

    if not os.path.exists(actual_path):
        return {"translated_text": "Voice note received", "target_lang": chosen_target, "file_path": file_path}

    try:
        with open(actual_path, "rb") as f:
            audio_bytes = f.read()

        mime_type = "audio/webm"
        if local_filename.lower().endswith(".mp4") or local_filename.lower().endswith(".m4a"):
            mime_type = "audio/mp4"
        elif local_filename.lower().endswith(".wav"):
            mime_type = "audio/wav"
        elif local_filename.lower().endswith(".mp3"):
            mime_type = "audio/mp3"

        inline_audio = {
            "mime_type": mime_type,
            "data": base64.b64encode(audio_bytes).decode('utf-8')
        }

        prompt = (
            f"Listen to this voice recording carefully. The speaker is speaking Urdu, Roman Urdu, or Hindi. "
            f"Translate their spoken words naturally and accurately into language code '{chosen_target}'. "
            f"Return ONLY the translated sentence, without quotes or additional text."
        )

        translated_text = call_gemini_rest(prompt, inline_audio)
    except Exception as e:
        print(f"[REST Audio Error]: {e}")

    # Fallback to text translation if voice decoding fails
    if not translated_text and transcript_hint and transcript_hint.strip():
        req = TranslationRequest(text=transcript_hint.strip(), target_lang=chosen_target)
        res = await translate_text(req)
        translated_text = res.get("translated_text", "")

    if not translated_text:
        translated_text = "Voice message delivered"

    return {
        "translated_text": translated_text,
        "target_lang": chosen_target,
        "file_path": file_path
    }

# --- CHATS & MESSAGES ---
@app.get("/api/chats/{phone}")
async def get_user_chats(phone: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT CASE WHEN sender = ? THEN receiver ELSE sender END AS partner
        FROM messages WHERE sender = ? OR receiver = ?
    """, (phone, phone, phone))
    partners = [row[0] for row in cursor.fetchall()]
    conn.close()
    return {"chats": partners}

@app.get("/api/messages/{phone}/{partner}")
async def get_conversation(phone: str, partner: str):
    chat_id = get_chat_id(phone, partner)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE messages SET status = 'delivered'
        WHERE chat_id = ? AND receiver = ? AND status = 'sent'
    """, (chat_id, phone))
    conn.commit()

    cursor.execute("""
        SELECT id, sender, receiver, msg_type, content, translated_content, status, created_at
        FROM messages WHERE chat_id = ? ORDER BY id ASC
    """, (chat_id,))
    rows = cursor.fetchall()
    conn.close()

    messages = [
        {
            "id": r[0], "sender": r[1], "receiver": r[2], "msg_type": r[3],
            "content": r[4], "translated_content": r[5], "status": r[6], "time": r[7]
        }
        for r in rows
    ]
    return {"messages": messages}

@app.post("/api/upload")
async def upload_media(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[1]
    if not ext:
        ext = ".webm"
    filename = f"{os.urandom(8).hex()}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(await file.read())
    return {"url": f"/uploads/{filename}"}

# --- WEBSOCKET ENGINE ---
@app.websocket("/ws/{phone}")
async def socket_endpoint(websocket: WebSocket, phone: str):
    await manager.connect(phone, websocket)
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT sender FROM messages WHERE receiver = ? AND status = 'sent'", (phone,))
        senders = [row[0] for row in cursor.fetchall()]
        cursor.execute("UPDATE messages SET status = 'delivered' WHERE receiver = ? AND status = 'sent'", (phone,))
        conn.commit()
        conn.close()

        for s in senders:
            await manager.send_to_user(s, {
                "action": "messages_delivered",
                "delivered_to": phone
            })
    except Exception as e:
        print(f"[Delivered Update Error]: {e}")

    try:
        while True:
            raw_data = await websocket.receive_text()
            payload = json.loads(raw_data)
            action = payload.get("action")
            receiver = payload.get("receiver")

            if action == "ping":
                await websocket.send_text(json.dumps({"action": "pong"}))
                continue

            if action == "chat_message":
                msg_type = payload.get("msg_type", "text")
                content = payload.get("content", "")
                translated = payload.get("translated", "")
                chat_id = get_chat_id(phone, receiver)

                is_rec_online = manager.is_online(receiver)
                initial_status = "delivered" if is_rec_online else "sent"

                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO messages (chat_id, sender, receiver, msg_type, content, translated_content, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (chat_id, phone, receiver, msg_type, content, translated, initial_status))
                msg_id = cursor.lastrowid
                conn.commit()
                conn.close()

                await manager.send_to_user(phone, {
                    "action": "message_sent_ack",
                    "id": msg_id,
                    "receiver": receiver,
                    "status": initial_status
                })

                await manager.send_to_user(receiver, {
                    "action": "new_message",
                    "id": msg_id,
                    "sender": phone,
                    "receiver": receiver,
                    "msg_type": msg_type,
                    "content": content,
                    "translated": translated,
                    "status": initial_status,
                    "time": "now"
                })

            elif action in ["call_signal", "ice_candidate"]:
                payload["sender"] = phone
                await manager.send_to_user(receiver, payload)

            elif action == "call_live_caption":
                await manager.send_to_user(receiver, {
                    "action": "call_live_caption",
                    "sender": phone,
                    "original": payload.get("original", ""),
                    "translated": payload.get("translated", ""),
                    "lang": payload.get("lang", "en")
                })

    except WebSocketDisconnect:
        manager.disconnect(phone)
    except Exception:
        manager.disconnect(phone)

@app.get("/")
async def serve_index():
    index_file = os.path.join(BASE_DIR, "index.html")
    return FileResponse(index_file)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
