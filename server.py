import os
import json
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import google.generativeai as genai

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

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

@app.post("/translate")
async def translate_text(req: TranslationPayload):
    clean_text = req.text.strip()
    if not clean_text:
        return {"translated_text": ""}

    if not GEMINI_KEY:
        return {"translated_text": clean_text, "note": "GEMINI_API_KEY missing"}

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = (
            f"You are a real-time conversational translator. Translate this spoken sentence "
            f"from language code '{req.source_lang}' to language code '{req.target_lang}'. "
            f"Return ONLY the direct translation without explanation, quotes, or conversational filler:\n\n"
            f"{clean_text}"
        )
        response = model.generate_content(prompt)
        translated = response.text.strip() if response and response.text else clean_text
        return {"translated_text": translated}
    except Exception as e:
        print(f"[Gemini Error]: {e}")
        return {"translated_text": clean_text}

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
