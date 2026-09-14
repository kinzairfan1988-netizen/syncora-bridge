@app.post("/translate")
async def translate_text(req: TranslationRequest):
    clean = req.text.strip()
    if not clean:
        return {"translated_text": ""}

    target_lang = req.target_lang.strip().lower()

    # 1. Gemini Engine (Urdu script, Roman Urdu, English har tarah ke text ke liye)
    if GEMINI_KEY:
        for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
            try:
                model = genai.GenerativeModel(model_name)
                prompt = (
                    f"Translate the following text strictly into target language '{target_lang}'. "
                    f"If the text is English, translate it to '{target_lang}'. "
                    f"If the text is Urdu or Roman Urdu, translate it to '{target_lang}'. "
                    f"Output ONLY the translated text, nothing else:\n\n{clean}"
                )
                resp = model.generate_content(prompt)
                if resp and hasattr(resp, "text") and resp.text:
                    out = resp.text.strip().replace('"', '').replace("'", "")
                    if out:
                        return {"translated_text": out}
            except Exception as e:
                print(f"[Gemini Error]: {e}")
                continue

    # 2. Google Translate Direct (UTF-8 Encoded)
    try:
        encoded_query = urllib.parse.quote(clean.encode('utf-8'))
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_lang}&dt=t&q={encoded_query}"
        req_obj = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req_obj, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if data and data[0]:
                out = "".join([part[0] for part in data[0] if part and part[0]]).strip()
                if out:
                    return {"translated_text": out}
    except Exception as e:
        print(f"[Google Translate Fallback Error]: {e}")

    return {"translated_text": clean}
