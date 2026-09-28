import os
import shutil
import json
import urllib.request
import urllib.parse
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Syncora Terminal - Full Live Build")

# Directories setup
os.makedirs("uploads", exist_ok=True)
os.makedirs("static", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

active_connections = {}
message_history = {}

class TranslationRequest(BaseModel):
    text: str
    target_lang: str = "en"

# Translation Engine
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
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Syncora Terminal</title>
    <style>
        :root {
            --bg: #0b0e14; --panel: #121721; --card: #1a202c; --border: #2d3748;
            --accent: #f59e0b; --text: #f7fafc; --muted: #718096; --green: #10b981; --red: #ef4444;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        html, body { height: 100vh; width: 100vw; overflow: hidden; font-family: sans-serif; background: var(--bg); color: var(--text); }
        .auth-overlay { position: fixed; inset: 0; background: #0b0e14; z-index: 999; display: flex; align-items: center; justify-content: center; padding: 20px; }
        .auth-card { background: var(--panel); border: 1px solid var(--border); border-radius: 20px; padding: 32px; width: 100%; max-width: 380px; text-align: center; }
        .auth-input { width: 100%; background: var(--card); border: 1px solid var(--border); padding: 14px; border-radius: 12px; color: #fff; font-size: 15px; margin-bottom: 14px; outline: none; }
        .btn-auth { width: 100%; background: var(--accent); color: #000; font-weight: 700; border: none; padding: 14px; border-radius: 12px; cursor: pointer; font-size: 15px; }
        .workspace { display: flex; width: 100%; height: 100%; }
        .sidebar { width: 360px; border-right: 1px solid var(--border); background: var(--panel); display: flex; flex-direction: column; }
        .sidebar-header { padding: 16px; border-bottom: 1px solid var(--border); color: var(--accent); font-size: 18px; font-weight: bold; display: flex; justify-content: space-between; align-items: center; }
        .search-box-container { padding: 12px 16px; border-bottom: 1px solid var(--border); }
        .search-input { width: 100%; background: var(--card); border: 1px solid var(--border); padding: 10px 14px; border-radius: 8px; color: #fff; outline: none; font-size: 13px; }
        .chat-list { flex: 1; overflow-y: auto; }
        .chat-item { padding: 14px 18px; border-bottom: 1px solid var(--border); cursor: pointer; display: flex; gap: 12px; align-items: center; }
        .chat-item:hover { background: #232b3b; }
        .sidebar-footer { padding: 12px; border-top: 1px solid var(--border); display: flex; justify-content: space-around; background: var(--panel); }
        .nav-tab { background: transparent; border: none; color: var(--muted); cursor: pointer; font-size: 12px; display: flex; flex-direction: column; align-items: center; gap: 4px; font-weight: 600; }
        .nav-tab.active { color: var(--accent); }
        .stage { flex: 1; display: flex; flex-direction: column; background: var(--bg); position: relative; }
        .stage-header { padding: 12px 16px; background: var(--panel); border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
        .stage-header-left { display: flex; align-items: center; gap: 12px; }
        .stage-header-actions { display: flex; gap: 10px; align-items: center; }
        .header-btn { background: var(--card); border: 1px solid var(--border); color: var(--accent); width: 36px; height: 36px; border-radius: 50%; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 15px; }
        .header-btn:hover { background: #232b3b; }
        .messages { flex: 1; padding: 16px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
        .bubble { max-width: 80%; padding: 10px 14px; border-radius: 12px; font-size: 14px; word-break: break-word; }
        .bubble.sent { align-self: flex-end; background: var(--accent); color: #000; font-weight: 600; }
        .bubble.received { align-self: flex-start; background: var(--card); border: 1px solid var(--border); }
        .input-bar { padding: 12px; background: var(--panel); border-top: 1px solid var(--border); display: flex; gap: 8px; align-items: center; position: relative; }
        .main-input { flex: 1; background: var(--card); border: 1px solid var(--border); padding: 10px 14px; border-radius: 20px; color: #fff; outline: none; font-size: 14px; }
        .btn-action { width: 40px; height: 40px; border-radius: 50%; background: var(--card); color: var(--accent); border: 1px solid var(--border); font-weight: 700; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
        .btn-send { width: 40px; height: 40px; border-radius: 50%; background: var(--accent); color: #000; border: none; font-weight: 700; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
        
        .attach-menu { position: absolute; bottom: 65px; left: 12px; background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 8px; display: none; flex-direction: column; gap: 6px; z-index: 100; box-shadow: 0 4px 12px rgba(0,0,0,0.5); }
        .attach-item { background: var(--card); border: none; color: #fff; padding: 8px 14px; border-radius: 8px; cursor: pointer; text-align: left; font-size: 13px; display: flex; gap: 8px; align-items: center; }
        .attach-item:hover { background: #232b3b; color: var(--accent); }

        .modal { position: fixed; inset: 0; background: rgba(0,0,0,0.85); z-index: 9999; display: none; align-items: center; justify-content: center; padding: 20px; }
        .modal-card { background: var(--panel); border: 1px solid var(--border); border-radius: 16px; padding: 20px; width: 100%; max-width: 340px; display: flex; flex-direction: column; gap: 10px; }
    </style>
</head>
<body>

    <div class="auth-overlay" id="auth-overlay">
        <div class="auth-card">
            <h2 style="color: var(--accent); margin-bottom: 6px;">Syncora Terminal</h2>
            <p style="font-size: 12px; color: var(--muted); margin-bottom: 20px;">Enter your phone to connect</p>
            <input type="tel" id="my-phone-input" class="auth-input" placeholder="e.g. 03001234567">
            <button class="btn-auth" onclick="forceLogin()">Enter Terminal →</button>
        </div>
    </div>

    <!-- Text & Translation Modal -->
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

    <!-- Hidden File Inputs -->
    <input type="file" id="media-upload-input" accept="image/*,video/*" style="display:none" onchange="uploadFile(this, 'media')">
    <input type="file" id="doc-upload-input" style="display:none" onchange="uploadFile(this, 'document')">

    <div class="workspace">
        <aside class="sidebar">
            <div class="sidebar-header">
                <span>SYNCORA</span>
                <span id="my-phone-display" style="font-size: 12px; color: var(--green);"></span>
            </div>
            <div class="search-box-container">
                <input type="text" class="search-input" placeholder="Search chats..." id="search-chats">
            </div>
            <div class="chat-list" id="chat-list">
                <div class="chat-item" onclick="selectChat('03111111111')">
                    <div style="width:36px; height:36px; background:#2d3748; border-radius:50%; display:flex; align-items:center; justify-content:center; color:var(--accent); font-weight:700;">11</div>
                    <div>
                        <div style="font-weight:600; font-size:14px;">Test Contact (03111111111)</div>
                        <div style="font-size:11px; color:var(--green);">Direct line active</div>
                    </div>
                </div>
            </div>
            <footer class="sidebar-footer">
                <button class="nav-tab active" onclick="switchTab('chats')">💬 Chats</button>
                <button class="nav-tab" onclick="switchTab('contacts')">👥 Contacts</button>
            </footer>
        </aside>

        <main class="stage">
            <header class="stage-header" id="stage-header-area">
                <div class="stage-header-left">
                    <div id="header-avatar" style="width:36px; height:36px; background:#2d3748; border-radius:50%; display:flex; align-items:center; justify-content:center; color:var(--accent); font-weight:700;">--</div>
                    <div>
                        <div id="active-chat-title" style="font-weight:700; font-size:14px;">Select a chat</div>
                        <div id="active-chat-status" style="font-size:11px; color:var(--muted);">Offline</div>
                    </div>
                </div>
                <div class="stage-header-actions">
                    <button class="header-btn" onclick="startAudioCall()" title="Audio Call">📞</button>
                    <button class="header-btn" onclick="startVideoCall()" title="Video Call">📹</button>
                    <button class="header-btn" onclick="openTranslationSettings()" title="Translation Options">🌐</button>
                </div>
            </header>

            <div class="messages" id="messages-container"></div>

            <footer class="input-bar">
                <div class="attach-menu" id="attach-menu">
                    <button class="attach-item" onclick="triggerMediaUpload()">📷 Photos & Videos</button>
                    <button class="attach-item" onclick="triggerDocUpload()">📄 Document</button>
                    <button class="attach-item" onclick="sendLocation()">📍 Location</button>
                </div>

                <button class="btn-action" onclick="toggleAttachMenu()" title="Attach">📎</button>
                <input type="text" id="text-input" class="main-input" placeholder="Message..." onkeydown="if(event.key==='Enter') stageMessage()">
                <button class="btn-action" onclick="toggleVoiceRecording()" title="Voice Note">🎙️</button>
                <button class="btn-send" onclick="stageMessage()">➤</button>
            </footer>
        </main>
    </div>

    <script>
        let myPhone = localStorage.getItem("syncora_phone") || "";
        let activePartner = "";
        let socket = null;
        let pendingText = "";
        
        let mediaRecorder = null;
        let audioChunks = [];
        let isRecording = false;

        window.onload = function() {
            if (myPhone) {
                document.getElementById("auth-overlay").style.display = "none";
                document.getElementById("my-phone-display").innerText = myPhone;
                initSocket();
                selectChat('03111111111');
            }
        };

        function forceLogin() {
            const val = document.getElementById("my-phone-input").value;
            if (!val) { alert("Phone number enter karein!"); return; }
            myPhone = val.trim();
            localStorage.setItem("syncora_phone", myPhone);
            document.getElementById("auth-overlay").style.display = "none";
            document.getElementById("my-phone-display").innerText = myPhone;
            initSocket();
            selectChat('03111111111');
        }

        function initSocket() {
            if (!myPhone) return;
            const proto = window.location.protocol === "https:" ? "wss://" : "ws://";
            socket = new WebSocket(proto + window.location.host + "/ws/" + myPhone);
            socket.onmessage = function(e) {
                const data = JSON.parse(e.data);
                if (data.action === "new_message" && data.sender === activePartner) {
                    appendBubble(data.content, "received", data.translated, data.msg_type);
                }
            };
        }

        function selectChat(partner) {
            activePartner = partner;
            document.getElementById("active-chat-title").innerText = partner;
            document.getElementById("active-chat-status").innerText = "Online";
            document.getElementById("header-avatar").innerText = partner.slice(-2);
            document.getElementById("messages-container").innerHTML = "";
        }

        function switchTab(tab) {
            document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));
            event.currentTarget.classList.add('active');
            if(tab === 'contacts') {
                alert("Contacts view activated.");
            }
        }

        function toggleAttachMenu() {
            const menu = document.getElementById("attach-menu");
            menu.style.display = menu.style.display === "flex" ? "none" : "flex";
        }

        function triggerMediaUpload() {
            document.getElementById("attach-menu").style.display = "none";
            document.getElementById("media-upload-input").click();
        }

        function triggerDocUpload() {
            document.getElementById("attach-menu").style.display = "none";
            document.getElementById("doc-upload-input").click();
        }

        async function uploadFile(input, fileType) {
            if(!activePartner) { alert("Pehle contact select karein!"); return; }
            if(input.files && input.files[0]) {
                const form = new FormData();
                form.append("file", input.files[0]);
                try {
                    const res = await fetch("/api/upload", { method: "POST", body: form });
                    const data = await res.json();
                    if(data.url) {
                        dispatchMsg(data.url, "", fileType);
                    }
                } catch(e) {
                    alert("Upload failed");
                }
            }
        }

        function sendLocation() {
            document.getElementById("attach-menu").style.display = "none";
            if(!activePartner) { alert("Pehle contact select karein!"); return; }
            if (navigator.geolocation) {
                navigator.geolocation.getCurrentPosition(position => {
                    const lat = position.coords.latitude;
                    const lon = position.coords.longitude;
                    const mapUrl = `https://maps.google.com/?q=${lat},${lon}`;
                    dispatchMsg(mapUrl, "Shared Location", "location");
                }, () => {
                    alert("Unable to retrieve your location");
                });
            } else {
                alert("Geolocation is not supported");
            }
        }

        function startAudioCall() {
            if(!activePartner) { alert("Pehle contact select karein!"); return; }
            alert("Audio calling initiated with " + activePartner);
        }

        function startVideoCall() {
            if(!activePartner) { alert("Pehle contact select karein!"); return; }
            alert("Video calling initiated with " + activePartner);
        }

        function openTranslationSettings() {
            alert("Translation options active via send prompt.");
        }

        function stageMessage() {
            const txt = document.getElementById("text-input").value;
            if (!txt || !activePartner) { alert("Pehle contact select karein aur message likhein!"); return; }
            pendingText = txt.trim();
            document.getElementById("modal-text-preview").innerText = '"' + pendingText + '"';
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

        async function toggleVoiceRecording() {
            if (!activePartner) { alert("Pehle contact select karein!"); return; }
            if (!isRecording) {
                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    mediaRecorder = new MediaRecorder(stream);
                    audioChunks = [];
                    mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
                    mediaRecorder.onstop = async () => {
                        const blob = new Blob(audioChunks, { type: 'audio/webm' });
                        const form = new FormData();
                        form.append("file", blob, "voice_" + Date.now() + ".webm");
                        try {
                            const res = await fetch("/api/upload", { method: "POST", body: form });
                            const data = await res.json();
                            if (data.url) {
                                dispatchMsg(data.url, "", "voice");
                            }
                        } catch(err) {
                            alert("Audio upload failed");
                        }
                        stream.getTracks().forEach(t => t.stop());
                    };
                    mediaRecorder.start();
                    isRecording = true;
                    event.target.style.background = "var(--red)";
                } catch(e) {
                    alert("Microphone permission denied.");
                }
            } else {
                mediaRecorder.stop();
                isRecording = false;
                event.target.style.background = "var(--card)";
            }
        }

        function dispatchMsg(content, translated, type) {
            appendBubble(content, "sent", translated, type);
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

        function appendBubble(text, dir, translated, type) {
            const box = document.getElementById("messages-container");
            const div = document.createElement("div");
            div.className = "bubble " + dir;
            
            let html = "";
            if (type === "voice") {
                const aid = "audio_" + Math.random().toString(36).substring(2, 9);
                html = `
                    <div style="display:flex; align-items:center; gap:10px;">
                        <audio id="${aid}" src="${text}"></audio>
                        <button onclick="document.getElementById('${aid}').play()" style="background:#000; color:var(--accent); border:none; width:34px; height:34px; border-radius:50%; cursor:pointer;">▶</button>
                        <span style="font-size:12px; font-weight:600;">Voice Note</span>
                    </div>
                `;
            } else if (type === "media") {
                html = `<img src="${text}" style="max-width:200px; border-radius:8px;" /><div style="font-size:11px; margin-top:4px;">Photo / Video</div>`;
            } else if (type === "document") {
                html = `<a href="${text}" target="_blank" style="color:var(--accent); text-decoration:underline; font-weight:600;">📄 Download Document</a>`;
            } else if (type === "location") {
                html = `<a href="${text}" target="_blank" style="color:var(--accent); text-decoration:underline; font-weight:600;">📍 View Shared Location</a>`;
            } else {
                html = "<div>" + text + "</div>";
                if (translated && translated.trim()) {
                    html += "<div style='font-size:11px; margin-top:4px; padding-top:4px; border-top:1px dashed rgba(0,0,0,0.2); font-weight:700;'>Translation: " + translated + "</div>";
                }
            }
            div.innerHTML = html;
            box.appendChild(div);
            box.scrollTop = box.scrollHeight;
        }
    </script>
</body>
</html>"""

@app.post("/translate")
async def translate_endpoint(req: TranslationRequest):
    return {"status": "success", "translated_text": translate_text_engine(req.text, req.target_lang)}

@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    path = os.path.join("uploads", file.filename or "file.webm")
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
                        "msg_type": data.get("msg_type", "text")
                    }))
    except WebSocketDisconnect:
        active_connections.pop(client_id, None)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
