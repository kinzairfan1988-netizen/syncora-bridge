import os
import shutil
from fastapi import APIRouter, File, UploadFile, HTTPException

audio_router = APIRouter(prefix="/api", tags=["Audio Module"])

# Ensure uploads directory exists
os.makedirs("uploads", exist_ok=True)

@audio_router.post("/stt")
async def speech_to_text_module(file: UploadFile = File(...)):
    try:
        file_path = os.path.join("uploads", file.filename or "voice.webm")
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        # Yahan aap apna future STT ya Gemini audio processing logic add kar sakte hain
        return {
            "status": "success",
            "text": "voice message note",
            "url": f"/uploads/{file.filename}"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
