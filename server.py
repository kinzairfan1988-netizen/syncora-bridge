import os
import re
import json
import random
import sqlite3
import urllib.request
import urllib.parse
from typing import Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import google.generativeai as genai

# Setup directories
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Database Initialization
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

# Application Definition
app = FastAPI(title="Syncora Terminal Core Engine")
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# Gemini Configuration
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
if GEMINI_KEY:
    try:
        genai.configure(api_key=GEMINI_KEY)
    except Exception as e:
        print(f"[Gemini Config Error]: {e}")

class TranslationRequest(BaseModel):
    text: str
    target_lang: str = "ur"

class OTPRequest(BaseModel):
    phone: str

class OTPVerify(BaseModel):
    phone: str
    otp: str
    display_name: str = ""

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
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            res_json = json.loads(response.read().decode('utf-8'))
            if res_json and isinstance(res_json, list) and len(res_json) > 0 and res_json[0]:
                out = "".join([part[0] for part in res_json[0] if part and part[0]]).strip()
                if out:
                    return out
    except Exception as e:
        print(f"[Google GTX Error]: {e}")
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

# --- TEXT TRANSLATION ROUTE ---
@app.post("/translate")
async def translate_text(req: TranslationRequest):
    clean = req.text.strip()
    if not clean:
        return {"translated_text": ""}

    target_lang = req.target_lang.strip().lower()
    has_script = is_urdu_or_arabic(clean)

    # Gemini Engine Attempt
    if GEMINI_KEY:
        for model_name in ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]:
            try:
                model = genai.GenerativeModel(model_name)
                prompt = (
                    f"Translate the following text strictly into target language '{target_lang}'.\n"
                    f"- If input is Roman Urdu (e.g. 'ap kaisy hain') or Urdu script and target is 'en', translate to clean natural English.\n"
                    f"- If input is English and target is 'ur', translate to natural Urdu script.\n"
                    f"Return ONLY the direct translation, no quotes, notes or explanations:\n\n{clean}"
                )
                response = model.generate_content(prompt)
                if response and hasattr(response, "text") and response.text:
                    out = response.text.strip().replace('"', '').replace("'", "")
                    if out and out.lower() != clean.lower():
                        return {"translated_text": out}
            except Exception as e:
                print(f"[Gemini Exception {model_name}]: {e}")
                continue

    # Google Translate Direct Fallback
    source_guess = "ur" if has_script else "auto"
    g_res = translate_via_google(clean, source_guess, target_lang)
    if g_res and g_res.lower() != clean.lower():
        return {"translated_text": g_res}

    if target_lang == "en":
        g_res_ur = translate_via_google(clean, "ur", "en")
        if g_res_ur and g_res_ur.lower() != clean.lower():
            return {"translated_text": g_res_ur}

    # Common Dictionary Fallback
    local_dict = {
        "ap kaisy hain": "How are you?",
        "aap kaise hain": "How are you?",
        "aap kaise ho": "How are you?",
        "kya hal hai": "How are you?",
        "kya ho raha hai": "What is happening?",
        "main theek hoon": "I am fine.",
        "shukriya": "Thank you.",
        "آپ کیسے ہیں": "How are you?",
        "آپ کیسے ہو": "How are you?",
        "کیا حال ہے": "How are you?",
        "کیا کر رہے ہیں": "What are you doing?",
        "how are you": "آپ کیسے ہیں؟",
        "what are you doing": "آپ کیا کر رہے ہیں؟",
        "where are you": "آپ کہاں ہیں؟",
        "i am fine": "میں ٹھیک ہوں۔",
        "thank you": "شکریہ۔",
        "hello": "ہیلو",
        "good morning": "صبح بخیر"
    }

    norm_key = re.sub(r'[^\w\s]', '', clean.lower()).strip()
    if norm_key in local_dict:
        return {"translated_text": local_dict[norm_key]}

    return {"translated_text": clean}

# --- AUDIO MULTIMODAL TRANSLATION ROUTE ---
@app.post("/api/translate-audio")
async def translate_audio_route(
    file_path: str = Form(...),
    target_lang: str = Form("en")
):
    try:
        # File URL se local file path nikalna
        local_filename = os.path.basename(file_path)
        actual_path = os.path.join(UPLOAD_DIR, local_filename)

        if not os.path.exists(actual_path):
            return JSONResponse(status_code=404, content={"translated_text": "", "error": "Audio file not found"})

        if GEMINI_KEY:
            for model_name in ["gemini-1.5-flash", "gemini-2.0-flash"]:
                try:
                    # Upload audio to Gemini API
                    audio_file = genai.upload_file(path=actual_path)
                    model = genai.GenerativeModel(model_name)
                    prompt = (
                        f"Listen carefully to this voice note. The speaker may speak in Urdu, Roman Urdu, Hindi, or English. "
                        f"Translate what they are saying into target language code '{target_lang}'. "
                        f"Provide ONLY the direct translated sentence as clear text without any introductory labels or quotes."
                    )
                    resp = model.generate_content([prompt, audio_file])
                    if resp and hasattr(resp, "text") and resp.text:
                        out = resp.text.strip().replace('"', '').replace("'", "")
                        return {"translated_text": out}
                except Exception as e:
                    print(f"[Gemini Audio Exception {model_name}]: {e}")
                    continue

        return {"translated_text": "Audio Translation (Voice Note processed)"}
    except Exception as e:
        print(f"[Audio Translate Root Error]: {e}")
        return {"translated_text": ""}

# --- OTP ENDPOINTS ---
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

# --- CHAT & HISTORY ENDPOINTS ---
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
    if not ext:
        ext = ".webm"
    filename = f"{os.urandom(8).hex()}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(await file.read())
    return {"url": f"/uploads/{filename}"}

# --- WEBSOCKET ROUTING ---
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
