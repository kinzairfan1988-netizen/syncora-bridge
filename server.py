import os
import shutil
import json
import sqlite3
import secrets
import urllib.request
import urllib.parse
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Syncora Terminal - Pre-filled WhatsApp Invite Fix")

# Directories and Database setup
os.makedirs("uploads", exist_ok=True)
os.makedirs("static", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

DB_FILE = "syncora.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    name TEXT,
                    invite_token TEXT UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS contacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    contact_id TEXT,
                    UNIQUE(user_id, contact_id)
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user1 TEXT,
                    user2 TEXT,
                    UNIQUE(user1, user2)
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conv_id INTEGER,
                    sender_id TEXT,
                    content TEXT,
                    translated TEXT,
                    msg_type TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
    conn.commit()
    conn.close()

init_db()

active_connections = {}

class TranslationRequest(BaseModel):
    text: str
    target_lang: str = "en"

class RegisterUserRequest(BaseModel):
    user_id: str
    name: str = "User"

class AcceptInviteRequest(BaseModel):
    user_id: str
    inviter_id: str
    name: str = "User"

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

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)

@app.post("/api/register")
async def register_user(req: RegisterUserRequest):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT invite_token FROM users WHERE user_id = ?", (req.user_id,))
    row = c.fetchone()
    if row:
        token = row[0]
    else:
        token = secrets.token_urlsafe(12)
        c.execute("INSERT OR REPLACE INTO users (user_id, name, invite_token) VALUES (?, ?, ?)", (req.user_id, req.name, token))
        conn.commit()
    conn.close()
    return {"status": "success", "invite_token": token}

@app.get("/api/invite-info/{token}")
async def invite_info(token: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id, name FROM users WHERE invite_token = ?", (token,))
    row = c.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Invalid invite link")
    return {"inviter_id": row[0], "inviter_name": row[1]}

@app.post("/api/accept-invite")
async def accept_invite(req: AcceptInviteRequest):
    if req.user_id == req.inviter_id:
        return {"status": "self"}
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    for uid in [req.user_id, req.inviter_id]:
        c.execute("SELECT user_id FROM users WHERE user_id = ?", (uid,))
        if not c.fetchone():
            c.execute("INSERT OR IGNORE INTO users (user_id, name, invite_token) VALUES (?, ?, ?)", (uid, req.name if uid == req.user_id else "User", secrets.token_urlsafe(12)))
    
    c.execute("INSERT OR IGNORE INTO contacts (user_id, contact_id) VALUES (?, ?)", (req.user_id, req.inviter_id))
    c.execute("INSERT OR IGNORE INTO contacts (user_id, contact_id) VALUES (?, ?)", (req.inviter_id, req.user_id))
    
    u1, u2 = sorted([req.user_id, req.inviter_id])
    c.execute("SELECT id FROM conversations WHERE user1 = ? AND user2 = ?", (u1, u2))
    conv = c.fetchone()
    if not conv:
        c.execute("INSERT INTO conversations (user1, user2) VALUES (?, ?)", (u1, u2))
        conv_id = c.lastrowid
    else:
        conv_id = conv[0]
    conn.commit()
    conn.close()
    return {"status": "success", "conv_id": conv_id}

@app.get("/api/contacts/{user_id}")
async def get_contacts(user_id: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT u.user_id, u.name 
        FROM contacts c 
        JOIN users u ON c.contact_id = u.user_id 
        WHERE c.user_id = ?
    """, (user_id,))
    rows = c.fetchall()
    contacts = []
    for r in rows:
        c_id, c_name = r[0], r[1]
        u1, u2 = sorted([user_id, c_id])
        c.execute("SELECT id FROM conversations WHERE user1 = ? AND user2 = ?", (u1, u2))
        conv = c.fetchone()
        conv_id = conv[0] if conv else None
        
        last_msg = ""
        if conv_id:
            c.execute("SELECT content FROM messages WHERE conv_id = ? ORDER BY id DESC LIMIT 1", (conv_id,))
            msg_row = c.fetchone()
            if msg_row:
                last_msg = msg_row[0]
        
        contacts.append({
            "user_id": c_id,
            "name": c_name or c_id[:6],
            "conv_id": conv_id,
            "last_message": last_msg
        })
    conn.close()
    return {"contacts": contacts}

@app.get("/api/messages/{conv_id}")
async def get_messages(conv_id: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT sender_id, content, translated, msg_type, timestamp FROM messages WHERE conv_id = ? ORDER BY id ASC", (conv_id,))
    rows = c.fetchall()
    messages = []
    for r in rows:
        messages.append({
            "sender_id": r[0],
            "content": r[1],
            "translated": r[2],
            "msg_type": r[3],
            "timestamp": r[4]
        })
    conn.close()
    return {"messages": messages}

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
        .search-box-container { padding: 12px 16px; border-bottom: 1px solid var(--border); display: flex; flex-direction: column; gap: 8px; }
        .search-input { width: 100%; background: var(--card); border: 1px solid var(--border); padding: 10px 14px; border-radius: 8px; color: #fff; outline: none; font-size: 13px; }
        .action-row { display: flex; gap: 6px; }
        .btn-invite { background: var(--accent); color: #000; border: none; padding: 8px 12px; border-radius: 8px; cursor: pointer; font-weight: bold; font-size: 12px; flex: 1; }
        .wa-direct-btn { background: #25D366; color: #fff; border: none; padding: 8px 12px; border-radius: 8px; cursor: pointer; font-weight: bold; font-size: 12px; flex-shrink: 0; }
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
            <p style="font-size: 12px; color: var(--muted); margin-bottom: 20px;">Enter your name to start</p>
            <input type="text" id="my-name-input" class="auth-input" placeholder="e.g. Ali Khan" onkeydown="if(event.key==='Enter') forceLogin()">
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
                <span id="my-name-display" style="font-size: 12px; color: var(--green);"></span>
            </div>
            <div class="search-box-container">
                <input type="text" class="search-input" placeholder="Search chats..." id="search-chats" onkeyup="filterChats()">
                <div class="action-row">
                    <button class="btn-invite" onclick="generateInviteLink()">🔗 Invite Link</button>
                    <input type="text" class="search-input" placeholder="WA number..." id="wa-phone-input" style="flex:1;">
                    <button class="wa-direct-btn" onclick="openWhatsAppDirect()">WA</button>
                </div>
            </div>
            <div class="chat-list" id="chat-list"></div>
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
                    <button class="attach-item" onclick="sendWhatsAppLinkOption()">💬 Send WhatsApp Link</button>
                </div>

                <button class="btn-action" onclick="toggleAttachMenu()" title="Attach">📎</button>
                <input type="text" id="text-input" class="main-input" placeholder="Message..." onkeydown="if(event.key==='Enter') stageMessage()">
                <button class="btn-action" onclick="toggleVoiceRecording()" title="Voice Note">🎙️</button>
                <button class="btn-send" onclick="stageMessage()">➤</button>
            </footer>
        </main>
    </div>

    <script>
        let myUserId = localStorage.getItem("syncora_user_id");
        let myName = localStorage.getItem("syncora_user_name") || "";
        let myInviteToken = "";
        let activePartner = null;
        let activeConvId = null;
        let socket = null;
        let pendingText = "";
        let contactsList = [];
        
        let mediaRecorder = null;
        let audioChunks = [];
        let isRecording = false;

        window.onload = async function() {
            if (!myUserId) {
                myUserId = 'user_' + Math.random().toString(36).substring(2, 11) + Date.now().toString(36);
                localStorage.setItem("syncora_user_id", myUserId);
            }
            
            if (myName && myName.trim() !== "") {
                document.getElementById("my-name-input").value = myName;
                document.getElementById("auth-overlay").style.display = "none";
                document.getElementById("my-name-display").innerText = myName;
                const urlParams = new URLSearchParams(window.location.search);
                await registerAndInit(urlParams.get('invite'));
            }
        };

        async function forceLogin() {
            const val = document.getElementById("my-name-input").value.trim();
            if (!val) { alert("Naam enter karein!"); return; }
            myName = val;
            localStorage.setItem("syncora_user_name", myName);
            
            const overlay = document.getElementById("auth-overlay");
            if (overlay) overlay.style.display = "none";
            
            const display = document.getElementById("my-name-display");
            if (display) display.innerText = myName;
            
            const urlParams = new URLSearchParams(window.location.search);
            await registerAndInit(urlParams.get('invite'));
        }

        async function registerAndInit(inviteToken) {
            try {
                const res = await fetch("/api/register", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ user_id: myUserId, name: myName })
                });
                const data = await res.json();
                myInviteToken = data.invite_token;

                if (inviteToken) {
                    const invRes = await fetch(`/api/invite-info/${inviteToken}`);
                    if (invRes.ok) {
                        const invData = await invRes.json();
                        if (invData.inviter_id !== myUserId) {
                            await fetch("/api/accept-invite", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ user_id: myUserId, inviter_id: invData.inviter_id, name: myName })
                            });
                            window.history.replaceState({}, document.title, window.location.pathname);
                        }
                    }
                }
            } catch(e) {}

            initSocket();
            loadContacts();
        }

        function initSocket() {
            if (!myUserId) return;
            const proto = window.location.protocol === "https:" ? "wss://" : "ws://";
            socket = new WebSocket(proto + window.location.host + "/ws/" + encodeURIComponent(myUserId));

            socket.onopen = function() {
                const status = document.getElementById("active-chat-status");
                if (status) { status.innerText = "Online"; status.style.color = "var(--green)"; }
            };

            socket.onmessage = function(e) {
                try {
                    const data = JSON.parse(e.data);
                    if (data.action === "new_message" && data.conv_id === activeConvId) {
                        appendBubble(data.content, "received", data.translated, data.msg_type);
                    }
                    loadContacts();
                } catch (err) {}
            };

            socket.onerror = function(error) {
                const status = document.getElementById("active-chat-status");
                if (status) { status.innerText = "Connection Error"; status.style.color = "var(--red)"; }
            };

            socket.onclose = function(event) {
                const status = document.getElementById("active-chat-status");
                if (status) { status.innerText = "Offline"; status.style.color = "var(--muted)"; }
            };
        }

        async function loadContacts() {
            try {
                const res = await fetch(`/api/contacts/${myUserId}`);
                const data = await res.json();
                contactsList = data.contacts || [];
                renderContacts(contactsList);
            } catch(e) {}
        }

        function renderContacts(list) {
            const listEl = document.getElementById("chat-list");
            listEl.innerHTML = "";
            if (list.length === 0) {
                listEl.innerHTML = `<div style="padding:20px; text-align:center; color:var(--muted); font-size:13px;">No contacts yet.<br>Click 'Invite Link' to add friends!</div>`;
                return;
            }
            list.forEach(c => {
                const div = document.createElement("div");
                div.className = "chat-item";
                div.onclick = () => selectContact(c);
                div.innerHTML = `
                    <div style="width:36px; height:36px; background:#2d3748; border-radius:50%; display:flex; align-items:center; justify-content:center; color:var(--accent); font-weight:700;">${c.name.slice(0,2).toUpperCase()}</div>
                    <div style="flex:1; overflow:hidden;">
                        <div style="font-weight:600; font-size:14px;">${c.name}</div>
                        <div style="font-size:11px; color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${c.last_message || 'Tap to chat'}</div>
                    </div>
                `;
                listEl.appendChild(div);
            });
        }

        function filterChats() {
            const query = document.getElementById("search-chats").value.toLowerCase();
            const filtered = contactsList.filter(c => c.name.toLowerCase().includes(query));
            renderContacts(filtered);
        }

        function generateInviteLink() {
            if (!myInviteToken) { alert("Not registered yet!"); return; }
            const inviteUrl = `${window.location.origin}/?invite=${myInviteToken}`;
            prompt("Copy your invite link:", inviteUrl);
        }

        async function selectContact(c) {
            activePartner = c.user_id;
            activeConvId = c.conv_id;
            document.getElementById("active-chat-title").innerText = c.name;
            document.getElementById("header-avatar").innerText = c.name.slice(0,2).toUpperCase();
            
            const msgContainer = document.getElementById("messages-container");
            msgContainer.innerHTML = "";
            
            if (activeConvId) {
                try {
                    const res = await fetch(`/api/messages/${activeConvId}`);
                    const data = await res.json();
                    (data.messages || []).forEach(m => {
                        const dir = m.sender_id === myUserId ? "sent" : "received";
                        appendBubble(m.content, dir, m.translated, m.msg_type);
                    });
                } catch(e) {}
            }
        }

        function openWhatsAppDirect() {
            if (!myInviteToken) { alert("Please wait, generating invite token..."); return; }
            const phoneInput = document.getElementById("wa-phone-input").value.trim();
            const inviteUrl = `${window.location.origin}/?invite=${myInviteToken}`;
            const messageText = `Join me on Syncora:\n${inviteUrl}`;
            
            let waUrl = "";
            if (phoneInput) {
                const cleanNum = phoneInput.replace(/[^0-9]/g, '');
                waUrl = `https://wa.me/${cleanNum}?text=${encodeURIComponent(messageText)}`;
            } else {
                waUrl = `https://wa.me/?text=${encodeURIComponent(messageText)}`;
            }
            window.open(waUrl, '_blank');
        }

        function sendWhatsAppLinkOption() {
            document.getElementById("attach-menu").style.display = "none";
            if(!activePartner) { alert("Select contact first!"); return; }
            const inviteUrl = `${window.location.origin}/?invite=${myInviteToken}`;
            dispatchMsg(inviteUrl, "Syncora Invite Link", "whatsapp_link");
        }

        function switchTab(tab) {
            document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));
            event.currentTarget.classList.add('active');
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
            if(!activePartner) { alert("Select contact first!"); return; }
            if(input.files && input.files[0]) {
                const form = new FormData();
                form.append("file", input.files[0]);
                try {
                    const res = await fetch("/api/upload", { method: "POST", body: form });
                    const data = await res.json();
                    if(data.url) { dispatchMsg(data.url, "", fileType); }
                } catch(e) { alert("Upload failed"); }
            }
        }

        function sendLocation() {
            document.getElementById("attach-menu").style.display = "none";
            if(!activePartner) { alert("Select contact first!"); return; }
            if (navigator.geolocation) {
                navigator.geolocation.getCurrentPosition(position => {
                    const mapUrl = `https://maps.google.com/?q=${position.coords.latitude},${position.coords.longitude}`;
                    dispatchMsg(mapUrl, "Shared Location", "location");
                }, () => alert("Unable to retrieve location"));
            }
        }

        function startAudioCall() { alert("Audio calling initiated"); }
        function startVideoCall() { alert("Video calling initiated"); }
        function openTranslationSettings() { alert("Translation options active"); }

        function stageMessage() {
            const txt = document.getElementById("text-input").value;
            if (!txt || !activePartner) { alert("Select contact and enter message!"); return; }
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
            if (!activePartner) { alert("Select contact first!"); return; }
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
                            if (data.url) { dispatchMsg(data.url, "", "voice"); }
                        } catch(err) { alert("Audio upload failed"); }
                        stream.getTracks().forEach(t => t.stop());
                    };
                    mediaRecorder.start();
                    isRecording = true;
                    event.target.style.background = "var(--red)";
                } catch(e) { alert("Mic permission denied"); }
            } else {
                mediaRecorder.stop();
                isRecording = false;
                event.target.style.background = "var(--card)";
            }
        }

        function dispatchMsg(content, translated, type) {
            appendBubble(content, "sent", translated, type);
            document.getElementById("text-input").value = "";
            if (socket && socket.readyState === WebSocket.OPEN && activeConvId) {
                socket.send(JSON.stringify({
                    action: "chat_message",
                    conv_id: activeConvId,
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
                html = `<div style="display:flex; align-items:center; gap:10px;"><audio id="${aid}" src="${text}"></audio><button onclick="document.getElementById('${aid}').play()" style="background:#000; color:var(--accent); border:none; width:34px; height:34px; border-radius:50%; cursor:pointer;">▶</button><span style="font-size:12px; font-weight:600;">Voice Note</span></div>`;
            } else if (type === "media") {
                html = `<img src="${text}" style="max-width:200px; border-radius:8px;" /><div style="font-size:11px; margin-top:4px;">Photo / Video</div>`;
            } else if (type === "document") {
                html = `<a href="${text}" target="_blank" style="color:var(--accent); text-decoration:underline; font-weight:600;">📄 Download Document</a>`;
            } else if (type === "location") {
                html = `<a href="${text}" target="_blank" style="color:var(--accent); text-decoration:underline; font-weight:600;">📍 View Shared Location</a>`;
            } else if (type === "whatsapp_link") {
                html = `<a href="${text}" target="_blank" style="color:#25D366; text-decoration:underline; font-weight:600;">💬 Open Invite Link</a>`;
            } else {
                html = "<div>" + text + "</div>";
                if (translated && translated.trim()) {
                    html += "<div style='font-size:11px; margin-top:4px; padding-top:4px; border-top:1px dashed rgba(0,0,0,0.2); font-weight:700;'>" + translated + "</div>";
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
                conv_id = data.get("conv_id")
                receiver = data.get("receiver")
                content = data.get("content")
                translated = data.get("translated")
                msg_type = data.get("msg_type", "text")
                
                if conv_id:
                    conn = sqlite3.connect(DB_FILE)
                    c = conn.cursor()
                    c.execute("INSERT INTO messages (conv_id, sender_id, content, translated, msg_type) VALUES (?, ?, ?, ?, ?)",
                              (conv_id, client_id, content, translated, msg_type))
                    conn.commit()
                    conn.close()
                
                if receiver in active_connections:
                    await active_connections[receiver].send_text(json.dumps({
                        "action": "new_message",
                        "sender": client_id,
                        "conv_id": conv_id,
                        "content": content,
                        "translated": translated,
                        "msg_type": msg_type
                    }))
    except WebSocketDisconnect:
        active_connections.pop(client_id, None)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
