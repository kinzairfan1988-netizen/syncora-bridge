import os
import json
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

app = FastAPI(title="Syncora Call Signaling Hub")

class CallHub:
    def __init__(self):
        # room_id -> list of connected websockets
        self.rooms: Dict[str, List[WebSocket]] = {}

    async def connect(self, room_id: str, websocket: WebSocket):
        await websocket.accept()
        if room_id not in self.rooms:
            self.rooms[room_id] = []
        self.rooms[room_id].append(websocket)
        print(f"[Hub] Client connected to room: {room_id}. Total: {len(self.rooms[room_id])}")

    def disconnect(self, room_id: str, websocket: WebSocket):
        if room_id in self.rooms:
            if websocket in self.rooms[room_id]:
                self.rooms[room_id].remove(websocket)
            if not self.rooms[room_id]:
                del self.rooms[room_id]
        print(f"[Hub] Client left room: {room_id}")

    async def relay_signal(self, room_id: str, sender_ws: WebSocket, message: dict):
        if room_id in self.rooms:
            dead_sockets = []
            for client in self.rooms[room_id]:
                if client != sender_ws:  # Doosre bande ko signal forward karein
                    try:
                        await client.send_text(json.dumps(message))
                    except Exception:
                        dead_sockets.append(client)
            for d in dead_sockets:
                self.disconnect(room_id, d)

hub = CallHub()

@app.websocket("/ws/{room_id}")
async def call_websocket(websocket: WebSocket, room_id: str):
    await hub.connect(room_id, websocket)
    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            # WebRTC offer, answer, ice-candidate, ya hangup signal forward karein
            await hub.relay_signal(room_id, websocket, data)
    except WebSocketDisconnect:
        hub.disconnect(room_id, websocket)
    except Exception as e:
        print(f"[Hub Err] {e}")
        hub.disconnect(room_id, websocket)

@app.get("/")
async def serve_index():
    return FileResponse("index.html")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
