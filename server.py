import os
import json
import asyncio
from typing import List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response, FileResponse
from openai import AsyncOpenAI
import edge_tts

app = FastAPI(title="Syncora Multilingual Sourcing Bridge")

# Groq Client Initialization
groq_key = os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY") or "dummy_key"

client = AsyncOpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=groq_key
)

# Natural Microsoft Neural Voices
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

async def llm_translate(text: str, src_lang: str, tgt_lang: str) -> str:
    source = LANG_NAMES.get(src_lang[:2].lower(), src_lang)
    target = LANG_NAMES.get(tgt_lang[:2].lower(), tgt_lang)

    system_prompt = (
        f"You are a real-time bilateral business and sourcing interpreter between {source} and {target}. "
        f"Translate the user's spoken input naturally, conversationally, and accurately into {target}. "
        "Do NOT provide explanations, notes, pleasantries, or quotes. Output ONLY the raw translated sentence."
    )

    models_to_try = ["llama-3.1-8b-instant", "llama3-8b-8192"]
    last_error = ""

    for model_name in models_to_try:
        try:
            response = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text}
                ],
                temperature=0.2,
                max_tokens=250
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            last_error = str(e)
            continue

    return f"[Groq LLM Error: {last_error}]"

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

@app.get("/")
async def get_index():
    return FileResponse("index.html")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
