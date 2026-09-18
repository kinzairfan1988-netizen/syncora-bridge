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
    conn = sqlite3.connect(DB_PATH, timeout=15)
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
    try:
        cursor.execute("ALTER TABLE messages ADD COLUMN status TEXT DEFAULT 'sent'")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE messages ADD COLUMN lang TEXT DEFAULT 'en'")
    except Exception:
        pass

    conn.commit()
    conn.close()

init_db()

app = FastAPI(title="Syncora Terminal Core Engine")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

class DirectLoginRequest(BaseModel):
    phone: str

class AddContactRequest(BaseModel):
    user_phone: str
    contact_phone: str

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

def has_urdu_arabic_script(text: str) -> bool:
    return bool(re.search(r'[\u0600-\u06FF]', text))

# Robust Rotary Translation (Mobile & Web Compatible)
def translate_robust(text: str, target_lang: str) -> str:
    clean = text.strip()
    if not clean:
        return ""

    target_lang = target_lang.strip().lower()
    is_script_urdu = has_urdu_arabic_script(clean)
    
    # Tier 1: Google Single Endpoint (Handles Urdu Script & Roman Urdu)
    try:
        source_param = "ur" if is_script_urdu else "auto"
        q_enc = urllib.parse.quote(clean.encode('utf-8'))
        url_g = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={source_param}&tl={target_lang}&dt=t&q={q_enc}"
        req_g = urllib.request.Request(url_g, headers={
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36'
        })
        with urllib.request.urlopen(req_g, timeout=5) as response:
            res_json = json.loads(response.read().decode('utf-8'))
            if res_json and isinstance(res_json, list) and len(res_json) > 0 and res_json[0]:
                out = "".join([part[0] for part in res_json[0] if part and part[0]]).strip()
                if out and out.lower() != clean.lower():
                    return out
    except Exception as e:
        print(f"[Tier 1 Error]: {e}")

    # Tier 2: MyMemory API Fallback
    try:
        src_pair = "ur" if is_script_urdu else ("ur" if target_lang != "ur" else "en")
        if src_pair != target_lang:
            q_enc = urllib.parse.quote(clean.encode('utf-8'))
            pair = f"{src_pair}|{target_lang}"
            url_mm = f"https://api.mymemory.translated.net/get?q={q_enc}&langpair={pair}"
            req_mm = urllib.request.Request(url_mm, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req_mm, timeout=5) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                if res_data and "responseData" in res_data and res_data["responseData"]["translatedText"]:
                    out_text = res_data["responseData"]["translatedText"].strip()
                    if out_text and not out_text.startswith("PLEASE SELECT") and not out_text.startswith("MYMEMORY WARNING") and out_text.lower() != "bruh":
                        return out_text
    except Exception as e:
        print(f"[Tier 2 Error]: {e}")

    # Tier 3: Lingva Relay
    try:
        q_enc = urllib.parse.quote(clean.encode('utf-8'))
        src_lingva = "ur" if (is_script_urdu or target_lang == "en") else "auto"
        if src_lingva != target_lang:
            url_l = f"https://lingva.ml/api/v1/{src_lingva}/{target_lang}/{q_enc}"
            req_l = urllib.request.Request(url_l, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req_l, timeout=5) as response:
                res_json = json.loads(response.read().decode('utf-8'))
                if "translation" in res_json and res_json["translation"]:
                    out_l = res_json["translation"].strip()
                    if out_l:
                        return out_l
    except Exception as e:
        print(f"[Tier 3 Error]: {e}")

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
    if not phone or len(phone) < 7:
        return JSONResponse(status_code=400, content={"error": "Valid mobile number required"})

    conn = sqlite3.connect(DB_PATH, timeout=15)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (phone, display_name) VALUES (?, ?)", (phone, phone))
    conn.commit()
    conn.close()

    return {"status": "ok", "phone": phone}

# Lifetime Contacts Registration (Both ways)
@app.post("/api/contacts/add")
async def add_permanent_contact(req: AddContactRequest):
    u = req.user_phone.strip()
    c = req.contact_phone.strip()
    if not u or not c or u == c:
        return JSONResponse(status_code=400, content={"error": "Invalid phones"})

    conn = sqlite3.connect(DB_PATH, timeout=15)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO user_contacts (user_phone, contact_phone) VALUES (?, ?)", (u, c))
    cursor.execute("INSERT OR IGNORE INTO user_contacts (user_phone, contact_phone) VALUES (?, ?)", (c, u))
    cursor.execute("INSERT OR IGNORE INTO users (phone, display_name) VALUES (?, ?)", (c, c))
    cursor.execute("INSERT OR IGNORE INTO users (phone, display_name) VALUES (?, ?)", (u, u))
    conn.commit()
    conn.close()
    return {"status": "ok", "message": "Contact saved permanently"}

@app.get("/api/user/status/{phone}")
async def get_user_status(phone: str):
    return {"phone": phone, "online": manager.is_online(phone.strip())}

@app.get("/api/user/profile/{phone}")
async def get_user_profile(phone: str):
    conn = sqlite3.connect(DB_PATH, timeout=15)
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
    conn = sqlite3.connect(DB_PATH, timeout=15)
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

@app.post("/translate")
async def translate_text(req: TranslationRequest):
    clean = req.text.strip()
    if not clean:
        return {"translated_text": ""}

    target_lang = req.target_lang.strip().lower() if req.target_lang else "en"
    translated = translate_robust(clean, target_lang)
    return {"translated_text": translated}

# Stable Chats Listing (Messages + Saved Contacts)
@app.get("/api/chats/{phone}")
async def get_user_chats(phone: str):
    p = phone.strip()
    conn = sqlite3.connect(DB_PATH, timeout=15)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT DISTINCT CASE WHEN sender = ? THEN receiver ELSE sender END AS partner
        FROM messages WHERE sender = ? OR receiver = ?
    """, (p, p, p))
    msg_partners = [row[0] for row in cursor.fetchall() if row[0]]

    cursor.execute("""
        SELECT contact_phone FROM user_contacts WHERE user_phone = ?
    """, (p,))
    saved_contacts = [row[0] for row in cursor.fetchall() if row[0]]

    conn.close()

    all_unique = []
    for item in (saved_contacts + msg_partners):
        if item and item != p and item not in all_unique:
            all_unique.append(item)

    return {"chats": all_unique}

@app.get("/api/messages/{phone}/{partner}")
async def get_conversation(phone: str, partner: str):
    chat_id = get_chat_id(phone, partner)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE messages SET status = 'delivered'
        WHERE chat_id = ? AND receiver = ? AND status = 'sent'
    """, (chat_id, phone))
    conn.commit()

    cursor.execute("""
        SELECT id, sender, receiver, msg_type, content, translated_content, status, created_at, lang
        FROM messages WHERE chat_id = ? ORDER BY id ASC
    """, (chat_id,))
    rows = cursor.fetchall()
    conn.close()

    messages = [
        {
            "id": r[0], "sender": r[1], "receiver": r[2], "msg_type": r[3],
            "content": r[4], "translated_content": r[5], "status": r[6], "time": r[7],
            "lang": r[8] if len(r) > 8 and r[8] else "en"
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

@app.websocket("/ws/{phone}")
async def socket_endpoint(websocket: WebSocket, phone: str):
    await manager.connect(phone, websocket)
    
    try:
        conn = sqlite3.connect(DB_PATH, timeout=15)
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
        print(f"[Delivered Error]: {e}")

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
                lang = payload.get("lang", "en")
                chat_id = get_chat_id(phone, receiver)

                is_rec_online = manager.is_online(receiver)
                initial_status = "delivered" if is_rec_online else "sent"

                conn = sqlite3.connect(DB_PATH, timeout=15)
                cursor = conn.cursor()
                cursor.execute("INSERT OR IGNORE INTO user_contacts (user_phone, contact_phone) VALUES (?, ?)", (phone, receiver))
                cursor.execute("INSERT OR IGNORE INTO user_contacts (user_phone, contact_phone) VALUES (?, ?)", (receiver, phone))
                cursor.execute("""
                    INSERT INTO messages (chat_id, sender, receiver, msg_type, content, translated_content, lang, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (chat_id, phone, receiver, msg_type, content, translated, lang, initial_status))
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
                    "lang": lang,
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
