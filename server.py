import os
import shutil
import json
import urllib.request
import urllib.parse
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Syncora Terminal - Stable Server")

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

# Stable Translation Engine
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
        with urllib.request.urlopen(req, timeout=6) as response:
            res_body = response.read().decode('utf-8')
            res_data = json.loads(res_body)
            if res_data and isinstance(res_data, list) and len(res_data) > 0:
                translated_sentences = [s[0] for s in res_data[0] if s and s[0]]
                translated_text = "".join(translated_sentences).strip()
                if translated_text:
                    return translated_text
    except Exception as e:
        print(f"[Translation Error]: {e}")
        
    return clean

# Root Route: Serves the frontend directly without file dependency
@app.get("/", response_class=HTMLResponse)
def read_root():
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>Syncora Terminal</title>
    <link rel="icon" href="data:,">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&family=Space+Grotesk:wght@500;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-obsidian: #0b0e14; --surface-panel: #121721; --surface-card: #1a202c; --surface-hover: #232b3b;
            --border-graphite: #2d3748; --border-subtle: rgba(255, 255, 255, 0.05); --accent-amber: #f59e0b;
            --accent-amber-dim: rgba(245, 158, 11, 0.12); --accent-amber-glow: rgba(245, 158, 11, 0.25);
            --danger-red: #ef4444; --danger-red-dim: rgba(239, 68, 68, 0.15); --text-primary: #f7fafc;
            --text-secondary: #a0aec0; --text-muted: #718096; --online-green: #10b981; --wa-green: #25d366;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
        html, body {
            height: 100%; height: 100dvh; width: 100vw; overflow: hidden;
            font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
            background-color: var(--bg-obsidian); color: var(--text-primary);
        }
        .auth-overlay {
            position: fixed; inset: 0; background: rgba(11, 14, 20, 0.96); backdrop-filter: blur(12px);
            z-index: 999; display: flex; align-items: center; justify-content: center; padding: 20px;
        }
        .auth-card {
            background: var(--surface-panel); border: 1px solid var(--border-graphite); border-radius: 24px;
            padding: 36px 28px; width: 100%; max-width: 400px; text-align: center; box-shadow: 0 10px 40px rgba(0,0,0,0.8);
        }
        .auth-badge {
            width: 60px; height: 60px; border-radius: 18px; background: var(--accent-amber-dim); border: 2px solid var(--accent-amber);
            display: flex; align-items: center; justify-content: center; font-size: 24px; color: var(--accent-amber);
            margin: 0 auto 16px auto; font-family: 'Space Grotesk', sans-serif; box-shadow: 0 0 25px var(--accent-amber-glow);
        }
        .auth-title { font-family: 'Space Grotesk', sans-serif; font-size: 22px; color: var(--text-primary); margin-bottom: 6px; }
        .auth-desc { font-size: 13px; color: var(--text-muted); margin-bottom: 20px; line-height: 1.4; }
        .auth-input {
            width: 100%; background: var(--surface-card); border: 1px solid var(--border-graphite);
            padding: 14px 16px; border-radius: 12px; color: #fff; font-size: 15px; margin-bottom: 14px; outline: none;
        }
        .auth-input:focus { border-color: var(--accent-amber); }
        .btn-auth {
            width: 100%; background: var(--accent-amber); color: #000; font-weight: 700; border: none;
            padding: 14px; border-radius: 12px; cursor: pointer; font-size: 14px; box-shadow: 0 4px 20px var(--accent-amber-glow);
        }
        .workspace { display: flex; width: 100%; height: 100%; position: relative; overflow: hidden; }
        .sidebar-panel {
            width: 380px; border-right: 1px solid var(--border-graphite); background: var(--surface-panel);
            display: flex; flex-direction: column; flex-shrink: 0; position: relative; height: 100%;
        }
        .sidebar-header {
            padding: 14px 16px; border-bottom: 1px solid var(--border-subtle); display: flex; align-items: center; justify-content: space-between;
        }
        .app-brand { font-family: 'Space Grotesk', sans-serif; font-size: 18px; font-weight: 700; color: var(--accent-amber); }
        .sidebar-search { padding: 10px 14px; border-bottom: 1px solid var(--border-subtle); display: flex; }
        .search-input {
            flex: 1; background: var(--surface-card); border: 1px solid var(--border-graphite); padding: 10px 14px;
            border-radius: 12px; color: #fff; font-size: 13px; outline: none;
        }
        .chat-list { flex: 1; overflow-y: auto; padding-bottom: 60px; }
        .chat-item {
            padding: 14px 18px; border-bottom: 1px solid var(--border-subtle); display: flex; align-items: center; gap: 12px; cursor: pointer;
        }
        .chat-item:hover, .chat-item.active { background: var(--surface-hover); }
        .chat-avatar {
            width: 44px; height: 44px; border-radius: 50%; background: #1f2937; border: 1px solid var(--border-graphite);
            display: flex; align-items: center; justify-content: center; font-weight: 700; color: var(--accent-amber); flex-shrink: 0;
        }
        .chat-info { flex: 1; overflow: hidden; }
        .chat-title { font-size: 15px; font-weight: 600; white-space: nowrap; text-overflow: ellipsis; overflow: hidden; }
        .chat-subtitle { font-size: 12px; color: var(--text-muted); margin-top: 3px; }
        .fab-btn {
            position: absolute; bottom: 70px; right: 20px; width: 54px; height: 54px; border-radius: 50%;
            background: var(--accent-amber); color: #000; border: none; font-size: 22px; display: flex;
            align-items: center; justify-content: center; cursor: pointer; box-shadow: 0 4px 20px var(--accent-amber-glow); z-index: 40;
        }
        .stage-panel { flex: 1; display: flex; flex-direction: column; background: var(--bg-obsidian); position: relative; height: 100%; overflow: hidden; }
        .stage-header {
            padding: 8px 12px; background: var(--surface-panel); border-bottom: 1px solid var(--border-graphite);
            display: flex; align-items: center; justify-content: space-between; flex-shrink: 0; min-height: 60px;
        }
        .messages-container { flex: 1; padding: 14px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
        .bubble { max-width: 82%; padding: 10px 14px; border-radius: 14px; font-size: 13px; line-height: 1.4; word-break: break-word; }
        .bubble.sent { align-self: flex-end; background: var(--accent-amber); color: #000; font-weight: 500; border-bottom-right-radius: 2px; }
        .bubble.received { align-self: flex-start; background: var(--surface-card); color: var(--text-primary); border: 1px solid var(--border-graphite); border-bottom-left-radius: 2px; }
        .bubble-translation { font-size: 12px; margin-top: 6px; padding-top: 6px; font-weight: 700; border-top: 1px dashed var(--border-graphite); color: var(--online-green); }
        .stage-input-bar { padding: 8px 12px; background: var(--surface-panel); border-top: 1px solid var(--border-graphite); display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
        .input-shell { flex: 1; background: var(--surface-card); border: 1px solid var(--border-graphite); border-radius: 22px; display: flex; align-items: center; padding: 2px 8px; gap: 6px; }
        .main-text-input { flex: 1; background: transparent; border: none; outline: none; color: var(--text-primary); font-size: 14px; padding: 8px; }
        .btn-send-permanent { width: 40px; height: 40px; border-radius: 50%; background: var(--accent-amber); color: #000; border: none; font-size: 16px; cursor: pointer; display: flex; align-items: center; justify-content: center; }
        .icon-btn { background: transparent; border: none; color: var(--text-secondary); font-size: 18px; cursor: pointer; padding: 4px; }
        .contacts-overlay, .send-modal-backdrop {
            position: fixed; inset: 0; background: rgba(0,0,0,0.85); backdrop-filter: blur(10px); z-index: 9999; display: none; align-items: center; justify-content: center; padding: 20px;
        }
        .contacts-card, .send-modal-card {
            background: var(--surface-panel); border: 1px solid var(--border-graphite); border-radius: 20px; width: 100%; max-width: 380px; padding: 22px; display: flex; flex-direction: column; gap: 12px; text-align: center;
        }
        .modal-btn-choice {
            padding: 12px; border-radius: 12px; border: 1px solid var(--border-graphite); font-size: 13px; font-weight: 700; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px; background: var(--surface-card); color: #fff;
        }
        .btn-choice-trans { background: var(--accent-amber); color: #000; border: none; }
        .lang-dropdown, .auth-input {
            width: 100%; background: var(--surface-card); border: 1px solid var(--border-graphite); padding: 10px; border-radius: 10px; color: #fff; font-size: 13px; outline: none;
        }
        @media (max-width: 768px) {
            .sidebar-panel { width: 100%; height: 100dvh; display: flex; }
            .stage-panel { display: none; width: 100%; height: 100dvh; }
            body.in-chat .sidebar-panel { display: none !important; }
            body.in-chat .stage-panel { display: flex !important; flex-direction: column; height: 100dvh; }
        }
    </style>
</head>
<body>
    <div class="auth-overlay" id="auth-overlay">
        <div class="auth-card">
            <div class="auth-badge">IA</div>
            <h2 class="auth-title">Welcome to Syncora</h2>
            <p class="auth-desc">Chat, Call & Live AI Translation Terminal</p>
            <input type="tel" id="my-phone-input" class="auth-input" placeholder="Mobile Number (e.g. 03001234567)" onkeydown="if(event.key==='Enter'){ executeDirectLogin(); }">
            <button class="btn-auth" onclick="executeDirectLogin()">Enter Terminal →</button>
        </div>
    </div>

    <div class="contacts-overlay" id="contacts-modal">
        <div class="contacts-card">
            <h3 style="color: var(--accent-amber);">Start New Conversation</h3>
            <input type="tel" id="manual-contact-input" class="auth-input" placeholder="Enter Mobile Number (0301...)">
            <button class="btn-auth" onclick="openManualChat()">Add & Open Chat</button>
            <button onclick="document.getElementById('contacts-modal').style.display='none'" style="background:transparent; border:none; color:var(--text-muted); cursor:pointer;">Close</button>
        </div>
    </div>

    <div class="workspace">
        <aside class="sidebar-panel">
            <div class="sidebar-header">
                <span class="app-brand">SYNCORA</span>
                <span style="font-size: 12px; color: var(--online-green);" id="my-status-label">● Online</span>
            </div>
            <div class="sidebar-search">
                <input type="text" id="chat-search-input" class="search-input" placeholder="Search chats..." oninput="filterChatList(this.value)">
            </div>
            <div class="chat-list" id="chat-list"></div>
            <button class="fab-btn" onclick="document.getElementById('contacts-modal').style.display='flex'">💬</button>
        </aside>

        <main class="stage-panel" id="stage-panel">
            <header class="stage-header">
                <div style="display: flex; align-items: center; gap: 6px;">
                    <button class="icon-btn" onclick="document.body.classList.remove('in-chat')">←</button>
                    <div class="chat-avatar" id="active-avatar">--</div>
                    <div>
                        <div style="font-size: 13px; font-weight: 700;" id="active-partner-label">Select Chat</div>
                        <div style="font-size: 10px; color: var(--text-muted);" id="active-partner-status">Offline</div>
                    </div>
                </div>
            </header>
            <div class="messages-container" id="messages-container"></div>
            <footer class="stage-input-bar">
                <div class="input-shell">
                    <input type="text" id="text-input" class="main-text-input" placeholder="Message..." onkeydown="if(event.key==='Enter'){ event.preventDefault(); stageMessageForDispatch(); }">
                </div>
                <button class="btn-send-permanent" onclick="stageMessageForDispatch()">➤</button>
            </footer>
        </main>
    </div>

    <div class="send-modal-backdrop" id="send-modal">
        <div class="send-modal-card">
            <h3 style="color: var(--accent-amber);">Confirm Dispatch</h3>
            <p style="font-size: 12px; color: var(--text-muted);" id="send-modal-preview"></p>
            <select class="lang-dropdown" id="modal-target-lang">
                <option value="en" selected>English (US)</option>
                <option value="ur">Urdu (اردو)</option>
                <option value="ar">Arabic (العربية)</option>
            </select>
            <button class="modal-btn-choice btn-choice-trans" onclick="confirmDispatchTranslation()">🌐 Translate & Send</button>
            <button class="modal-btn-choice" onclick="confirmDispatchOriginal()">✉️ Send Without Translation</button>
            <button onclick="document.getElementById('send-modal').style.display='none'" style="background:transparent; border:none; color:var(--text-muted); cursor:pointer;">Cancel</button>
        </div>
    </div>

    <script>
        let myPhone = localStorage.getItem("syncora_user_phone") || "";
        let activePartner = localStorage.getItem("syncora_active_partner") || "";
        let allChatsCache = JSON.parse(localStorage.getItem("syncora_cached_chats") || "[]");
        let socket = null;
        let pendingPayload = null;

        window.onload = () => {
            renderChatList();
            if (myPhone) {
                document.getElementById("auth-overlay").style.display = "none";
                document.getElementById("my-status-label").innerText = `● ${myPhone}`;
                initSocket();
                if (activePartner) selectChat(activePartner);
            }
        };

        function executeDirectLogin() {
            const input = document.getElementById("my-phone-input").value.trim();
            if (!input) return;
            myPhone = input;
            localStorage.setItem("syncora_user_phone", myPhone);
            document.getElementById("auth-overlay").style.display = "none";
            document.getElementById("my-status-label").innerText = `● ${myPhone}`;
            initSocket();
        }

        function initSocket() {
            if (!myPhone) return;
            const proto = window.location.protocol === "https:" ? "wss://" : "ws://";
            socket = new WebSocket(`${proto}${window.location.host}/ws/${myPhone}`);
            socket.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.action === "new_message" && data.sender === activePartner) {
                    appendBubble(data.content, "received", data.translated, "now");
                }
            };
        }

        function openManualChat() {
            const num = document.getElementById("manual-contact-input").value.trim();
            if (!num) return;
            document.getElementById("contacts-modal").style.display = "none";
            if (!allChatsCache.includes(num)) {
                allChatsCache.unshift(num);
                localStorage.setItem("syncora_cached_chats", JSON.stringify(allChatsCache));
            }
            renderChatList();
            selectChat(num);
        }

        function renderChatList() {
            const list = document.getElementById("chat-list");
            list.innerHTML = "";
            allChatsCache.forEach(p => {
                const item = document.createElement("div");
                item.className = `chat-item ${p === activePartner ? 'active' : ''}`;
                item.onclick = () => selectChat(p);
                item.innerHTML = `<div class="chat-avatar">${p.slice(-2)}</div><div class="chat-info"><div class="chat-title">${p}</div><div class="chat-subtitle">Active Line</div></div>`;
                list.appendChild(item);
            });
        }

        function selectChat(p) {
            activePartner = p;
            localStorage.setItem("syncora_active_partner", activePartner);
            document.body.classList.add("in-chat");
            document.getElementById("active-partner-label").innerText = p;
            document.getElementById("active-avatar").innerText = p.slice(-2);
            document.getElementById("messages-container").innerHTML = "";
        }

        function stageMessageForDispatch() {
            const text = document.getElementById("text-input").value.trim();
            if (!text || !activePartner) return;
            pendingPayload = { content: text };
            document.getElementById("send-modal-preview").innerText = `"${text}"`;
            document.getElementById("send-modal").style.display = "flex";
        }

        function confirmDispatchOriginal() {
            if (!pendingPayload) return;
            executeDispatch(pendingPayload.content, "");
            document.getElementById("send-modal").style.display = "none";
        }

        async function confirmDispatchTranslation() {
            if (!pendingPayload) return;
            const targetLang = document.getElementById("modal-target-lang").value;
            let translatedText = pendingPayload.content;
            try {
                const res = await fetch("/translate", {
                    method: "POST", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ text: pendingPayload.content, target_lang: targetLang })
                });
                const data = await res.json();
                translatedText = data.translated_text || pendingPayload.content;
            } catch(e){}
            executeDispatch(pendingPayload.content, translatedText);
            document.getElementById("send-modal").style.display = "none";
        }

        function executeDispatch(content, translated) {
            appendBubble(content, "sent", translated, "now");
            document.getElementById("text-input").value = "";
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ action: "chat_message", receiver: activePartner, content: content, translated: translated }));
            }
        }

        function appendBubble(content, dir, translated, time) {
            const box = document.getElementById("messages-container");
            const bubble = document.createElement("div");
            bubble.className = `bubble ${dir}`;
            let body = `<div>${content}</div>`;
            if (translated && translated.trim() !== "") {
                body += `<div class="bubble-translation">Translation: ${translated}</div>`;
            }
            bubble.innerHTML = body + `<div style="font-size:9px; opacity:0.6; text-align:right; margin-top:2px;">${time}</div>`;
            box.appendChild(bubble);
            box.scrollTop = box.scrollHeight;
        }
    </script>
</body>
</html>"""

# Translation Endpoint
@app.post("/translate")
async def translate_endpoint(req: TranslationRequest):
    try:
        translated = translate_text_engine(req.text, req.target_lang)
        return {
            "status": "success",
            "original": req.text,
            "target_lang": req.target_lang,
            "translated_text": translated
        }
    except Exception as e:
        raise HTTPException(status_status=500, detail=str(e))

# WebSocket Endpoint
@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await websocket.accept()
    active_connections[client_id] = websocket
    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            receiver = data.get("receiver")
            if data.get("action") == "chat_message":
                msg_record = {
                    "sender": client_id,
                    "content": data.get("content"),
                    "translated": data.get("translated"),
                    "time": "now"
                }
                if receiver in active_connections:
                    await active_connections[receiver].send_text(json.dumps({
                        "action": "new_message",
                        **msg_record
                    }))
    except WebSocketDisconnect:
        if client_id in active_connections:
            del active_connections[client_id]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
