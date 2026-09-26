import os
import shutil
import json
import urllib.request
import urllib.parse
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, File, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Syncora Terminal - Complete Stable Server")

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

class ProfileRequest(BaseModel):
    phone: str
    display_name: str = ""
    about_status: str = ""
    avatar_url: str = ""

# Updated Stable Translation Engine with Force Language Mapping
def translate_text_engine(text: str, target_lang: str) -> str:
    clean = text.strip()
    if not clean:
        return ""
    
    t_lang = str(target_lang).strip().lower()
    if not t_lang:
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

# Root Route: Serves the Complete Frontend
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
            --bg-obsidian: #0b0e14;
            --surface-panel: #121721;
            --surface-card: #1a202c;
            --surface-hover: #232b3b;
            --border-graphite: #2d3748;
            --border-subtle: rgba(255, 255, 255, 0.05);
            --accent-amber: #f59e0b;
            --accent-amber-dim: rgba(245, 158, 11, 0.12);
            --accent-amber-glow: rgba(245, 158, 11, 0.25);
            --danger-red: #ef4444;
            --danger-red-dim: rgba(239, 68, 68, 0.15);
            --text-primary: #f7fafc;
            --text-secondary: #a0aec0;
            --text-muted: #718096;
            --online-green: #10b981;
            --wa-green: #25d366;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }

        html, body {
            height: 100%; height: 100dvh; width: 100vw; overflow: hidden;
            font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
            background-color: var(--bg-obsidian); color: var(--text-primary);
        }

        .auth-overlay {
            position: fixed; inset: 0; background: rgba(11, 14, 20, 0.96);
            backdrop-filter: blur(12px); z-index: 999; display: flex;
            align-items: center; justify-content: center; padding: 20px;
        }
        .auth-card {
            background: var(--surface-panel); border: 1px solid var(--border-graphite);
            border-radius: 24px; padding: 36px 28px; width: 100%; max-width: 400px; text-align: center;
            box-shadow: 0 10px 40px rgba(0,0,0,0.8);
        }
        .auth-badge {
            width: 60px; height: 60px; border-radius: 18px; background: var(--accent-amber-dim);
            border: 2px solid var(--accent-amber); display: flex; align-items: center; justify-content: center;
            font-size: 24px; color: var(--accent-amber); margin: 0 auto 16px auto; font-family: 'Space Grotesk', sans-serif;
            box-shadow: 0 0 25px var(--accent-amber-glow);
        }
        .auth-title { font-family: 'Space Grotesk', sans-serif; font-size: 22px; color: var(--text-primary); margin-bottom: 6px; }
        .auth-desc { font-size: 13px; color: var(--text-muted); margin-bottom: 20px; line-height: 1.4; }
        
        .auth-input {
            width: 100%; background: var(--surface-card); border: 1px solid var(--border-graphite);
            padding: 14px 16px; border-radius: 12px; color: #fff; font-size: 15px; margin-bottom: 14px; outline: none;
        }
        .auth-input:focus { border-color: var(--accent-amber); }
        
        .btn-auth {
            width: 100%; background: var(--accent-amber); color: #000; font-weight: 700;
            border: none; padding: 14px; border-radius: 12px; cursor: pointer; font-size: 14px;
            box-shadow: 0 4px 20px var(--accent-amber-glow);
        }

        .workspace { display: flex; width: 100%; height: 100%; position: relative; overflow: hidden; }

        .sidebar-panel {
            width: 380px; border-right: 1px solid var(--border-graphite);
            background: var(--surface-panel); display: flex; flex-direction: column; flex-shrink: 0;
            position: relative; height: 100%;
        }
        .sidebar-header {
            padding: 14px 16px; border-bottom: 1px solid var(--border-subtle);
            display: flex; align-items: center; justify-content: space-between; flex-shrink: 0;
        }
        .app-brand { font-family: 'Space Grotesk', sans-serif; font-size: 18px; font-weight: 700; color: var(--accent-amber); }
        .sidebar-search {
            padding: 10px 14px; border-bottom: 1px solid var(--border-subtle); display: flex; gap: 8px; flex-shrink: 0;
        }
        .search-input {
            flex: 1; background: var(--surface-card); border: 1px solid var(--border-graphite);
            padding: 10px 14px; border-radius: 12px; color: #fff; font-size: 13px; outline: none;
        }
        .chat-list { flex: 1; overflow-y: auto; padding-bottom: 60px; }
        .chat-item {
            padding: 14px 18px; border-bottom: 1px solid var(--border-subtle);
            display: flex; align-items: center; gap: 12px; cursor: pointer; transition: background 0.15s;
        }
        .chat-item:hover, .chat-item.active { background: var(--surface-hover); }
        .chat-avatar {
            width: 44px; height: 44px; border-radius: 50%; background: #1f2937;
            border: 1px solid var(--border-graphite); display: flex; align-items: center;
            justify-content: center; font-weight: 700; color: var(--accent-amber); flex-shrink: 0;
            overflow: hidden; font-size: 14px;
        }
        .chat-info { flex: 1; overflow: hidden; }
        .chat-title { font-size: 15px; font-weight: 600; white-space: nowrap; text-overflow: ellipsis; overflow: hidden; }
        .chat-subtitle { font-size: 12px; color: var(--text-muted); margin-top: 3px; }

        .bottom-nav-bar {
            height: 56px; border-top: 1px solid var(--border-graphite); background: var(--surface-panel);
            display: flex; align-items: center; justify-content: space-around; width: 100%;
            position: absolute; bottom: 0; left: 0; z-index: 30;
        }
        .nav-tab-btn {
            display: flex; flex-direction: column; align-items: center; gap: 3px;
            background: transparent; border: none; color: var(--text-muted); cursor: pointer;
            font-size: 11px; font-weight: 600; flex: 1; padding: 6px 0;
        }
        .nav-tab-btn span.tab-icon { font-size: 18px; }
        .nav-tab-btn.active { color: var(--accent-amber); }

        .stage-panel {
            flex: 1; display: flex; flex-direction: column; background: var(--bg-obsidian);
            position: relative; height: 100%; overflow: hidden;
        }
        .stage-header {
            padding: 8px 12px; background: var(--surface-panel);
            border-bottom: 1px solid var(--border-graphite);
            display: flex; align-items: center; justify-content: space-between;
            flex-shrink: 0; z-index: 10; min-height: 60px; gap: 6px;
        }

        .messages-container {
            flex: 1; padding: 14px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px;
            min-height: 0; -webkit-overflow-scrolling: touch;
        }
        .bubble {
            max-width: 82%; padding: 10px 14px; border-radius: 14px; font-size: 13px; line-height: 1.4; word-break: break-word;
        }
        .bubble.sent {
            align-self: flex-end; background: var(--accent-amber); color: #000; font-weight: 500; border-bottom-right-radius: 2px;
        }
        .bubble.received {
            align-self: flex-start; background: var(--surface-card); color: var(--text-primary);
            border: 1px solid var(--border-graphite); border-bottom-left-radius: 2px;
        }
        .bubble-translation {
            font-size: 12px; margin-top: 6px; padding-top: 6px; font-weight: 700;
            border-top: 1px dashed rgba(0, 0, 0, 0.25); color: #1e293b;
        }
        .bubble.received .bubble-translation {
            border-top: 1px dashed var(--border-graphite); color: var(--online-green);
        }

        .stage-input-bar {
            padding: 8px 12px; background: var(--surface-panel);
            border-top: 1px solid var(--border-graphite); display: flex; align-items: center;
            gap: 8px; flex-shrink: 0; z-index: 20; width: 100%;
        }
        .input-shell {
            flex: 1; background: var(--surface-card); border: 1px solid var(--border-graphite);
            border-radius: 22px; display: flex; align-items: center; padding: 2px 8px 2px 10px; gap: 6px;
        }
        .main-text-input {
            flex: 1; background: transparent; border: none; outline: none;
            color: var(--text-primary); font-size: 14px; padding: 8px 2px;
        }
        .btn-inside-mic {
            background: transparent; border: none; font-size: 18px; color: var(--accent-amber);
            cursor: pointer; padding: 4px 6px; border-radius: 50%; display: flex; align-items: center;
        }
        .recording-bar {
            flex: 1; background: var(--surface-card); border: 1px solid rgba(239, 68, 68, 0.4);
            border-radius: 22px; display: none; align-items: center; justify-content: space-between; padding: 6px 14px;
        }
        .rec-indicator { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; }
        .rec-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--danger-red); animation: blink 1s infinite; }
        @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.2; } }

        .btn-send-permanent {
            width: 40px; height: 40px; border-radius: 50%; background: var(--accent-amber);
            color: #000; border: none; font-size: 16px; cursor: pointer; flex-shrink: 0;
            display: flex; align-items: center; justify-content: center;
        }
        .icon-btn {
            background: transparent; border: none; color: var(--text-secondary);
            font-size: 18px; cursor: pointer; padding: 4px; border-radius: 8px;
        }

        .send-modal-backdrop {
            position: fixed; inset: 0; background: rgba(0, 0, 0, 0.88);
            backdrop-filter: blur(10px); z-index: 9999; display: none;
            align-items: center; justify-content: center; padding: 20px;
        }
        .send-modal-card {
            background: var(--surface-panel); border: 1px solid var(--border-graphite);
            border-radius: 20px; width: 100%; max-width: 380px; padding: 22px;
            display: flex; flex-direction: column; gap: 12px; text-align: center;
        }
        .modal-btn-choice {
            padding: 12px; border-radius: 12px; border: 1px solid var(--border-graphite);
            font-size: 13px; font-weight: 700; cursor: pointer; display: flex; align-items: center;
            justify-content: center; gap: 8px; background: var(--surface-card); color: #fff;
        }
        .btn-choice-trans { background: var(--accent-amber); color: #000; border: none; }
        .lang-options-drawer { display: flex; flex-direction: column; gap: 8px; margin-top: 6px; text-align: left; }
        .lang-dropdown {
            width: 100%; background: var(--surface-card); border: 1px solid var(--border-graphite);
            padding: 10px; border-radius: 10px; color: #fff; font-size: 13px; outline: none;
        }

        @media (max-width: 768px) {
            .sidebar-panel { width: 100%; height: 100dvh; display: flex; }
            .stage-panel { display: none; width: 100%; height: 100dvh; }
            body.in-chat .sidebar-panel { display: none !important; }
            body.in-chat .stage-panel { display: flex !important; flex-direction: column; height: 100dvh; }
        }
    </style>
</head>
<body onclick="unlockMobileAudio()">

    <audio id="remote-audio-sink" autoplay playsinline></audio>

    <div class="auth-overlay" id="auth-overlay">
        <div class="auth-card">
            <div class="auth-badge">IA</div>
            <h2 class="auth-title">Welcome to Syncora</h2>
            <p class="auth-desc">Chat, Call & Live AI Translation Terminal</p>
            <input type="tel" id="my-phone-input" class="auth-input" placeholder="Mobile Number (e.g. 03001234567)" onkeydown="if(event.key==='Enter'){ executeDirectLogin(); }">
            <button class="btn-auth" onclick="executeDirectLogin()">Enter Terminal →</button>
        </div>
    </div>

    <!-- Send Dispatch Modal -->
    <div class="send-modal-backdrop" id="send-modal">
        <div class="send-modal-card">
            <h3 style="font-size: 16px; color: var(--accent-amber);">Confirm Dispatch</h3>
            <p style="font-size: 12px; color: var(--text-muted);" id="send-modal-preview">Review message text</p>
            <div class="lang-options-drawer">
                <label style="font-size: 11px; color: var(--text-muted);">Select Target Language:</label>
                <select class="lang-dropdown" id="modal-target-lang">
                    <option value="en" selected>English (US)</option>
                    <option value="ur">Urdu (اردو)</option>
                    <option value="ar">Arabic (العربية)</option>
                    <option value="zh">Chinese (中文)</option>
                    <option value="de">German (Deutsch)</option>
                    <option value="fr">French (Français)</option>
                    <option value="es">Spanish (Español)</option>
                </select>
                <button class="modal-btn-choice btn-choice-trans" onclick="confirmDispatchTranslation()">🌐 Translate & Send</button>
            </div>
            <button class="modal-btn-choice" onclick="confirmDispatchOriginal()" style="margin-top: 4px;">✉️ Send Without Translation</button>
            <button onclick="cancelDispatch()" style="background: transparent; border: none; color: var(--text-muted); font-size: 12px; cursor: pointer;">Cancel</button>
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
            <nav class="bottom-nav-bar">
                <button class="nav-tab-btn active" onclick="switchTab('chats')"><span class="tab-icon">💬</span><span>Chats</span></button>
            </nav>
        </aside>

        <main class="stage-panel" id="stage-panel">
            <header class="stage-header">
                <div style="display: flex; align-items: center; gap: 6px; overflow: hidden;">
                    <button class="icon-btn" onclick="backToSidebar()" id="mobile-back-btn" style="font-size: 18px;">←</button>
                    <div class="chat-avatar" id="active-avatar">--</div>
                    <div style="overflow: hidden;">
                        <div style="font-size: 13px; font-weight: 700;" id="active-partner-label">Select Chat</div>
                        <div style="font-size: 10px; color: var(--text-muted);" id="active-partner-status">Offline</div>
                    </div>
                </div>
            </header>

            <div class="messages-container" id="messages-container"></div>

            <footer class="stage-input-bar">
                <div class="input-shell" id="input-shell">
                    <input type="text" id="text-input" class="main-text-input" placeholder="Message..." onkeydown="if(event.key==='Enter'){ event.preventDefault(); stageMessageForDispatch(); }">
                    <button class="btn-inside-mic" id="inside-mic-btn" type="button" onclick="toggleVoiceRecording()" title="Record Voice Note">🎙️</button>
                </div>
                <div class="recording-bar" id="recording-bar">
                    <div class="rec-indicator">
                        <div class="rec-dot"></div>
                        <span style="font-size:12px; color:var(--accent-amber);">Recording Audio...</span>
                    </div>
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <button class="icon-btn" type="button" onclick="cancelRecording()" style="color: var(--danger-red);">🗑️</button>
                        <button class="icon-btn" type="button" onclick="stopAndFinishRecording()" style="color: var(--online-green);">✓</button>
                    </div>
                </div>
                <button class="btn-send-permanent" id="send-arrow-btn" type="button" onclick="stageMessageForDispatch()" title="Send">➤</button>
            </footer>
        </main>
    </div>

    <script>
        let mobileAudioUnlocked = false;
        function unlockMobileAudio() {
            if (mobileAudioUnlocked) return;
            try {
                if ('speechSynthesis' in window) {
                    const silentUtterance = new SpeechSynthesisUtterance(' ');
                    silentUtterance.volume = 0.01;
                    window.speechSynthesis.speak(silentUtterance);
                }
                mobileAudioUnlocked = true;
            } catch(e) {}
        }

        let myPhone = localStorage.getItem("syncora_user_phone") || "";
        let activePartner = localStorage.getItem("syncora_active_partner") || "";
        let allChatsCache = JSON.parse(localStorage.getItem("syncora_cached_chats") || "[]");
        let socket = null;
        let isConnectingSocket = false;
        let pendingPayload = null;

        let mediaRecorder = null;
        let recordedChunks = [];
        let isRecording = false;
        let activeAudioStream = null;

        window.onload = async () => {
            renderChatListFromCache();
            if (myPhone) {
                document.getElementById("auth-overlay").style.display = "none";
                document.getElementById("my-status-label").innerText = `● ${myPhone}`;
                initSocketSafe();
                await loadRecentChats();
                if (allChatsCache.length > 0) selectChat(allChatsCache[0]);
            }
        };

        function renderChatListFromCache() {
            const list = document.getElementById("chat-list");
            if (!list) return;
            list.innerHTML = "";
            allChatsCache.forEach(partner => renderChatItem(partner));
        }

        function renderChatItem(partner) {
            const list = document.getElementById("chat-list");
            const item = document.createElement("div");
            item.className = `chat-item ${partner === activePartner ? 'active' : ''}`;
            item.onclick = () => selectChat(partner);
            item.innerHTML = `
                <div class="chat-avatar">${partner.slice(-2)}</div>
                <div class="chat-info">
                    <div class="chat-title">${partner}</div>
                    <div class="chat-subtitle">Direct line active</div>
                </div>
            `;
            list.appendChild(item);
        }

        async function executeDirectLogin() {
            unlockMobileAudio();
            const input = document.getElementById("my-phone-input").value.trim();
            if (!input || input.length < 7) { alert("Please valid mobile number enter karein."); return; }

            const res = await fetch("/api/auth/login", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ phone: input })
            });
            if (res.ok) {
                myPhone = input;
                localStorage.setItem("syncora_user_phone", myPhone);
                document.getElementById("auth-overlay").style.display = "none";
                document.getElementById("my-status-label").innerText = `● ${myPhone}`;
                initSocketSafe();
                await loadRecentChats();
                if (allChatsCache.length > 0) selectChat(allChatsCache[0]);
            }
        }

        function initSocketSafe() {
            if (!myPhone || isConnectingSocket) return;
            if (socket && socket.readyState === WebSocket.OPEN) return;
            isConnectingSocket = true;
            const proto = window.location.protocol === "https:" ? "wss://" : "ws://";
            
            socket = new WebSocket(`${proto}${window.location.host}/ws/${myPhone}`);
            socket.onopen = () => { isConnectingSocket = false; };
            socket.onmessage = async (event) => {
                const data = JSON.parse(event.data);
                if (data.action === "new_message") {
                    if (data.sender === activePartner) {
                        appendBubble(data.content, "received", data.translated, data.msg_type, data.time, data.id);
                    }
                    loadRecentChats();
                }
            };
            socket.onclose = () => { isConnectingSocket = false; socket = null; setTimeout(initSocketSafe, 3000); };
        }

        async function loadRecentChats() {
            if (!myPhone) return;
            try {
                const res = await fetch(`/api/chats/${myPhone}`);
                const data = await res.json();
                (data.chats || []).forEach(p => { if (!allChatsCache.includes(p)) allChatsCache.push(p); });
                localStorage.setItem("syncora_cached_chats", JSON.stringify(allChatsCache));
                renderChatListFromCache();
            } catch(e){}
        }

        async function selectChat(partner) {
            if (!partner) return;
            activePartner = partner;
            localStorage.setItem("syncora_active_partner", activePartner);
            document.body.classList.add("in-chat");
            document.getElementById("active-partner-label").innerText = partner;
            document.getElementById("active-avatar").innerText = partner.slice(-2);

            const res = await fetch(`/api/messages/${myPhone}/${partner}`);
            const data = await res.json();
            const box = document.getElementById("messages-container");
            box.innerHTML = "";
            data.messages.forEach(m => {
                appendBubble(m.content, m.sender === myPhone ? "sent" : "received", m.translated_content, m.msg_type, m.time, m.id);
            });
        }

        function backToSidebar() { document.body.classList.remove("in-chat"); }

        function stageMessageForDispatch() {
            const text = document.getElementById("text-input").value.trim();
            if (!text || !activePartner) return;
            pendingPayload = { content: text, type: "text" };
            document.getElementById("send-modal-preview").innerText = `"${text}"`;
            document.getElementById("send-modal").style.display = "flex";
        }

        function cancelDispatch() { pendingPayload = null; document.getElementById("send-modal").style.display = "none"; }

        function confirmDispatchOriginal() {
            if (!pendingPayload) return;
            executeDispatch(pendingPayload.content, "", pendingPayload.type);
            cancelDispatch();
        }

        async function confirmDispatchTranslation() {
            if (!pendingPayload) return;
            const targetLang = document.getElementById("modal-target-lang").value;
            let translatedText = pendingPayload.content;
            if (pendingPayload.type === "text") {
                try {
                    const res = await fetch("/translate", {
                        method: "POST", headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ text: pendingPayload.content, target_lang: targetLang })
                    });
                    const data = await res.json();
                    translatedText = data.translated_text || pendingPayload.content;
                } catch(e){}
            }
            executeDispatch(pendingPayload.content, translatedText, pendingPayload.type, targetLang);
            cancelDispatch();
        }

        function executeDispatch(content, translated, msgType, lang = "en") {
            if (!activePartner) return;
            appendBubble(content, "sent", translated, msgType, "now", "temp_" + Date.now());
            document.getElementById("text-input").value = "";
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ action: "chat_message", receiver: activePartner, msg_type: msgType, content: content, translated: translated, lang: lang }));
            }
            loadRecentChats();
        }

        function appendBubble(content, dir, translated, type, time, msgId = null) {
            const box = document.getElementById("messages-container");
            const bubble = document.createElement("div");
            bubble.className = `bubble ${dir}`;

            let body = `<div>${content}</div>`;
            if (type === "voice") {
                const pid = "audio_" + Math.random().toString(36).substring(2, 9);
                body = `
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <audio id="${pid}" src="${content}"></audio>
                        <button onclick="document.getElementById('${pid}').play()" style="background:#000; color:var(--accent-amber); border:none; width:36px; height:36px; border-radius:50%; cursor:pointer;">▶</button>
                        <span style="font-size:12px; font-weight:600;">Voice Note</span>
                    </div>
                `;
            } else if (translated && translated.trim() !== "") {
                body += `<div class="bubble-translation">Translation: ${translated}</div>`;
            }
            
            bubble.innerHTML = body + `<div style="font-size:9px; opacity:0.6; text-align:right; margin-top:2px;">${time}</div>`;
            box.appendChild(bubble);
            box.scrollTop = box.scrollHeight;
        }

        function toggleVoiceRecording() {
            if (!isRecording) startVoiceRecording();
            else stopAndFinishRecording();
        }

        async function startVoiceRecording() {
            try {
                activeAudioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
                mediaRecorder = new MediaRecorder(activeAudioStream);
                recordedChunks = [];
                mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) recordedChunks.push(e.data); };
                mediaRecorder.onstop = async () => {
                    const blob = new Blob(recordedChunks, { type: "audio/webm" });
                    const form = new FormData(); form.append("file", blob, "voice.webm");
                    const res = await fetch("/api/upload", { method: "POST", body: form });
                    const data = await res.json();
                    
                    pendingPayload = { content: data.url, type: "voice" };
                    document.getElementById("send-modal-preview").innerText = "Voice Note Ready to Send";
                    document.getElementById("send-modal").style.display = "flex";
                };
                mediaRecorder.start();
                isRecording = true;
                document.getElementById("input-shell").style.display = "none";
                document.getElementById("recording-bar").style.display = "flex";
            } catch (err) { alert("Mic error: " + err.message); }
        }

        function stopAndFinishRecording() {
            if (mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
            if (activeAudioStream) { activeAudioStream.getTracks().forEach(t => t.stop()); activeAudioStream = null; }
            resetRecordingUI();
        }

        function cancelRecording() {
            if (mediaRecorder && mediaRecorder.state !== "inactive") mediaRecorder.stop();
            if (activeAudioStream) { activeAudioStream.getTracks().forEach(t => t.stop()); activeAudioStream = null; }
            resetRecordingUI();
            cancelDispatch();
        }

        function resetRecordingUI() {
            isRecording = false;
            document.getElementById("recording-bar").style.display = "none";
            document.getElementById("input-shell").style.display = "flex";
        }
    </script>
</body>
</html>"""

# FastAPI Endpoints
@app.post("/translate")
async def translate_endpoint(req: TranslationRequest):
    return {"status": "success", "translated_text": translate_text_engine(req.text, req.target_lang)}

@app.post("/api/auth/login")
async def api_login(req: LoginRequest):
    user_profiles[req.phone] = user_profiles.get(req.phone, {"phone": req.phone})
    return {"status": "success", "phone": req.phone}

@app.post("/api/contacts/add")
async def add_contact(req: ContactRequest):
    contacts = user_contacts.setdefault(req.user_phone, [])
    if req.contact_phone not in contacts: contacts.append(req.contact_phone)
    return {"status": "success", "contacts": contacts}

@app.get("/api/chats/{phone}")
async def get_chats(phone: str):
    return {"chats": user_contacts.get(phone, [])}

@app.get("/api/messages/{user1}/{user2}")
async def get_messages(user1: str, user2: str):
    return {"messages": message_history.get(tuple(sorted([user1, user2])), [])}

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
                msg_record = {
                    "id": str(os.urandom(4).hex()), "sender": client_id,
                    "content": data.get("content"), "translated_content": data.get("translated"),
                    "msg_type": data.get("msg_type", "text"), "time": "now"
                }
                key = tuple(sorted([client_id, data.get("receiver")]))
                message_history.setdefault(key, []).append(msg_record)
                if data.get("receiver") in active_connections:
                    await active_connections[data.get("receiver")].send_text(json.dumps({"action": "new_message", **msg_record}))
    except WebSocketDisconnect:
        active_connections.pop(client_id, None)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
