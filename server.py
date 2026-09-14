import os
import json
import urllib.request
import urllib.parse
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import google.generativeai as genai

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
if GEMINI_KEY:
    try:
        genai.configure(api_key=GEMINI_KEY)
    except Exception as e:
        print(f"[Gemini Config Error]: {e}")

app = FastAPI(title="Syncora Multi-Language & Video Terminal")

class TranslationPayload(BaseModel):
    text: str
    source_lang: str = "ur"
    target_lang: str = "en"

class SystemHub:
    def __init__(self):
        self.rooms: Dict[str, List[WebSocket]] = {}
        self.offline_messages: Dict[str, List[dict]] = {}

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

    async def broadcast_bytes(self, room_id: str, sender: WebSocket, data: bytes):
        if room_id in self.rooms:
            dead = []
            for client in self.rooms[room_id]:
                if client != sender:
                    try:
                        await client.send_bytes(data)
                    except Exception:
                        dead.append(client)
            for d in dead:
                self.disconnect(room_id, d)

    async def broadcast_text(self, room_id: str, sender: WebSocket, payload: dict):
        if payload.get("type") == "text_message":
            if room_id not in self.offline_messages:
                self.offline_messages[room_id] = []
            self.offline_messages[room_id].append({
                "sender": payload.get("sender"),
                "text": payload.get("text"),
                "translated": payload.get("translated", ""),
                "time": payload.get("time", "")
            })

        if room_id in self.rooms:
            dead = []
            for client in self.rooms[room_id]:
                if client != sender:
                    try:
                        await client.send_text(json.dumps(payload))
                    except Exception:
                        dead.append(client)
            for d in dead:
                self.disconnect(room_id, d)

hub = SystemHub()

def direct_translate(text: str, sl: str, tl: str) -> str:
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={sl}&tl={tl}&dt=t&q=" + urllib.parse.quote(text)
        req_obj = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_obj, timeout=4) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data and data[0]:
                translated_parts = [part[0] for part in data[0] if part and part[0]]
                return "".join(translated_parts).strip()
    except Exception as e:
        print(f"[Direct Translate Error]: {e}")
    return text

@app.post("/translate")
async def translate_text(req: TranslationPayload):
    clean_text = req.text.strip()
    if not clean_text:
        return {"translated_text": ""}

    # 1. Bulletproof Direct Translation (Zero Latency & No 404)
    translated = direct_translate(clean_text, req.source_lang, req.target_lang)
    if translated and translated.lower() != clean_text.lower():
        return {"translated_text": translated}

    # 2. Gemini Fallback if available
    if GEMINI_KEY:
        prompt = (
            f"Translate this spoken sentence from language code '{req.source_lang}' "
            f"to language code '{req.target_lang}'. Return ONLY the direct translation:\n\n{clean_text}"
        )
        for m_name in ["gemini-2.0-flash", "gemini-1.5-flash-8b", "gemini-1.5-flash"]:
            try:
                model = genai.GenerativeModel(m_name)
                response = model.generate_content(prompt)
                if response and hasattr(response, "text") and response.text:
                    return {"translated_text": response.text.strip()}
            except Exception as e:
                print(f"[Gemini Error on {m_name}]: {e}")
                continue

    return {"translated_text": translated}

@app.get("/messages/{room_id}")
async def get_saved_messages(room_id: str):
    msgs = hub.offline_messages.get(room_id, [])
    return JSONResponse(content={"messages": msgs})

@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    await hub.connect(room_id, websocket)
    try:
        while True:
            msg = await websocket.receive()
            if "bytes" in msg and msg["bytes"]:
                await hub.broadcast_bytes(room_id, websocket, msg["bytes"])
            elif "text" in msg and msg["text"]:
                payload = json.loads(msg["text"])
                await hub.broadcast_text(room_id, websocket, payload)
    except WebSocketDisconnect:
        hub.disconnect(room_id, websocket)
    except Exception:
        hub.disconnect(room_id, websocket)

@app.get("/")
async def serve_index():
    return FileResponse("index.html")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
