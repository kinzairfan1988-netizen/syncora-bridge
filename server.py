import os
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types

app = FastAPI()

# CORS Middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Gemini Client
# Ensure GEMINI_API_KEY is set in your Railway environment variables
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

# Gemini Instruction for Real-time Audio Translation & System Control
GEMINI_INSTRUCTION = (
    "You are an advanced real-time voice translation and system control agent. "
    "Your task is to accurately translate incoming audio streams dynamically (such as English to Urdu, "
    "Roman Urdu, or Hindi) and assist in managing system-level operations smoothly and contextually. "
    "Maintain low latency, high accuracy, and natural conversational flow."
)

@app.get("/")
def read_root():
    return {"status": "Server is running successfully on Railway!"}

@app.websocket("/ws/audio")
async def audio_websocket(websocket: WebSocket):
    await websocket.accept()
    
    # Configure Gemini Multimodal Live session with the exact instruction
    config = types.LiveConnectConfig(
        response_modalities=[types.LiveClientConfigResponseModalities.AUDIO],
        system_instruction=types.Content(
            parts=[types.Part.from_text(text=GEMINI_INSTRUCTION)]
        )
    )

    try:
        # Connecting to Gemini Live API
        async with client.aio.live.connect(
            model="gemini-2.0-flash-exp", 
            config=config
        ) as session:
            
            async def receive_from_client():
                """Receives audio chunks from the frontend/mobile browser and sends to Gemini."""
                try:
                    while True:
                        data = await websocket.receive_bytes()
                        await session.send(
                            input=types.LiveClientRealtimeInput(
                                media_chunks=[
                                    types.Blob(
                                        data=data,
                                        mime_type="audio/pcm"
                                    )
                                ]
                            )
                        )
                except WebSocketDisconnect:
                    pass
                except Exception:
                    pass

            async def send_to_client():
                """Receives translated audio response from Gemini and sends it back to the client."""
                try:
                    async for response in session.receive():
                        server_content = response.server_content
                        if server_content and server_content.model_turn:
                            for part in server_content.model_turn.parts:
                                if part.inline_data:
                                    await websocket.send_bytes(part.inline_data.data)
                except Exception:
                    pass

            import asyncio
            # Run both streaming tasks concurrently
            await asyncio.gather(receive_from_client(), send_to_client())

    except WebSocketDisconnect:
        print("Client disconnected from WebSocket.")
    except Exception as e:
        print(f"Error in WebSocket session: {e}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.main(["server:app", "--host", "0.0.0.0", "--port", str(port)])
