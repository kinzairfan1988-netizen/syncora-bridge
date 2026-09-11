import os
import json
import asyncio
from typing import List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
from openai import AsyncOpenAI
import edge_tts

app = FastAPI(title="Syncora Multilingual Sourcing Bridge")
# Safe Groq Client Initialization (Kabhi crash nahi hoga)
groq_key = os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY") or "dummy_key_to_prevent_crash"

client = AsyncOpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=groq_key
)

# Natural Microsoft Neural Voices (Male / Female per Language)
VOICE_MAP = {
    "ur": {"male": "ur-PK-AsadNeural", "female": "ur-PK-UzmaNeural"},
    "zh": {"male": "zh-CN-YunxiNeural", "female": "zh-CN-XiaoxiaoNeural"},
    "en": {"male": "en-US-BrianNeural", "female": "en-US-AvaNeural"},
    "ms": {"male": "ms-MY-OsmanNeural", "female": "ms-MY-YasminNeural"},
    "ar": {"male": "ar-SA-HamedNeural", "female": "ar-SA-ZariyahNeural"},
    "es": {"male": "es-ES-AlvaroNeural", "female": "es-ES-ElviraNeural"},
    "ru": {"male": "ru-RU-DmitryNeural", "female": "ru-RU-SvetlanaNeural"},
    "tr": {"male": "tr-TR-AhmetNeural", "female": "tr-TR-EmelNeural"},
    "de": {"male": "de-DE-ConradNeural", "female": "de-DE-KatjaNeural"},
    "ja": {"male": "ja-JP-KeitaNeural", "female": "ja-JP-NanamiNeural"}
}

LANG_NAMES = {
    "ur": "Urdu",
    "zh": "Mandarin Chinese (Simplified)",
    "en": "English",
    "ms": "Malay (Bahasa Melayu)",
    "ar": "Arabic",
    "es": "Spanish",
    "ru": "Russian",
    "tr": "Turkish",
    "de": "German",
    "ja": "Japanese"
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
async def text_to_speech(text: str, lang: str, gender: str = "female"):
    if not text.strip():
        return Response(content=b"", media_type="audio/mpeg")
    
    prefix = lang[:2].lower()
    gender_clean = gender.lower() if gender.lower() in ["male", "female"] else "female"
    
    lang_voices = VOICE_MAP.get(prefix, VOICE_MAP["en"])
    selected_voice = lang_voices.get(gender_clean, lang_voices["female"])
    
    communicate = edge_tts.Communicate(
        text=text, 
        voice=selected_voice,
        rate="-4%",
        pitch="-1Hz"
    )
    
    mp3_bytes = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_bytes += chunk["data"]
            
    return Response(content=mp3_bytes, media_type="audio/mpeg")

# Ultra-Fast Llama-3 Translation Engine via Groq
async def llm_translate(text: str, src_lang: str, tgt_lang: str) -> str:
    source = LANG_NAMES.get(src_lang[:2].lower(), src_lang)
    target = LANG_NAMES.get(tgt_lang[:2].lower(), tgt_lang)

    system_prompt = (
        f"You are a real-time bilateral business and sourcing interpreter between {source} and {target}. "
        f"Translate the user's spoken input naturally, conversationally, and accurately into {target}. "
        "Do NOT provide explanations, notes, pleasantries, or quotes. Output ONLY the raw translated sentence."
    )

    try:
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            temperature=0.2,
            max_tokens=250
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[Groq LLM Error: {str(e)}]"

@app.websocket("/ws/room")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            
            sender = data.get("sender", "Anonymous")
            gender = data.get("gender", "male")
            src_lang = data.get("source_lang", "ur-PK")
            tgt_lang = data.get("target_lang", "ms-MY")
            original_text = data.get("text", "").strip()

            if not original_text:
                continue

            translated_text = await llm_translate(original_text, src_lang, tgt_lang)

            payload = {
                "sender": sender,
                "gender": gender,
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
    <title>Syncora Sourcing Bridge | Global Edition</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 15px; }
        .container { max-width: 650px; margin: auto; background: #1e293b; padding: 20px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.4); }
        h2 { margin-top: 0; color: #38bdf8; text-align: center; }
        .config-box { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 15px; }
        select, input { padding: 10px; border-radius: 8px; border: 1px solid #475569; background: #334155; color: white; box-sizing: border-box; }
        .full-w { width: 100%; display: flex; gap: 8px; }
        #username { flex: 2; }
        #gender { flex: 1.2; }
        .lang-select { flex: 1; }
        .lang-label { font-size: 11px; color: #94a3b8; margin-bottom: 3px; display: block; }
        .controls { text-align: center; margin: 15px 0; }
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
    <h2>⚡ Syncora Global Bridge</h2>
    
    <div class="config-box">
        <div class="full-w">
            <input type="text" id="username" placeholder="Your Name" value="Ali">
            <select id="gender">
                <option value="male" selected>👨 Male</option>
                <option value="female">👩 Female</option>
            </select>
        </div>

        <div class="full-w">
            <div class="lang-select">
                <span class="lang-label">I Speak (Source):</span>
                <select id="my-lang" style="width: 100%;">
                    <option value="ur-PK" selected>🇵🇰 Urdu</option>
                    <option value="zh-CN">🇨🇳 Chinese (Mandarin)</option>
                    <option value="en-US">🇬🇧 English</option>
                    <option value="ms-MY">🇲🇾 Malay (Malaysia)</option>
                    <option value="ar-SA">🇸🇦 Arabic</option>
                    <option value="es-ES">🇪🇸 Spanish</option>
                    <option value="ru-RU">🇷🇺 Russian</option>
                    <option value="tr-TR">🇹🇷 Turkish</option>
                    <option value="de-DE">🇩🇪 German</option>
                    <option value="ja-JP">🇯🇵 Japanese</option>
                </select>
            </div>

            <div class="lang-select">
                <span class="lang-label">Translate To (Target):</span>
                <select id="target-lang" style="width: 100%;">
                    <option value="ms-MY" selected>🇲🇾 Malay (Malaysia)</option>
                    <option value="zh-CN">🇨🇳 Chinese (Mandarin)</option>
                    <option value="ur-PK">🇵🇰 Urdu</option>
                    <option value="en-US">🇬🇧 English</option>
                    <option value="ar-SA">🇸🇦 Arabic</option>
                    <option value="es-ES">🇪🇸 Spanish</option>
                    <option value="ru-RU">🇷🇺 Russian</option>
                    <option value="tr-TR">🇹🇷 Turkish</option>
                    <option value="de-DE">🇩🇪 German</option>
                    <option value="ja-JP">🇯🇵 Japanese</option>
                </select>
            </div>
        </div>
    </div>

    <div class="controls">
        <button id="mic-btn" onclick="toggleSpeech()">🎤 Push to Speak</button>
    </div>

    <div id="chat-box"></div>
</div>

<script>
    const wsUrl = (window.location.protocol === "https:" ? "wss://" : "ws://") + window.location.host + "/ws/room";
    let socket = new WebSocket(wsUrl);

    socket.onmessage = function(event) {
        const msg = JSON.parse(event.data);
        const chatBox = document.getElementById("chat-box");

        const genderIcon = msg.gender === "female" ? "👩" : "👨";
        const bubble = document.createElement("div");
        bubble.className = "bubble";
        bubble.innerHTML = `
            <div class="sender">${genderIcon} ${msg.sender} (${msg.source_lang} ➔ ${msg.target_lang})</div>
            <div class="orig">${msg.original}</div>
            <div class="trans">👉 <b>${msg.translated}</b></div>
        `;
        chatBox.appendChild(bubble);
        chatBox.scrollTop = chatBox.scrollHeight;

        speakText(msg.translated, msg.target_lang, msg.gender);
    };

    function speakText(text, lang, gender) {
        if (!text || text.startsWith("[Groq LLM Error")) return;
        const url = `/tts?text=${encodeURIComponent(text)}&lang=${encodeURIComponent(lang)}&gender=${encodeURIComponent(gender)}`;
        const audio = new Audio(url);
        audio.play().catch(e => {
            console.log("Audio play error:", e);
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
            const gender = document.getElementById("gender").value;
            const myLang = document.getElementById("my-lang").value;
            const tgtLang = document.getElementById("target-lang").value;

            socket.send(JSON.stringify({
                sender: sender,
                gender: gender,
                source_lang: myLang,
                target_lang: tgtLang,
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
