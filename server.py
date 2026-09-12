import os
import json
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, FileResponse
import edge_tts

app = FastAPI(title="Syncora Signal Hub")

class RoomHub:
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

    async def broadcast(self, room_id: str, sender: WebSocket, payload: dict):
        if room_id in self.rooms:
            dead_sockets = []
            for client in self.rooms[room_id]:
                # SENDER KO APNA HI MESSAGE KABHI WAPAS NA BHEJEIN
                if client != sender:
                    try:
                        await client.send_text(json.dumps(payload))
                    except Exception:
                        dead_sockets.append(client)
            for d in dead_sockets:
                self.disconnect(room_id, d)

hub = RoomHub()

@app.get("/tts")
async def text_to_speech(text: str):
    clean_text = text.strip()
    if not clean_text:
        return Response(content=b"", media_type="audio/mpeg")
    try:
        communicate = edge_tts.Communicate(text=clean_text, voice="ur-PK-AsadNeural")
        mp3_bytes = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_bytes += chunk["data"]
        return Response(content=mp3_bytes, media_type="audio/mpeg")
    except Exception as e:
        print(f"[TTS Error]: {e}")
        return Response(content=b"", media_type="audio/mpeg")

@app.websocket("/ws/{room_id}")
async def socket_endpoint(websocket: WebSocket, room_id: str):
    await hub.connect(room_id, websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            # Sirf doosre users ko relay karein, bolne wale ko nahi
            await hub.broadcast(room_id, websocket, data)
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
