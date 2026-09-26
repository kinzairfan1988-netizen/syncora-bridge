import os
import shutil
from fastapi import FastAPI, File, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import google.generativeai as genai

# Gemini API Configuration (Apni API key yahan set ya environment se lein)
# genai.configure(api_key=os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY"))

app = FastAPI()

# Directory setup for uploads and static files
os.makedirs("uploads", exist_ok=True)
os.makedirs("static", exist_ok=True)

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Active WebSocket connections storage
active_connections: dict[str, WebSocket] = {}
user_profiles: dict[str, dict] = {}
user_contacts: dict[str, list] = {}
message_history: dict[str, list] = {}

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
    return "<h3>index.html not found on server root!</h3>"

@app.post("/api/auth/login")
async def login_user(req: LoginRequest):
    phone = req.phone.strip()
    if phone not in user_profiles:
        user_profiles[phone] = {
            "phone": phone,
            "display_name": f"User {phone[-4:]}",
            "about_status": "Hey there! I am using Syncora.",
            "avatar_url": ""
        }
    if phone not in user_contacts:
        user_contacts[phone] = []
    return {"status": "success", "phone": phone}

@app.get("/api/user/profile/{phone}")
async def get_profile(phone: str):
    return user_profiles.get(phone, {"phone": phone, "display_name": phone, "about_status": "", "avatar_url": ""})

@app.post("/api/user/profile/update")
async def update_profile(req: ProfileUpdate):
    user_profiles[req.phone] = {
        "phone": req.phone,
        "display_name": req.display_name,
        "about_status": req.about_status,
        "avatar_url": req.avatar_url
    }
    return {"status": "success"}

@app.get("/api/user/status/{phone}")
async def get_user_status(phone: str):
    is_online = phone in active_connections
    return {"phone": phone, "online": is_online}

@app.get("/api/chats/{phone}")
async def get_chats(phone: str):
    contacts = user_contacts.get(phone, [])
    return {"chats": contacts}

@app.post("/api/contacts/add")
async def add_contact(req: ContactRequest):
    if req.user_phone not in user_contacts:
        user_contacts[req.user_phone] = []
    if req.contact_phone not in user_contacts[req.user_phone]:
        user_contacts[req.user_phone].append(req.contact_phone)
        
    if req.contact_phone not in user_contacts:
        user_contacts[req.contact_phone] = []
    if req.user_phone not in user_contacts[req.contact_phone]:
        user_contacts[req.contact_phone].append(req.user_phone)
        
    return {"status": "success"}

@app.get("/api/messages/{phone1}/{phone2}")
async def get_messages(phone1: str, phone2: str):
    key1 = f"{phone1}_{phone2}"
    key2 = f"{phone2}_{phone1}"
    msgs = message_history.get(key1, message_history.get(key2, []))
    return {"messages": msgs}

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    file_path = os.path.join("uploads", file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"url": f"/uploads/{file.filename}"}

# --- NEW SPEECH-TO-TEXT ENDPOINT FOR GEMINI AI ---
@app.post("/api/stt")
async def speech_to_text(file: UploadFile = File(...)):
    try:
        audio_bytes = await file.read()
        temp_filename = os.path.join("uploads", file.filename or "voice.webm")
        with open(temp_filename, "wb") as f:
            f.write(audio_bytes)
            
        # Gemini API call for audio transcription & translation
        try:
            audio_file_ref = genai.upload_file(temp_filename)
            model = genai.GenerativeModel("gemini-1.5-flash")
            response = model.generate_content([
                audio_file_ref, 
                "Listen to this voice note. Transcribe what is spoken and return only the clear resulting text."
            ])
            transcribed_text = response.text.strip() if response and response.text else "voice message"
        except Exception:
            transcribed_text = "voice message"
            
        return {"text": transcribed_text, "url": f"/uploads/{file.filename or 'voice.webm'}"}
    except Exception as e:
        return {"text": "voice message", "url": ""}

@app.post("/translate")
async def translate_text(req: TranslateRequest):
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"Translate the following text into target language code '{req.target_lang}' (e.g. ur for Urdu, en for English, ar for Arabic, zh for Chinese, de for German, fr for French, es for Spanish). Return ONLY the translated text without extra quotes or notes:\n\n{req.text}"
        response = model.generate_content(prompt)
        translated = response.text.strip() if response and response.text else req.text
        return {"translated_text": translated}
    except Exception as e:
        return {"translated_text": req.text}

@app.websocket("/ws/{phone}")
async def websocket_endpoint(websocket: WebSocket, phone: str):
    await websocket.accept()
    active_connections[phone] = "connected"
    print(f"connection open for {phone}")
    
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            
            if action == "ping":
                await websocket.send_json({"action": "pong"})
                continue
                
            if action == "chat_message":
                receiver = data.get("receiver")
                msg_payload = {
                    "id": str(os.urandom(4).hex()),
                    "sender": phone,
                    "receiver": receiver,
                    "msg_type": data.get("msg_type", "text"),
                    "content": data.get("content"),
                    "translated_content": data.get("translated", ""),
                    "lang": data.get("lang", "en"),
                    "time": "just now",
                    "status": "delivered"
                }
                
                # Save to history
                key1 = f"{phone}_{receiver}"
                key2 = f"{receiver}_{phone}"
                if key1 not in message_history and key2 not in message_history:
                    message_history[key1] = []
                target_key = key1 if key1 in message_history else (key2 if key2 in message_history else key1)
                message_history[target_key].append(msg_payload)
                
                # Forward to receiver if online
                if receiver in active_connections:
                    # Note: In production, track WS objects directly. Here we simulate websocket routing.
                    pass
                    
            elif action == "call_signal" or action == "call_live_caption":
                # Forward signaling / live captions
                receiver = data.get("receiver")
                if receiver in active_connections:
                    pass

    except WebSocketDisconnect:
        if phone in active_connections:
            del active_connections[phone]
        print(f"connection closed for {phone}")
