import os
import json
import asyncio
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response, FileResponse
from openai import AsyncOpenAI
import edge_tts

app = FastAPI(title="Syncora Call Bridge")

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

# Clean language mapping dictionary
LANG_NAMES = {
    "ur": "Urdu",
    "en": "English",
    "ms": "Malay (Bahasa Melayu)",
    "zh": "Mandarin Chinese",
    "ar": "Arabic",
    "es": "Spanish",
    "ru": "Russian",
    "tr": "Turkish",
    "de": "German",
    "ja": "Japanese"
}

def resolve_lang(code: str) -> str:
    prefix = (code or "en").split("-")[0].lower()
    return LANG_NAMES.get(prefix, "English")

class RoomManager:
    def __init__(self):
        self.rooms: Dict[str, List[WebSocket]] = {}

    async def connect(self, room_id: str, websocket: WebSocket):
        await websocket.accept()
        if room_id not in self.rooms:
            self.rooms[room_id] = []
        self.rooms[room_id].append(websocket)

    def disconnect(self, room_id: str, websocket: WebSocket):
        if room_id in self.rooms:
            if websocket in self.rooms[room_id]:
                self.rooms[room_id].remove(websocket)
            if not self.rooms[room_id]:
                del self.rooms[room_id]

    async def broadcast(self, room_id: str, message: dict):
        if room_id in self.rooms:
            for connection in self.rooms[room_id]:
                try:
                    await connection.send_text(json.dumps(message))
                except Exception:
                    pass

manager = RoomManager()

@app.get("/tts")
async def text_to_speech(text: str, lang: str, gender: str = "female"):
    if not text.strip():
        return Response(content=b"", media_type="audio/mpeg")
    
    prefix = (lang or "en").split("-")[0].lower()
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

async def pure_translate(text: str, src_lang: str, tgt_lang: str) -> str:
    raw_key = os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    clean_key = raw_key.strip().strip("'").strip('"')

    if not clean_key or clean_key == "dummy_key":
        return text

    source = resolve_lang(src_lang)
    target = resolve_lang(tgt_lang)

    # Bulletproof prompt with strict anti-Arabic leak rule
    system_prompt = (
        f"You are a professional language translator.\n"
        f"Your ONLY task is to translate the user input from {source} into {target}.\n"
        f"RULES:\n"
        f"1. You MUST output ONLY the translated text in {target}.\n"
        f"2. DO NOT output Arabic unless the target language is explicitly Arabic.\n"
        f"3. DO NOT answer questions or chat. ONLY translate the sentence.\n"
        f"4. Do NOT include pronunciation, notes, or quotes."
    )

    groq_client = AsyncOpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=clean_key
    )

    # Discover active models dynamically
    active_models = []
    try:
        models_data = await groq_client.models.list()
        active_models = [m.id for m in models_data.data if "whisper" not in m.id and "guard" not in m.id]
    except Exception:
        pass

    if not active_models:
        active_models = ["llama-3.1-8b-instant", "llama-3.3-70b-versatile"]

    for model_name in active_models:
        try:
            response = await groq_client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Translate this into {target}: {text}"}
                ],
                temperature=0.0,
                max_tokens=200
            )
            content = response.choices[0].message.content
            if content and content.strip():
                return content.strip()
        except Exception:
            continue

    return text

@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    await manager.connect(room_id, websocket)
    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            
            sender_id = data.get("sender_id", "")
            sender_name = data.get("sender_name", "Caller")
            gender = data.get("gender", "male")
            src_lang = data.get("source_lang", "ur-PK")
            tgt_lang = data.get("target_lang", "en-US")
            original_text = data.get("text", "").strip()

            if not original_text:
                continue

            translated = await pure_translate(original_text, src_lang, tgt_lang)

            payload = {
                "sender_id": sender_id,
                "sender_name": sender_name,
                "gender": gender,
                "source_lang": src_lang,
                "target_lang": tgt_lang,
                "original": original_text,
                "translated": translated
            }
            await manager.broadcast(room_id, payload)

    except WebSocketDisconnect:
        manager.disconnect(room_id, websocket)
    except Exception:
        manager.disconnect(room_id, websocket)

@app.get("/")
async def get_index():
    return FileResponse("index.html")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
