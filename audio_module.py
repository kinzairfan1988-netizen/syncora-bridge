import os
import shutil
import json
import urllib.request
import urllib.parse
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Syncora Terminal - Final Bulletproof Server")

# Directories setup
os.makedirs("uploads", exist_ok=True)
os.makedirs("static", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

active_connections = {}
user_profiles = {}
user_contacts = {}
message_history = {}

class TranslationRequest(BaseModel):
    text: str
    target_lang: str = "en"

class LoginRequest(BaseModel):
    phone: str

class ContactRequest(BaseModel):
    user_phone: str
    contact_phone: str

def translate_text_engine(text: str, target_lang: str) -> str:
    clean = text.strip()
    if not clean:
        return ""
    target_lang = str(target_lang).strip().lower()
    t_lang = target_lang if target_lang in ["ur", "ar", "de", "fr", "es", "zh-cn"] else "en"
    try:
        encoded_text = urllib.parse.quote(clean)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={t_lang}&dt=t&q={encoded_text}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=3) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            if res_data and isinstance(res_data, list):
                return "".join([s[0] for s in res_data[0] if s and s[0]]).strip()
    except Exception:
        pass
    return f"[{t_lang.upper()}] {clean}"

@app.get("/", response_class=HTMLResponse)
def read_root():
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Syncora Terminal</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700&family=Space+Grotesk:wght@700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0b0e14; --panel: #121721; --card: #1a202c; --border: #2d3748;
            --accent: #f59e0b; --text: #f7fafc; --muted: #718096; --green: #10b981;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        html, body { height: 100vh; width: 100vw; overflow: hidden; font-family: 'Plus Jakarta Sans', sans-serif; background: var(--bg); color: var(--text); }
        .auth-overlay { position: fixed; inset: 0; background: rgba(11, 14, 20, 0.98); z-index: 999; display: flex; align-items: center; justify-content: center; padding: 20px; }
        .auth-card { background: var(--panel); border: 1px solid var(--border); border-radius: 20px; padding: 32px; width: 100%; max-width: 380px; text-align: center; }
        .auth-input { width: 100%; background: var(--card); border: 1px solid var(--border); padding: 14px; border-radius: 12px; color: #fff; font-size: 15px; margin-bottom: 14px; outline: none; }
        .btn-auth { width: 100%; background: var(--accent); color: #000; font-weight: 700; border: none; padding: 14px; border-radius: 12px; cursor: pointer; font-size: 15px; }
        .workspace { display: flex; width: 100%; height: 100%; }
        .sidebar { width: 360px; border-right: 1px solid var(--border); background: var(--panel); display: flex; flex-direction: column; }
        .sidebar-header { padding: 16px; border-bottom: 1px solid var(--border); font-family: 'Space Grotesk'; color: var(--accent); font-size: 18px; display: flex; justify-content: space-between; }
        .chat-list { flex: 1; overflow-y: auto; }
        .chat-item { padding: 14px 18px; border-bottom: 1px solid var(--border); cursor: pointer; display: flex; gap: 12px; align-items: center; }
        .chat-item:hover { background: #232b3b; }
        .stage { flex: 1; display: flex; flex-direction: column; background: var(--bg); }
        .stage-header { padding: 14px; background: var(--panel); border-bottom: 1px solid var(--border); font-weight: 700; }
        .messages { flex: 1; padding: 16px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
        .bubble { max-width: 80%; padding: 10px 14px; border-radius: 12px; font-size: 14px; }
        .bubble.sent { align-self: flex-end; background: var(--accent); color: #000; font-weight: 600; }
        .bubble.received { align-self: flex-start; background: var(--card); border: 1px solid var(--border); }
        .input-bar { padding: 12px; background: var(--panel); border-top: 1px solid var(--border); display: flex; gap: 8px; }
        .main-input { flex: 1; background: var(--card); border: 1px solid var(--border); padding: 10px 14px; border-radius: 20px; color: #fff; outline: none; font-size: 14px; }
        .btn-send { width: 40px; height: 40px; border-radius: 50%; background: var(--accent); color: #000; border: none; font-weight: 700; cursor: pointer; display: flex; align-items: center; justify-content: center; }
        .modal { position: fixed; inset: 0; background: rgba(0,0,0,0.85); z-index: 9999; display: none; align-items: center; justify-content: center; padding: 20px; }
        .modal-card { background: var(--panel); border: 1px solid var(--border); border-radius: 16px; padding: 20px; width: 100%; max-width: 340px; display: flex; flex-direction: column; gap: 10px; }
    </style>
</head>
<body>

    <div class="auth-overlay" id="auth-overlay">
        <div class="auth-card">
            <h2 style="font-family: 'Space Grotesk'; color: var(--accent); margin-bottom: 6px;">Syncora Terminal</h2>
            <p style="font-size: 12px; color: var(--muted); margin-bottom: 20px;">Enter your phone to start</p>
            <input type="tel" id="my-phone-input" class="auth-input" placeholder="e.g. 03001234567">
            <button class="btn-auth" onclick="forceLogin()">Enter Terminal →</button>
        </div>
    </div>

    <div class="modal" id="send-modal">
        <div class="modal-card">
            <h3 style="color: var(--accent); font-size: 16px;">Send Message</h3>
            <p style="font-size: 12px; color: var(--muted);" id="modal-text-preview"></p>
            <select id="target-lang" style="padding: 10px; background: var(--card); color: #fff; border: 1px solid var(--border); border-radius: 8px;">
                <option value="en">English</option>
                <option value="ur">Urdu</option>
                <option value="ar">Arabic</option>
                <option value="zh-CN">Chinese</option>
            </select>
            <button class="btn-auth" onclick="sendTranslated()">🌐 Translate & Send</button>
            <button onclick="sendOriginal()" style="background: var(--card); color: #fff; border: 1px solid var(--border); padding: 10px; border-radius: 8px; cursor: pointer; font-weight: 600;">✉️ Send Original</button>
            <button onclick="document.getElementById('send-modal').style.display='none'" style="background: transparent; border: none; color: var(--muted); cursor: pointer; font-size: 12px;">Cancel</button>
        </div>
    </div>

    <div class="workspace">
        <aside class="sidebar">
            <div class="sidebar-header">
                <span>SYNCORA</span>
                <span id="my-phone-display" style="font-size: 12px; color: var(--green);"></span>
            </div>
            <div class="chat-list" id="chat-list">
                <div class="chat-item" onclick="selectChat('03111111111')">
                    <div style="width:36px; height:36px; background:#2d3748; border-radius:50%; display:flex; align-items:center; justify-content:center; color:var(--accent); font-weight:700;">11</div>
                    <div>
                        <div style="font-weight:600; font-size:14px;">Test Contact (03111111111)</div>
                        <div style="font-size:11px; color:var(--muted);">Click to open chat</div>
                    </div>
                </div>
            </div>
        </aside>

        <main class="stage">
            <header class="stage-header" id="active-chat-title">Select a chat</header>
            <div class="messages" id="messages-container"></div>
            <footer class="input-bar">
                <input type="text" id="text-input" class="main-input" placeholder="Type message..." onkeydown="if(event.key==='Enter') stageMessage()">
                <button onclick="toggleVoice()" title="Voice Note" style="background:transparent; border:none; color:var(--accent); font-size:20px; cursor:pointer;">🎙️</button>
                <button class="btn-send" onclick="stageMessage()">➤</button>
            </footer>
        </main>
    </div>

    <script>
        let myPhone = localStorage.getItem("syncora_phone") || "";
        let activePartner = "";
        let socket = null;
        let pendingText = "";

        // Safe URL parameters handler to prevent syntax errors
        try {
            const urlParams = new URLSearchParams(window.location.search);
            const chatParam = urlParams.get('chat');
            if (chatParam) {
                activePartner = chatParam;
            }
        } catch(e) {}

        window.onload = () => {
            if (myPhone) {
                document.getElementById("auth-overlay").style.display = "none";
                document.getElementById("my-phone-display").innerText = myPhone;
                initSocket();
                if (activePartner) {
                    selectChat(activePartner);
                }
            }
        };

        function forceLogin() {
            const val = document.getElementById("my-phone-input").value.trim();
            if (!val) { alert("Number enter karein!"); return; }
            myPhone = val;
            localStorage.setItem("syncora_phone", myPhone);
            document.getElementById("auth-overlay").style.display = "none";
            document.getElementById("my-phone-display").innerText = myPhone;
            initSocket();
        }

        function initSocket() {
            if (!myPhone) return;
            const proto = window.location.protocol === "https:" ? "wss://" : "ws://";
            socket = new WebSocket(`${proto}${window.location.host}/ws/${myPhone}`);
            socket.onmessage = (e) => {
                const data = JSON.parse(e.data);
                if (data.action === "new_message" && data.sender === activePartner) {
                    appendBubble(data.content, "received", data.translated);
                }
            };
        }

        function selectChat(partner) {
            activePartner = partner;
            document.getElementById("active-chat-title").innerText = "Chat with " + partner;
            document.getElementById("messages-container").innerHTML = "";
        }

        function stageMessage() {
            const txt = document.getElementById("text-input").value.trim();
            if (!txt || !activePartner) { alert("Pehle contact select karein aur message likhein!"); return; }
            pendingText = txt;
            document.getElementById("modal-text-preview").innerText = `"${txt}"`;
            document.getElementById("send-modal").style.display = "flex";
        }

        async function sendTranslated() {
            document.getElementById("send-modal").style.display = "none";
            const lang = document.getElementById("target-lang").value;
            let translated = pendingText;
            try {
                const res = await fetch("/translate", {
                    method: "POST", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ text: pendingText, target_lang: lang })
                });
                const data = await res.json();
                translated = data.translated_text || pendingText;
            } catch(e) {}
            dispatchMsg(pendingText, translated, "text");
        }

        function sendOriginal() {
            document.getElementById("send-modal").style.display = "none";
            dispatchMsg(pendingText, "", "text");
        }

        function dispatchMsg(content, translated, type) {
            appendBubble(content, "sent", translated);
            document.getElementById("text-input").value = "";
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({
                    action: "chat_message",
                    receiver: activePartner,
                    content: content,
                    translated: translated,
                    msg_type: type
                }));
            }
        }

        function appendBubble(text, dir, translated) {
            const box = document.getElementById("messages-container");
            const div = document.createElement("div");
            div.className = `bubble ${dir}`;
            let html = `<div>${text}</div>`;
            if (translated && translated.trim()) {
                html += `<div style="font-size:11px; margin-top:4px; padding-top:4px; border-top:1px dashed rgba(0,0,0,0.2); font-weight:700;">Translation: ${translated}</div>`;
            }
            div.innerHTML = html;
            box.appendChild(div);
            box.scrollTop = box.scrollHeight;
        }

        async function toggleVoice() {
            if (!activePartner) { alert("Pehle contact select karein!"); return; }
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                const recorder = new MediaRecorder(stream);
                let chunks = [];
                recorder.ondataavailable = e => chunks.push(e.data);
                recorder.onstop = async () => {
                    const blob = new Blob(chunks, { type: 'audio/webm' });
                    const form = new FormData();
                    form.append("file", blob, "voice.webm");
                    const res = await fetch("/api/upload", { method: "POST", body: form });
                    const data = await res.json();
                    dispatchMsg(data.url, "", "voice");
                };
                recorder.start();
                alert("Recording started... Click OK to stop & send.");
                recorder.stop();
                stream.getTracks().forEach(t => t.stop());
            } catch(e) {
                alert("Mic error: " + e.message);
            }
        }
    </script>
</body>
</html>"""

@app.post("/translate")
async def translate_endpoint(req: TranslationRequest):
    return {"status": "success", "translated_text": translate_text_engine(req.text, req.target_lang)}

@app.post("/api/auth/login")
async def api_login(req: LoginRequest):
    return {"status": "success", "phone": req.phone}

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    path = os.path.join("uploads", file.filename or "voice.webm")
    with open(path, "wb") as b:
        shutil.copyfileobj(file.file, b)
    return {"status": "success", "url": f"/uploads/{file.filename}"}

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await websocket.accept()
    active_connections[client_id] = websocket
    try:
        while True:
            data = json.loads(await websocket.receive_text())
            if data.get("action") == "chat_message":
                recv = data.get("receiver")
                if recv in active_connections:
                    await active_connections[recv].send_text(json.dumps({
                        "action": "new_message",
                        "sender": client_id,
                        "content": data.get("content"),
                        "translated": data.get("translated"),
                        "msg_type": data.get("msg_type")
                    }))
    except WebSocketDisconnect:
        active_connections.pop(client_id, None)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
