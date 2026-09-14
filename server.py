import re

def is_urdu_script(text: str) -> bool:
    # Check if string contains Arabic/Urdu Unicode characters
    return bool(re.search(r'[\u0600-\u06FF]', text))

@app.post("/translate")
async def translate_text(req: TranslationRequest):
    clean = req.text.strip()
    if not clean:
        return {"translated_text": ""}

    target_lang = req.target_lang

    # Auto-swap target agar user ne ghalti se same language select kar li ho
    has_urdu = is_urdu_script(clean)
    if not has_urdu and clean.isascii() and target_lang == "en":
        # Check if it looks like English text (common English words)
        english_indicators = ["what", "how", "are", "you", "doing", "is", "the", "hello", "hi", "where", "why"]
        words = clean.lower().split()
        if any(w in english_indicators for w in words):
            target_lang = "ur"  # English text ko Urdu mein translate karein

    # 1. Gemini AI Translation (Best for Urdu Script, Roman Urdu & English)
    if GEMINI_KEY:
        for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
            try:
                model = genai.GenerativeModel(model_name)
                prompt = (
                    f"Translate the following text into target language code '{target_lang}'.\n"
                    f"- If the input is in English, translate it to '{target_lang}'.\n"
                    f"- If the input is in Urdu or Roman Urdu, translate it to '{target_lang}'.\n"
                    f"Return ONLY the direct translation, nothing else:\n\n{clean}"
                )
                resp = model.generate_content(prompt)
                if resp and hasattr(resp, "text") and resp.text:
                    out = resp.text.strip().replace('"', '').replace("'", "")
                    if out and out.lower() != clean.lower():
                        return {"translated_text": out}
            except Exception as e:
                print(f"[Gemini fallback]: {e}")
                continue

    # 2. Google Translate Direct Fallback with proper UTF-8 handling
    try:
        source_param = "ur" if has_urdu else "auto"
        encoded_query = urllib.parse.quote(clean.encode('utf-8'))
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={source_param}&tl={target_lang}&dt=t&q={encoded_query}"
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
        print(f"[Google Translate API error]: {e}")

    # 3. Built-in direct common dictionary fallback
    dict_map = {
        "ap kaisy hain": "How are you?",
        "aap kaise ho": "How are you?",
        "آپ کیسے ہیں": "How are you?",
        "what are you doing": "آپ کیا کر رہے ہیں؟",
        "kya kar rahe ho": "What are you doing?",
        "theek": "Fine",
        "shukriya": "Thank you"
    }
    key = clean.lower().strip("?.! ")
    if key in dict_map:
        return {"translated_text": dict_map[key]}

    return {"translated_text": clean}
