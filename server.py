import re

def is_urdu_or_arabic(text: str) -> bool:
    return bool(re.search(r'[\u0600-\u06FF]', text))

def translate_via_google(text: str, source: str, target: str) -> str:
    try:
        encoded = urllib.parse.quote(text.strip().encode('utf-8'))
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={source}&tl={target}&dt=t&q={encoded}"
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            res_json = json.loads(response.read().decode('utf-8'))
            if res_json and isinstance(res_json, list) and len(res_json) > 0 and res_json[0]:
                out = "".join([part[0] for part in res_json[0] if part and part[0]]).strip()
                if out:
                    return out
    except Exception as e:
        print(f"[Google GTX Error]: {e}")
    return ""

@app.post("/translate")
async def translate_text(req: TranslationRequest):
    clean = req.text.strip()
    if not clean:
        return {"translated_text": ""}

    target_lang = req.target_lang.strip().lower()
    has_script = is_urdu_or_arabic(clean)

    # 1. PEHLA ATTEMPT: Gemini AI (Agar key mojood hai)
    if GEMINI_KEY:
        for model_name in ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]:
            try:
                model = genai.GenerativeModel(model_name)
                prompt = (
                    f"Translate the following text into language code '{target_lang}'.\n"
                    f"- Note: The text might be in Roman Urdu (Urdu written in English alphabets like 'ap kaisy hain'), Urdu script, or English.\n"
                    f"- If input is Roman Urdu or Urdu script and target is 'en', translate to natural English.\n"
                    f"- If input is English and target is 'ur', translate to natural Urdu script.\n"
                    f"Return ONLY the translated sentence, without any explanations or quotation marks:\n\n{clean}"
                )
                response = model.generate_content(prompt)
                if response and hasattr(response, "text") and response.text:
                    out = response.text.strip().replace('"', '').replace("'", "")
                    if out and out.lower() != clean.lower():
                        return {"translated_text": out}
            except Exception as e:
                print(f"[Gemini Exception {model_name}]: {e}")
                continue

    # 2. DOOSRA ATTEMPT: Google Translate Engine
    # Agar Urdu script hai toh source 'ur' rakhein, warna 'auto'
    source_guess = "ur" if has_script else "auto"
    g_res = translate_via_google(clean, source_guess, target_lang)
    if g_res and g_res.lower() != clean.lower():
        return {"translated_text": g_res}

    # Agar target English hai aur Roman Urdu auto detect nahi hui
    if target_lang == "en":
        g_res_ur = translate_via_google(clean, "ur", "en")
        if g_res_ur and g_res_ur.lower() != clean.lower():
            return {"translated_text": g_res_ur}

    # 3. TEESRA ATTEMPT: Common Roman-Urdu & English Essential Dictionary
    local_dict = {
        # Roman Urdu / Urdu -> English
        "ap kaisy hain": "How are you?",
        "aap kaise hain": "How are you?",
        "aap kaise ho": "How are you?",
        "kya hal hai": "How are you?",
        "kya ho raha hai": "What is happening?",
        "main theek hoon": "I am fine.",
        "shukriya": "Thank you.",
        "آپ کیسے ہیں": "How are you?",
        "آپ کیسے ہو": "How are you?",
        "کیا حال ہے": "How are you?",
        "کیا کر رہے ہیں": "What are you doing?",
        # English -> Urdu
        "how are you": "آپ کیسے ہیں؟",
        "what are you doing": "آپ کیا کر رہے ہیں؟",
        "where are you": "آپ کہاں ہیں؟",
        "i am fine": "میں ٹھیک ہوں۔",
        "thank you": "شکریہ۔",
        "hello": "ہیلو",
        "good morning": "صبح بخیر"
    }

    norm_key = re.sub(r'[^\w\s]', '', clean.lower()).strip()
    if norm_key in local_dict:
        return {"translated_text": local_dict[norm_key]}

    # Agar koi translation na ho sake toh saaf batayein ke translation unavailable hai
    return {"translated_text": f"[{clean}]"}
