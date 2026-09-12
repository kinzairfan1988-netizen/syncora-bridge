import os
import json
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

app = FastAPI(title="Syncora Signal & Inbox Hub")

class SystemHub:
    def __init__(self):
        # room_id -> active websocket connections
        self.rooms: Dict[str, List[WebSocket]] = {}
        # room_id -> list of saved offline messages
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
        # Agar text message hai to history mein save karein taake offline banda aakar dekh sake
        if payload.get("type") == "text_message":
            if room_id not in self.offline_messages:
                self.offline_messages[room_id] = []
            self.offline_messages[room_id].append({
                "sender": payload.get("sender"),
                "text": payload.get("text"),
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

@app.get("/messages/{room_id}")
async def get_saved_messages(room_id: str):
    """Jab dost link open karega to uske phone number line ke saray purane messages usay mil jayenge"""
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
