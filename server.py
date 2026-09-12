import os
import json
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

app = FastAPI(title="Syncora Realtime Relay")

class ConnectionHub:
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

    async def broadcast_text(self, room_id: str, sender: WebSocket, text: str):
        if room_id in self.rooms:
            dead = []
            for client in self.rooms[room_id]:
                if client != sender:
                    try:
                        await client.send_text(text)
                    except Exception:
                        dead.append(client)
            for d in dead:
                self.disconnect(room_id, d)

hub = ConnectionHub()

@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    await hub.connect(room_id, websocket)
    try:
        while True:
            msg = await websocket.receive()
            if "bytes" in msg and msg["bytes"]:
                await hub.broadcast_bytes(room_id, websocket, msg["bytes"])
            elif "text" in msg and msg["text"]:
                await hub.broadcast_text(room_id, websocket, msg["text"])
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
