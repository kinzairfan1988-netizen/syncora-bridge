import os
import json
import asyncio
import re
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response, FileResponse
from openai import AsyncOpenAI
import edge_tts

app = FastAPI(title="Syncora Call Bridge")

VOICE_MAP = {
    "ur": {"male": "ur-PK-AsadNeural", "female": "ur-PK-UzmaNeural"},
    "en": {"male": "en-US-BrianNeural", "female": "en-US-AvaNeural"},
    "ms": {"male": "ms-MY-OsmanNeural", "female": "ms-MY-YasminNeural"},
    "zh": {"male": "zh-CN-YunxiNeural", "female": "zh-CN-XiaoxiaoNeural"},
    "ar": {"male": "ar-SA-HamedNeural", "female": "ar-SA-ZariyahNeural"}
}

LANG_MAP = {
    "ur": "Urdu",
    "en": "English",
    "ms": "Malay",
    "zh": "Chinese",
    "ar": "Arabic"
}

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
async def text_to_speech(text: str, lang: str = "en", gender: str = "female"):
    if not text.strip():
        return Response(content=b"", media_type="audio/mpeg")
    
    prefix = (lang or "en").split("-")[0].lower()
    gender_clean = gender.lower() if gender.lower() in ["male", "female"] else "female"
    
    lang_voices = VOICE_MAP.get(prefix, VOICE_MAP["en"])
    selected_voice = lang_voices.get(gender_clean, lang_voices["female"])
    
    print(f"[TTS ACTIVE] Voice: {selected_voice} | Lang: {prefix} | Saying: {text}")
    
    communicate = edge_tts.Communicate(
        text=text, 
        voice=selected_voice,
        rate="+0%",
        pitch="+0Hz"
    )
    
    mp3_bytes = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_bytes += chunk["data"]
            
    return Response(content=mp3_bytes, media_type="audio/mpeg")

async def pure_translate(text: str, src_code: str, tgt_code: str) -> str:
    raw_key = os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    clean_key = raw_key.strip().strip("'").strip('"')

    if not clean_key or clean_key == "dummy_key":
        return text

    src_prefix = src_code.split("-")[0].lower()
    tgt_prefix = tgt_code.split("-")[0].lower()

    target_lang = LANG_MAP.get(tgt_prefix, "English")
    source_lang = LANG_MAP.get(src_prefix, "Urdu")

    print(f"[RECV INPUT] '{text}' (Claimed source: {source_lang} -> Target: {target_lang})")

    groq_client = AsyncOpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=clean_key
    )

    try:
        response = await groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"Translate this spoken sentence from {source_lang} to {target_lang}. "
                        f"Output ONLY the translated sentence in {target_lang}. "
                        f"CRITICAL: Do NOT write Arabic words or letters. Only {target_lang}."
                    )
                },
                {"role": "user", "content": text}
            ],
            temperature=0.0,
            max_tokens=80
        )
        content = response.choices[0].message.content
        if content and content.strip():
            clean = re.sub(r'^(Translation:|Output:|"|\')', "", content.strip(), flags=re.IGNORECASE).strip().strip('"')
            print(f"[TRANSLATED CLEAN] '{clean}'")
            return clean
    except Exception as e:
        print(f"[ERROR IN GROQ] {e}")

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

            if not original_text or len(original_text) < 2:
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
