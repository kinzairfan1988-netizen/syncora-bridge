import os
import json
import urllib.request
import urllib.parse
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(title="Syncora - Isolated Text Translation Module")

class TranslationRequest(BaseModel):
    text: str
    target_lang: str = "en"

def translate_text_engine(text: str, target_lang: str) -> str:
    clean = text.strip()
    if not clean:
        return ""
    
    target_lang = target_lang.strip().lower()
    print(f"[DEBUG] Received target_lang from frontend: '{target_lang}'")
    
    # Secure language mapping for all supported options
    lang_mapping = {
        "en": "en",
        "ur": "ur",
        "ar": "ar",
        "de": "de",
        "fr": "fr",
        "es": "es",
        "zh": "zh-CN",
        "zh-cn": "zh-CN",
        "chinese": "zh-CN"
    }
    
    t_lang = lang_mapping.get(target_lang, "en")
    print(f"[DEBUG] Mapped target language for Google GTX: '{t_lang}'")
    
    try:
        encoded_text = urllib.parse.quote(clean)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={t_lang}&dt=t&q={encoded_text}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=6) as response:
            res_body = response.read().decode('utf-8')
            res_data = json.loads(res_body)
            if res_data and isinstance(res_data, list) and len(res_data) > 0:
                translated_sentences = [s[0] for s in res_data[0] if s and s[0]]
                translated_text = "".join(translated_sentences).strip()
                if translated_text:
                    return translated_text
    except Exception as e:
        print(f"[Translation Error]: {e}")
        
    return clean

@app.post("/translate")
async def translate_endpoint(req: TranslationRequest):
    try:
        translated = translate_text_engine(req.text, req.target_lang)
        return {"status": "success", "original": req.text, "target_lang": req.target_lang, "translated_text": translated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def root():
    return {"status": "Syncora Text Translation Module is running successfully!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server_text_test:app", host="0.0.0.0", port=8000, reload=True)
