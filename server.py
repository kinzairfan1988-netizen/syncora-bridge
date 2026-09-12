import os
import json
import asyncio
import re
import urllib.request
import urllib.error
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response, FileResponse
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
        print(f"[WS] User joined room {room_id}. Total: {len(self.rooms[room_id])}")

    def disconnect(self, room_id: str, websocket: WebSocket):
        if room_id in self.rooms:
            if websocket in self.rooms[room_id]:
                self.rooms[room_id].remove(websocket)
            if not self.rooms[room_id]:
                del self.rooms[room_id]
        print(f"[WS] User left room {room_id}")

    async def broadcast(self, room_id: str, message: dict):
        if room_id in self.rooms:
            dead_sockets = []
            for connection in self.rooms[room_id]:
                try:
                    await connection.send_text(json.dumps(message))
                except Exception:
                    dead_sockets.append(connection)
            for d in dead_sockets:
                self.disconnect(room_id, d)

manager = RoomManager()

@app.get("/tts")
async def text_to_speech(text: str, lang: str = "en", gender: str = "female"):
    if not text.strip() or text.startswith("[Error:"):
        return Response(content=b"", media_type="audio/mpeg")
    
    prefix = (lang or "en").split("-")[0].lower()
    gender_clean = gender.lower() if gender.lower() in ["male", "female"] else "female"
    
    lang_voices = VOICE_MAP.get(prefix, VOICE_MAP["en"])
    selected_voice = lang_voices.get(gender_clean, lang_voices["female"])
    
    try:
        communicate = edge_tts.Communicate(text=text, voice=selected_voice)
        mp3_bytes = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_bytes += chunk["data"]
        return Response(content=mp3_bytes, media_type="audio/mpeg")
    except Exception as e:
        print(f"[TTS ERR] {e}")
        return Response(content=b"", media_type="audio/mpeg")

def call_gemini_api(endpoint: str, payload: dict, api_key: str):
    req = urllib.request.Request(
        f"{endpoint}?key={api_key}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.read().decode("utf-8")

async def pure_translate(text: str, src_code: str, tgt_code: str) -> str:
    raw_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    clean_key = raw_key.strip().strip("'").strip('"')

    if not clean_key:
        return "[Error: GEMINI_API_KEY missing on Railway]"

    src_prefix = src_code.split("-")[0].lower()
    tgt_prefix = tgt_code.split("-")[0].lower()

    target_lang = LANG_MAP.get(tgt_prefix, "English")
    source_lang = LANG_MAP.get(src_prefix, "Urdu")

    prompt = (
        f"You are a fast verbal translator. Translate this text from {source_lang} to {target_lang}. "
        f"Output ONLY the translated sentence in {target_lang}. Never output quotes or explanation.\n\n"
        f"Text: {text}"
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 100}
    }

    # Standard endpoints
    models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    for m in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
        try:
            res_text = await asyncio.to_thread(call_gemini_api, url, payload, clean_key)
            data = json.loads(res_text)
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    clean = parts[0].get("text", "").strip()
                    clean = re.sub(r'^(Translation:|Output:|"|\')', "", clean, flags=re.IGNORECASE).strip().strip('"')
                    return clean
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8")
            print(f"[GEMINI FAIL {m}] {err_body}")
            continue
        except Exception as e:
            print(f"[GEMINI ERR {m}] {e}")
            continue

    return f"[Error: Translation failed]"

@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    await manager.connect(room_id, websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)

            sender_id = data.get("sender_id", "")
            sender_name = data.get("sender_name", "Caller")
            gender = data.get("gender", "male")
            src_lang = data.get("source_lang", "ur-PK")
            tgt_lang = data.get("target_lang", "en-US")
            text = data.get("text", "").strip()

            if not text:
                continue

            translated = await pure_translate(text, src_lang, tgt_lang)

            await manager.broadcast(room_id, {
                "sender_id": sender_id,
                "sender_name": sender_name,
                "gender": gender,
                "source_lang": src_lang,
                "target_lang": tgt_lang,
                "original": text,
                "translated": translated
            })
    except WebSocketDisconnect:
        manager.disconnect(room_id, websocket)
    except Exception as e:
        print(f"[WS ERR] {e}")
        manager.disconnect(room_id, websocket)

@app.get("/")
async def get_index():
    return FileResponse("index.html")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
