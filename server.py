import os
import json
import random
import sqlite3
import urllib.request
import urllib.parse
from typing import Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import google.generativeai as genai

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

DB_PATH = "syncora.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            phone TEXT PRIMARY KEY,
            display_name TEXT,
            avatar_url TEXT,
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS otp_store (
            phone TEXT PRIMARY KEY,
            otp TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
if GEMINI_KEY:
    try:
        genai.configure(api_key=GEMINI_KEY)
    except Exception as e:
        print(f"[Gemini Config Error]: {e}")

app = FastAPI(title="Syncora Terminal Core Engine")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

class TranslationRequest(BaseModel):
    text: str
    target_lang: str = "en"

class OTPRequest(BaseModel):
    phone: str

class OTPVerify(BaseModel):
    phone: str
    otp: str
    display_name: str = ""

def get_chat_id(u1: str, u2: str) -> str:
    cleaned = sorted([u1.strip(), u2.strip()])
    return f"chat_{cleaned[0]}_{cleaned[1]}"

def direct_translate(text: str, sl: str, tl: str) -> str:
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={sl}&tl={tl}&dt=t&q=" + urllib.parse.quote(text)
        req_obj = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req_obj, timeout=5) as resp:
            raw = resp.read().decode('utf-8')
            data = json.loads(raw)
            if data and isinstance(data, list) and len(data) > 0 and data[0]:
                out = "".join([part[0] for part in data[0] if part and len(part) > 0 and part[0]])
                return out.strip()
    except Exception as e:
        print(f"[Direct Translate Error]: {e}")
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

    async def send_to_user(self, phone: str, payload: dict):
        if phone in self.active_sessions:
            try:
                await self.active_sessions[phone].send_text(json.dumps(payload))
            except Exception:
                self.disconnect(phone)

manager = ConnectionManager()

@app.post("/api/otp/send")
async def send_otp(req: OTPRequest):
    phone = req.phone.strip()
    if not phone:
        return JSONResponse(status_code=400, content={"error": "Phone number required"})
    otp_code = str(random.randint(1000, 9999))
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO otp_store (phone, otp) VALUES (?, ?)", (phone, otp_code))
    conn.commit()
    conn.close()
    return {"status": "ok", "message": "OTP sent", "otp_preview": otp_code}

@app.post("/api/otp/verify")
async def verify_otp(req: OTPVerify):
    phone = req.phone.strip()
    otp = req.otp.strip()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT otp FROM otp_store WHERE phone = ?", (phone,))
    row = cursor.fetchone()
    if not row or row[0] != otp:
        conn.close()
        return JSONResponse(status_code=400, content={"error": "Galat OTP code!"})

    cursor.execute("INSERT OR IGNORE INTO users (phone, display_name) VALUES (?, ?)", (phone, req.display_name or phone))
    cursor.execute("DELETE FROM otp_store WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()
    return {"status": "verified", "phone": phone}

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
        SELECT sender, receiver, msg_type, content, translated_content, created_at
        FROM messages WHERE chat_id = ? ORDER BY id ASC
    """, (chat_id,))
    rows = cursor.fetchall()
    conn.close()
    messages = [
        {
            "sender": r[0], "receiver": r[1], "msg_type": r[2],
            "content": r[3], "translated_content": r[4], "time": r[5]
        }
        for r in rows
    ]
    return {"messages": messages}

@app.post("/api/upload")
async def upload_media(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[1]
    filename = f"{os.urandom(8).hex()}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(await file.read())
    return {"url": f"/uploads/{filename}"}

@app.post("/translate")
async def translate_text(req: TranslationRequest):
    clean = req.text.strip()
    if not clean:
        return {"translated_text": ""}

    # 1. Gemini Translation
    if GEMINI_KEY:
        for model_name in ["gemini-2.0-flash", "gemini-1.5-flash-8b", "gemini-1.5-flash"]:
            try:
                model = genai.GenerativeModel(model_name)
                prompt = (
                    f"You are a translation API. Translate this text accurately into language '{req.target_lang}'. "
                    f"If the text is Roman Urdu (e.g., 'ap kaisy hain'), Urdu script ('آپ کیسے ہیں'), or any other language, "
                    f"provide the direct translation in '{req.target_lang}' without any notes, explanations, or quotes:\n\n{clean}"
                )
                resp = model.generate_content(prompt)
                if resp and hasattr(resp, "text") and resp.text:
                    out = resp.text.strip().replace('"', '').replace("'", "")
                    if out:
                        return {"translated_text": out}
            except Exception as e:
                print(f"[Gemini fallback]: {e}")
                continue

    # 2. Google Translate Direct Fallbacks
    res_ur = direct_translate(clean, "ur", req.target_lang)
    if res_ur and res_ur.lower() != clean.lower():
        return {"translated_text": res_ur}

    res_auto = direct_translate(clean, "auto", req.target_lang)
    if res_auto and res_auto.lower() != clean.lower():
        return {"translated_text": res_auto}

    # 3. Simple Roman-Urdu Dictionary Backup for common greetings
    common_map = {
        "ap kaisy hain": "How are you?",
        "aap kaise ho": "How are you?",
        "kya hal hai": "How are you?",
        "theek": "Fine",
        "shukriya": "Thank you"
    }
    clean_lower = clean.lower().strip("?.! ")
    if clean_lower in common_map and req.target_lang == "en":
        return {"translated_text": common_map[clean_lower]}

    return {"translated_text": clean}

@app.websocket("/ws/{phone}")
async def socket_endpoint(websocket: WebSocket, phone: str):
    await manager.connect(phone, websocket)
    try:
        while True:
            raw_data = await websocket.receive_text()
            payload = json.loads(raw_data)
            action = payload.get("action")
            receiver = payload.get("receiver")

            if action == "chat_message":
                msg_type = payload.get("msg_type", "text")
                content = payload.get("content", "")
                translated = payload.get("translated", "")
                chat_id = get_chat_id(phone, receiver)

                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO messages (chat_id, sender, receiver, msg_type, content, translated_content)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (chat_id, phone, receiver, msg_type, content, translated))
                conn.commit()
                conn.close()

                out_payload = {
                    "action": "new_message",
                    "sender": phone,
                    "receiver": receiver,
                    "msg_type": msg_type,
                    "content": content,
                    "translated": translated,
                    "time": "now"
                }
                await manager.send_to_user(receiver, out_payload)

            elif action in ["call_signal", "ice_candidate"]:
                await manager.send_to_user(receiver, payload)

    except WebSocketDisconnect:
        manager.disconnect(phone)
    except Exception:
        manager.disconnect(phone)

@app.get("/")
async def serve_index():
    return FileResponse("index.html")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
