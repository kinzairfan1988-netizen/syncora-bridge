import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from deep_translator import GoogleTranslator

app = FastAPI()

active_connections = []

def translate_text(text: str, source_lang: str, target_lang: str) -> str:
    try:
        s = "ur" if source_lang.startswith("ur") else ("zh-CN" if source_lang.startswith("zh") else source_lang)
        t = "zh-CN" if target_lang.startswith("zh") else ("ur" if target_lang.startswith("ur") else target_lang)
        return GoogleTranslator(source=s, target=t).translate(text)
    except Exception as e:
        print(f"Translation error: {e}")
        return text

@app.get("/")
async def get_index():
    return FileResponse("index.html")

@app.websocket("/ws/room")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    print(f"User connected. Total in room: {len(active_connections)}")
    
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            
            original_text = payload.get("text", "").strip()
            source_lang = payload.get("source_lang", "ur")
            target_lang = payload.get("target_lang", "zh-CN")
            sender = payload.get("sender", "User")
            
            if original_text:
                translated = translate_text(original_text, source_lang, target_lang)
                
                response_msg = {
                    "sender": sender,
                    "original": original_text,
                    "translated": translated,
                    "source_lang": source_lang,
                    "target_lang": target_lang
                }
                
                for conn in active_connections:
                    await conn.send_text(json.dumps(response_msg))
                    
    except WebSocketDisconnect:
        active_connections.remove(websocket)
        print("User disconnected.")