import os
import shutil
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    import google.generativeai as genai
    HAS_GEMINI = True
    # Agar aapki API key environment variable mein nahi hai, toh aap yahan direct bhi set kar sakte hain:
    # genai.configure(api_key="YOUR_GEMINI_API_KEY")
except ImportError:
    HAS_GEMINI = False

app = FastAPI()

os.makedirs("uploads", exist_ok=True)
os.makedirs("static", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

active_connections = {}
user_profiles = {}
user_contacts = {}
message_history = {}

class LoginRequest(BaseModel):
    phone: str

class ProfileUpdate(BaseModel):
    phone: str
    display_name: str = ""
    about_status: str = ""
    avatar_url: str = ""

class ContactRequest(BaseModel):
    user_phone: str
    contact_phone: str

class TranslateRequest(BaseModel):
    text: str
    target_lang: str = "en"

@app.get("/", response_class=HTMLResponse)
async def get_terminal():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h3>index.html not found!</h3>"

@app.post("/api/auth/login")
async def login_user(req: LoginRequest):
    phone = req.phone.strip()
    if phone not in user_profiles:
        user_profiles[phone] = {"phone": phone, "display_name": f"User {phone[-4:]}", "about_status": "Hey there! I am using Syncora.", "avatar_url": ""}
    if phone not in user_contacts:
        user_contacts[phone] = []
    return {"status": "success", "phone": phone}

@app.get("/api/user/profile/{phone}")
async def get_profile(phone: str):
    return user_profiles.get(phone, {"phone": phone, "display_name": phone, "about_status": "", "avatar_url": ""})

@app.post("/api/user/profile/update")
async def update_profile(req: ProfileUpdate):
    user_profiles[req.phone] = {"phone": req.phone, "display_name": req.display_name, "about_status": req.about_status, "avatar_url": req.avatar_url}
    return {"status": "success"}

@app.get("/api/user/status/{phone}")
async def get_user_status(phone: str):
    return {"phone": phone, "online": phone in active_connections}

@app.get("/api/chats/{phone}")
async def get_chats(phone: str):
    return {"chats": user_contacts.get(phone, [])}

@app.post("/api/contacts/add")
async def add_contact(req: ContactRequest):
    if req.user_phone not in user_contacts: user_contacts[req.user_phone] = []
    if req.contact_phone not in user_contacts[req.user_phone]: user_contacts[req.user_phone].append(req.contact_phone)
    return {"status": "success"}

@app.get("/api/messages/{phone1}/{phone2}")
async def get_messages(phone1: str, phone2: str):
    key = f"{phone1}_{phone2}"
    return {"messages": message_history.get(key, [])}

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    file_path = os.path.join("uploads", file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"url": f"/uploads/{file.filename}"}

# --- ASAL GEMINI AUDIO TRANSCRIPTION (STT) ENDPOINT ---
@app.post("/api/stt")
async def speech_to_text(file: UploadFile = File(...)):
    file_path = os.path.join("uploads", file.filename or "voice.webm")
    try:
        audio_bytes = await file.read()
        with open(file_path, "wb") as f:
            f.write(audio_bytes)
        
        transcribed_text = "voice message"
        if HAS_GEMINI:
            try:
                audio_file = genai.upload_file(file_path)
                model = genai.GenerativeModel("gemini-1.5-flash")
                response = model.generate_content([
                    audio_file, 
                    "Listen to this audio recording. Accurately transcribe what is spoken. Return ONLY the transcribed text without extra quotes or formatting."
                ])
                if response and response.text:
                    transcribed_text = response.text.strip()
            except Exception as ex:
                print("Gemini STT processing error:", ex)
                
        return {"text": transcribed_text, "url": f"/uploads/{file.filename or 'voice.webm'}"}
    except Exception as e:
        print("STT Error:", e)
        return {"text": "voice message", "url": f"/uploads/{file.filename or 'voice.webm'}"}

@app.post("/translate")
async def translate_text(req: TranslateRequest):
    try:
        if HAS_GEMINI:
            model = genai.GenerativeModel("gemini-1.5-flash")
            response = model.generate_content(f"Translate the following text into target language '{req.target_lang}' (e.g. ur for Urdu, en for English). Return ONLY the translated text without extra formatting:\n\n{req.text}")
            return {"translated_text": response.text.strip() if response and response.text else req.text}
        else:
            return {"translated_text": req.text}
    except Exception:
        return {"translated_text": req.text}

@app.websocket("/ws/{phone}")
async def websocket_endpoint(websocket: WebSocket, phone: str):
    await websocket.accept()
    active_connections[phone] = websocket
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("action") == "ping":
                await websocket.send_json({"action": "pong"})
    except WebSocketDisconnect:
        if phone in active_connections:
            del active_connections[phone]
