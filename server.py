import os
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from google import genai
from google.genai import types

app = FastAPI()

# Initialize Gemini Client
# Make sure GEMINI_API_KEY is set in your environment variables
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# Store active connections
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections in self.active_connections and self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

@app.get("/")
async def get():
    return HTMLResponse("<h3>Real-time Audio Translation Calling App is Running</h3>")

@app.websocket("/ws/audio")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Receive audio data or text packet from client
            data = await websocket.receive_bytes()
            
            # Example: Processing audio chunks or text with Gemini API for translation
            # You can adjust the prompt based on whether you are sending raw audio or transcribed text
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[
                    "Translate the incoming audio/text context to English/Urdu/Roman Urdu as configured:",
                    types.Part.from_bytes(
                        data=data,
                        mime_type="audio/webm", # Update mime_type according to your frontend recording format (e.g., audio/wav, audio/webm)
                    ),
                ]
            )
            
            translated_text = response.text if response and response.text else "Translation pending..."
            
            # Send back the translated result to the client
            await websocket.send_text(translated_text)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast("A user disconnected.")
    except Exception as e:
        print(f"Error occurred: {e}")
        manager.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
