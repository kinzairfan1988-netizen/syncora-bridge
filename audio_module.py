from fastapi import APIRouter, File, UploadFile
import os
import shutil

# Ek bilkul alag router taake audio ka code main code mein mix na ho
audio_router = APIRouter(prefix="/audio", tags=["Audio Module"])

AUDIO_DIR = "isolated_audio"
os.makedirs(AUDIO_DIR, exist_ok=True)

@audio_router.post("/upload")
async def handle_isolated_audio(file: UploadFile = File(...)):
    try:
        file_path = os.path.join(AUDIO_DIR, file.filename or "voice_note.webm")
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Yeh bilkul clean response dega bina server crash kiye
        return {
            "status": "success",
            "message": "Audio safely stored in isolated module",
            "audio_url": f"/{AUDIO_DIR}/{file.filename or 'voice_note.webm'}"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
