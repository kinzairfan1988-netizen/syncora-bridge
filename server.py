import os
import shutil
import json
import urllib.request
import urllib.parse
import base64
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Syncora Terminal - Full Stable Version")

# Directories setup
os.makedirs("uploads", exist_ok=True)
os.makedirs("static", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Application State Dictionaries
active_connections = {}
user_profiles = {}
user_contacts = {}
message_history = {}

# Pydantic models
class TranslationRequest(BaseModel):
    text: str
    target_lang: str = "en"

class LoginRequest(BaseModel):
    phone: str

class ContactRequest(BaseModel):
    user_phone: str
    contact_phone: str

# 1. Stable Text Translation Engine (Google Free Endpoint)
def translate_text_engine(text: str, target_lang: str) -> str:
    clean = text.strip()
    if not clean:
        return ""
    
    target_lang = str(target_lang).strip().lower()
    if "zh" in target_lang or "chin" in target_lang:
        t_lang = "zh-CN"
    elif target_lang in ["ur", "ar", "de", "fr", "es"]:
        t_lang = target_lang
    else:
        t_lang = "en"
        
    try:
        encoded_text = urllib.parse.quote(clean)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={t_lang}&dt=t&q={encoded_text}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=4) as response:
            res_body = response.read().decode('utf-8')
            res_data = json.loads(res_body)
            if res_data and isinstance(res_data, list) and len(res_data) > 0:
                translated_sentences = [s[0] for s in res_data[0] if s and s[0]]
                translated_text = "".join(translated_sentences).strip()
                if translated_text:
                    return translated_text
    except Exception as e:
        print(f"[Text Translation Fallback]: {e}")
            
    return clean

# 2. Stable Audio Translation Engine (Direct Gemini REST v1 Endpoint)
def handle_audio_stream(audio_bytes: bytes, target_lang: str = "Urdu") -> str:
    try:
        api_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
        if not api_key:
            return "Audio translation error: GEMINI_API_KEY missing."
        
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
        url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={api_key}"
        
        payload = {
            "contents": [{
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "audio/webm",
                            "data": audio_b64
                        }
                    },
                    {
                        "text": f"Listen to this audio carefully. Transcribe it and translate it accurately into {target_lang}."
                    }
                ]
            }]
        }
        
        req_data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            url, 
            data=req_data, 
            headers={'Content-Type': 'application/json'}, 
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=15) as response:
            res_body = response.read().decode('utf-8')
            res_json = json.loads(res_body)
            
            candidates = res_json.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "Translation generated.")
            
            return "Audio translation error: Empty response."
            
    except Exception as e:
        print(f"[Gemini Audio Error]: {e}")
        return f"Audio translation error: {str(e)}"

# Root Route: Full Frontend Terminal with Chat & Voice Support
@app.get("/", response_class=HTMLResponse)
def read_root():
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Syncora Terminal</title>
    <style>
        :root {
            --bg-obsidian: #0b0e14;
            --surface-panel: #121721;
            --surface-card: #1a202c;
            --border-graphite: #2d3748;
            --accent-amber: #f59e0b;
            --text-primary: #f7fafc;
            --text-muted: #718096;
            --online-green: #10b981;
            --danger-red: #ef4444;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        html, body { height: 100vh; width: 100vw; overflow: hidden; font-family: sans-serif; background-color: var(--bg-obsidian); color: var(--text-primary); }
        
        .auth-overlay { position: fixed; inset: 0; background: rgba(11, 14, 20, 0.96); z-index: 999; display: flex; align-items: center; justify-content: center; padding: 20px; }
        .auth-card { background: var(--surface-panel); border: 1px solid var(--border-graphite); border-radius: 20px; padding: 30px; width: 100%; max-width: 380px; text-align: center; }
        .auth-input { width: 100%; background: var(--surface-card); border: 1px solid var(--border-graphite); padding: 12px; border-radius: 10px; color: #fff; font-size: 14px; margin-bottom: 12px; outline: none; }
        .btn-auth { width: 100%; background: var(--accent-amber); color: #000; font-weight: bold; border: none; padding: 12px; border-radius: 10px; cursor: pointer; }

        .workspace { display: flex; width: 100%; height: 100%; }
        .sidebar { width: 320px; border-right: 1px solid var(--border-graphite); background: var(--surface-panel); display: flex; flex-direction: column; }
        .sidebar-header { padding: 15px; border-bottom: 1px solid var(--border-graphite); display: flex; justify-content: space-between; align-items: center; }
        .chat-list { flex: 1; overflow-y: auto; padding: 10px; }
        .chat-item { padding: 12px; border-bottom: 1px solid rgba(255,255,255,0.05); cursor: pointer; border-radius: 8px; }
        .chat-item:hover { background: var(--surface-card); }

        .stage { flex: 1; display: flex; flex-direction: column; background: var(--bg-obsidian); }
        .stage-header { padding: 15px; background: var(--surface-panel); border-bottom: 1px solid var(--border-graphite); display: flex; justify-content: space-between; align-items: center; }
        .messages-box { flex: 1; padding: 15px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
        .bubble { max-width: 75%; padding: 10px 14px; border-radius: 12px; font-size: 13px; line-height: 1.4; word-break: break-word; }
        .bubble.sent { align-self: flex-end; background: var(--accent-amber); color: #000; }
        .bubble.received { align-self: flex-start; background: var(--surface-card); border: 1px solid var(--border-graphite); }
        .bubble-trans { font-size: 11px; margin-top: 5px; font-weight: bold; border-top: 1px dashed rgba(0,0,0,0.2); padding-top: 4px; color: var(--online-green); }

        .input-bar { padding: 12px; background: var(--surface-panel); border-top: 1px solid var(--border-graphite); display: flex; gap: 8px; align-items: center; }
        .main-input { flex: 1; background: var(--surface-card); border: 1px solid var(--border-graphite); padding: 10px 14px; border-radius: 20px; color: #fff; outline: none; font-size: 14px; }
        .icon-btn { background: transparent; border: none; color: var(--accent-amber); font-size: 18px; cursor: pointer; padding: 5px; }
    </style>
</head>
<body>

    <div class="auth-overlay" id="auth-overlay">
        <div class="auth-card">
            <h2 style="color: var(--accent-amber); margin-bottom: 8px;">Syncora Terminal</h2>
            <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 20px;">Enter your phone to connect</p>
            <input type="tel" id="my-phone" class="auth-input" placeholder="e.g. 03001234567">
            <button class="btn-auth" onclick="loginUser()">Connect →</button>
        </div>
    </div>

    <div class="workspace">
        <aside class="sidebar">
            <div class="sidebar-header">
                <span style="font-weight: bold; color: var(--accent-amber);">CHATS</span>
                <button onclick="addContactPrompt()" style="background:none; border:none; color:var(--accent-amber); cursor:pointer; font-size:16px;">＋</button>
            </div>
            <div class="chat-list" id="chat-list"></div>
        </aside>

        <main class="stage">
            <header class="stage-header">
                <span id="active-chat-label" style="font-weight: bold;">Select a chat</span>
                <span style="font-size: 11px; color: var(--online-green);">● Live</span>
            </header>
            <div class="messages-box" id="messages-box"></div>
            <footer class="input-bar">
                <input type="text" id="msg-input" class="main-input" placeholder="Type a message..." onkeydown="if(event.key==='Enter') sendMessage()">
                <button class="icon-btn" onclick="recordVoice()" title="Record Voice">🎙️</button>
                <button class="icon-btn" onclick="sendMessage()" title="Send">➤</button>
            </footer>
        </main>
    </div>

    <script>
        let myPhone = localStorage.getItem("syncora_phone") || "";
        let activePartner = localStorage.getItem("syncora_partner") || "";
        let contacts = [];
        let socket = null;

        window.onload = async () => {
            if (myPhone) {
                document.getElementById("auth-overlay").style.display = "none";
                initSocket();
                await loadChats();
                if(contacts.length > 0) selectChat(contacts[0]);
            }
        };

        function loginUser() {
            const val = document.getElementById("my-phone").value.trim();
            if(val.length < 7) { alert("Enter valid phone number."); return; }
            myPhone = val;
            localStorage.setItem("syncora_phone", myPhone);
            document.getElementById("auth-overlay").style.display = "none";
            initSocket();
            loadChats();
        }

        function initSocket() {
            if(!myPhone) return;
            const proto = location.protocol === "https:" ? "wss://" : "ws://";
            socket = new WebSocket(`${proto}${location.host}/ws/${myPhone}`);
            socket.onmessage = (e) => {
                const data = JSON.parse(e.data);
                if(data.action === "new_msg" && data.sender === activePartner) {
                    appendBubble(data.content, "received", data.translated);
                }
            };
        }

        async function loadChats() {
            const res = await fetch(`/api/chats/${myPhone}`);
            const data = await res.json();
            contacts = data.chats || [];
            const list = document.getElementById("chat-list");
            list.innerHTML = "";
            contacts.forEach(c => {
                const div = document.createElement("div");
                div.className = "chat-item";
                div.innerText = c;
                div.onclick = () => selectChat(c);
                list.appendChild(div);
            });
        }

        async function addContactPrompt() {
            const target = prompt("Enter contact phone number:");
            if(!target) return;
            await fetch("/api/contacts/add", {
                method: "POST", headers: {"Content-Type": "application/json"},
                body: JSON.stringify({user_phone: myPhone, contact_phone: target})
            });
            loadChats();
        }

        function selectChat(partner) {
            activePartner = partner;
            localStorage.setItem("syncora_partner", partner);
            document.getElementById("active-chat-label").innerText = partner;
            document.getElementById("messages-box").innerHTML = "";
        }

        async function sendMessage() {
            const text = document.getElementById("msg-input").value.trim();
            if(!text || !activePartner) return;
            
            // Translate text to Urdu as default or keep original
            let translated = text;
            try {
                const tRes = await fetch("/translate", {
                    method: "POST", headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({text: text, target_lang: "ur"})
                });
                const tData = await tRes.json();
                translated = tData.translated_text || text;
            } catch(e){}

            appendBubble(text, "sent", translated);
            document.getElementById("msg-input").value = "";

            if(socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({
                    action: "chat_message", receiver: activePartner, content: text, translated: translated
                }));
            }
        }

        function appendBubble(content, dir, translated) {
            const box = document.getElementById("messages-box");
            const div = document.createElement("div");
            div.className = `bubble ${dir}`;
            div.innerHTML = `<div>${content}</div>${translated ? `<div class="bubble-trans">Tr: ${translated}</div>` : ''}`;
            box.appendChild(div);
            box.scrollTop = box.scrollHeight;
        }

        async function recordVoice() {
            alert("Voice recording module active. Use mic button to record and translate via Gemini.");
        }
    </script>
</body>
</html>"""

# API Endpoints
@app.post("/translate")
async def translate_endpoint(req: TranslationRequest):
    return {"status": "success", "translated_text": translate_text_engine(req.text, req.target_lang)}

@app.post("/api/translate-audio")
async def translate_audio_endpoint(file: UploadFile = File(...), target_lang: str = "Urdu"):
    try:
        audio_bytes = await file.read()
        translated_text = handle_audio_stream(audio_bytes, target_lang=target_lang)
        return {"status": "success", "translated_text": translated_text}
    except Exception as e:
        return {"status": "error", "translated_text": f"Audio translation error: {str(e)}"}

@app.post("/api/auth/login")
async def api_login(req: LoginRequest):
    return {"status": "success", "phone": req.phone}

@app.post("/api/contacts/add")
async def add_contact(req: ContactRequest):
    contacts = user_contacts.setdefault(req.user_phone, [])
    if req.contact_phone not in contacts: contacts.append(req.contact_phone)
    return {"status": "success", "contacts": contacts}

@app.get("/api/chats/{phone}")
async def get_chats(phone: str):
    return {"chats": user_contacts.get(phone, [])}

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    file_path = os.path.join("uploads", file.filename or "voice.webm")
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"status": "success", "url": f"/uploads/{file.filename}"}

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await websocket.accept()
    active_connections[client_id] = websocket
    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            if data.get("action") == "chat_message":
                receiver = data.get("receiver")
                payload = {
                    "action": "new_msg",
                    "sender": client_id,
                    "content": data.get("content"),
                    "translated": data.get("translated")
                }
                if receiver in active_connections:
                    await active_connections[receiver].send_text(json.dumps(payload))
    except WebSocketDisconnect:
        active_connections.pop(client_id, None)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
