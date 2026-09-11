import os
import json
import asyncio
from typing import List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response, FileResponse
from openai import AsyncOpenAI
import edge_tts

app = FastAPI(title="Syncora Multilingual Voice Bridge")

# Microsoft Neural Voices Map
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
    "zh": "Mandarin Chinese",
    "en": "English",
    "ms": "Malay",
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

# High-Performance Neural Voice Endpoint
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
        rate="-2%",
        pitch="-1Hz"
    )
    
    mp3_bytes = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_bytes += chunk["data"]
            
    return Response(content=mp3_bytes, media_type="audio/mpeg")

# Strict Single-Language Conversational AI Engine with Live Model Discovery & Diagnostics
async def llm_agent_reply(text: str, src_lang: str, tgt_lang: str) -> str:
    raw_key = os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    clean_key = raw_key.strip().strip("'").strip('"')

    if not clean_key or clean_key == "dummy_key":
        return "[Error: GROQ_API_KEY Railway variables mein configure nahi hai]"

    source = LANG_NAMES.get(src_lang[:2].lower(), src_lang)
    target = LANG_NAMES.get(tgt_lang[:2].lower(), tgt_lang)

    system_prompt = (
        f"You are Syncora, an intelligent conversational voice assistant. "
        f"The user spoke to you in {source}. "
        f"CRITICAL RULE: Respond 100% in {target} language only. "
        f"Do NOT use any other language. "
        f"Keep your response concise, polite, and conversational (1 to 2 spoken sentences) in {target}. "
        f"Do NOT include explanations, quotes, notes, or translations."
    )

    groq_client = AsyncOpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=clean_key
    )

    # Fetch active models dynamically from Groq account
    active_models = []
    try:
        models_data = await groq_client.models.list()
        active_models = [m.id for m in models_data.data if "whisper" not in m.id and "guard" not in m.id]
    except Exception as e:
        return f"[Groq Connection Error: {str(e)}]"

    if not active_models:
        active_models = ["llama-3.1-8b-instant", "llama-3.3-70b-versatile"]

    last_error = ""
    for model_name in active_models:
        try:
            response = await groq_client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text}
                ],
                temperature=0.1,
                max_tokens=150
            )
            content = response.choices[0].message.content
            if content and content.strip():
                return content.strip()
        except Exception as err:
            last_error = f"{model_name}: {str(err)}"
            continue

    return f"[Groq LLM Error: {last_error}]"

@app.websocket("/ws/room")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            
            sender = data.get("sender", "Ali")
            gender = data.get("gender", "male")
            src_lang = data.get("source_lang", "ur-PK")
            tgt_lang = data.get("target_lang", "en-US")
            original_text = data.get("text", "").strip()

            if not original_text:
                continue

            reply_text = await llm_agent_reply(original_text, src_lang, tgt_lang)

            payload = {
                "sender": sender,
                "gender": gender,
                "source_lang": src_lang,
                "target_lang": tgt_lang,
                "original": original_text,
                "translated": reply_text
            }
            await manager.broadcast(payload)

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)

@app.get("/")
async def get_index():
    return FileResponse("index.html")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
