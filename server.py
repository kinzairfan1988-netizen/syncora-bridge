import os
import json
import asyncio
from typing import List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
from deep_translator import GoogleTranslator, MyMemoryTranslator
import edge_tts

app = FastAPI(title="Syncora Sourcing Bridge")

# Microsoft Neural Voices
VOICE_MAP = {
    "ur": "ur-PK-AsadNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
    "en": "en-US-JennyNeural"
}

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message))
            except Exception:
                pass

manager = ConnectionManager()

# Edge-TTS Audio Generation
@app.get("/tts")
async def text_to_speech(text: str, lang: str):
    if not text.strip():
        return Response(content=b"", media_type="audio/mpeg")
    
    prefix = lang[:2].lower()
    voice = VOICE_MAP.get(prefix, "en-US-JennyNeural")
    
    communicate = edge_tts.Communicate(text, voice)
    mp3_bytes = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_bytes += chunk["data"]
            
    return Response(content=mp3_bytes, media_type="audio/mpeg")

# Reliable Multi-Provider Translation
def perform_translation(text: str, src_lang: str, tgt_lang: str) -> str:
    # 1. MyMemory Codes (Strict exact codes jaisa unki list me hai)
    mm_map = {
        "ur": "ur-PK",
        "zh": "zh-CN",
        "en": "en-US"
    }
    mm_src = mm_map.get(src_lang[:2].lower(), "en-US")
    mm_tgt = mm_map.get(tgt_lang[:2].lower(), "zh-CN")

    # Primary: MyMemory Translator (Cloud par block nahi hota)
    try:
        res = MyMemoryTranslator(source=mm_src, target=mm_tgt).translate(text)
        if res and not res.strip().startswith("["):
            return res
    except Exception:
        pass

    # Secondary Backup: Google Translator
    try:
        g_src = "zh-CN" if src_lang.lower().startswith("zh") else src_lang[:2].lower()
        g_tgt = "zh-CN" if tgt_lang.lower().startswith("zh") else tgt_lang[:2].lower()
        res = GoogleTranslator(source=g_src, target=g_tgt).translate(text)
        if res:
            return res
    except Exception as e:
        return f"[Translation Error: {str(e)}]"

    return text

@app.websocket("/ws/room")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            
            sender = data.get("sender", "Anonymous")
            src_lang = data.get("source_lang", "ur-PK")
            tgt_lang = data.get("target_lang", "zh-CN")
            original_text = data.get("text", "").strip()

            if not original_text:
                continue

            translated_text = perform_translation(original_text, src_lang, tgt_lang)

            payload = {
                "sender": sender,
                "source_lang": src_lang,
                "target_lang": tgt_lang,
                "original": original_text,
                "translated": translated_text
            }
            await manager.broadcast(payload)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)

@app.get("/", response_class=HTMLResponse)
async def get_index():
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Syncora Digital | Sourcing Bridge</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 15px; }
        .container { max-width: 600px; margin: auto; background: #1e293b; padding: 20px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.4); }
        h2 { margin-top: 0; color: #38bdf8; text-align: center; }
        .config-box { display: flex; gap: 10px; margin-bottom: 15px; }
        select, input { width: 100%; padding: 10px; border-radius: 8px; border: 1px solid #475569; background: #334155; color: white; box-sizing: border-box; }
        .controls { text-align: center; margin: 20px 0; }
        button { background: #22c55e; color: white; border: none; padding: 14px 24px; font-size: 16px; font-weight: bold; border-radius: 30px; cursor: pointer; width: 100%; transition: 0.2s; }
        button.recording { background: #ef4444; }
        #chat-box { height: 350px; overflow-y: auto; background: #0f172a; padding: 12px; border-radius: 8px; border: 1px solid #334155; }
        .bubble { margin-bottom: 12px; padding: 10px; border-radius: 8px; background: #1e293b; }
        .bubble .sender { font-weight: bold; font-size: 12px; color: #38bdf8; margin-bottom: 4px; }
        .bubble .orig { font-size: 14px; color: #94a3b8; }
        .bubble .trans { font-size: 16px; font-weight: 500; color: #f8fafc; margin-top: 2px; }
    </style>
</head>
<body>

<div class="container">
    <h2>⚡ Syncora Sourcing Bridge</h2>
    
    <div class="config-box">
        <input type="text" id="username" placeholder="Your Name" value="Ali">
        <select id="my-lang">
            <option value="ur-PK" selected>🇵🇰 Urdu</option>
            <option value="zh-CN">🇨🇳 Chinese (Mandarin)</option>
            <option value="en-US">🇬🇧 English</option>
        </select>
    </div>

    <div class="controls">
        <button id="mic-btn" onclick="toggleSpeech()">🎤 Push to Speak</button>
    </div>

    <div id="chat-box"></div>
</div>

<script>
    const wsUrl = (window.location.protocol === "https:" ? "wss://" : "ws://") + window.location.host + "/ws/room";
    let socket = new WebSocket(wsUrl);
    const audioPlayer = new Audio();

    socket.onmessage = function(event) {
        const msg = JSON.parse(event.data);
        const chatBox = document.getElementById("chat-box");

        const bubble = document.createElement("div");
        bubble.className = "bubble";
        bubble.innerHTML = `
            <div class="sender">${msg.sender} (${msg.source_lang})</div>
            <div class="orig">${msg.original}</div>
            <div class="trans">👉 <b>${msg.translated}</b></div>
        `;
        chatBox.appendChild(bubble);
        chatBox.scrollTop = chatBox.scrollHeight;

        const myLang = document.getElementById("my-lang").value;
        const myName = document.getElementById("username").value;

        // Play audio if received for target language or by receiver
        if (msg.target_lang.startsWith(myLang.substring(0, 2)) || msg.sender !== myName) {
            speakText(msg.translated, msg.target_lang);
        }
    };

    function speakText(text, lang) {
        if (!text || text.startsWith("[Translation Error")) return;
        const url = `/tts?text=${encodeURIComponent(text)}&lang=${encodeURIComponent(lang)}`;
        audioPlayer.src = url;
        audioPlayer.play().catch(e => {
            console.log("Audio unlock or play error:", e);
        });
    }

    let recognition;
    let isListening = false;
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (SpeechRecognition) {
        recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = false;

        recognition.onstart = function() {
            isListening = true;
            document.getElementById("mic-btn").className = "recording";
            document.getElementById("mic-btn").innerText = "🛑 Listening... Tap to Send";
        };

        recognition.onresult = function(event) {
            const transcript = event.results[0][0].transcript;
            const sender = document.getElementById("username").value;
            const myLang = document.getElementById("my-lang").value;
            
            // Auto target mapping: Urdu -> Chinese, Chinese -> Urdu, English -> Urdu
            let targetLang = "ur-PK";
            if (myLang.startsWith("ur")) {
                targetLang = "zh-CN";
            } else if (myLang.startsWith("zh")) {
                targetLang = "ur-PK";
            } else {
                targetLang = "ur-PK";
            }

            socket.send(JSON.stringify({
                sender: sender,
                source_lang: myLang,
                target_lang: targetLang,
                text: transcript
            }));
        };

        recognition.onerror = function(e) {
            console.error(e);
            stopListening();
        };

        recognition.onend = function() {
            stopListening();
        };
    }

    function toggleSpeech() {
        // Mobile Browser audio channel unlock
        audioPlayer.play().then(() => audioPlayer.pause()).catch(() => {});

        if (!recognition) {
            alert("Speech recognition is only supported in Chrome, Edge, or Safari.");
            return;
        }
        if (isListening) {
            recognition.stop();
            stopListening();
        } else {
            recognition.lang = document.getElementById("my-lang").value;
            recognition.start();
        }
    }

    function stopListening() {
        isListening = false;
        document.getElementById("mic-btn").className = "";
        document.getElementById("mic-btn").innerText = "🎤 Push to Speak";
    }
</script>

</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
