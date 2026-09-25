def translate_via_gemini(text: str, target_lang: str) -> str:
    clean = text.strip()
    if not clean:
        return ""
    
    target_lang = target_lang.strip().lower()
    t_lang = target_lang if target_lang in ["ur", "en", "ar", "de", "fr", "es"] else "en"
    
    # Set distinct source and target languages to prevent MyMemory pair errors
    src_lang = "ur" if t_lang == "en" else "en"
    
    try:
        encoded_text = urllib.parse.quote(clean)
        url = f"https://api.mymemory.translated.net/get?q={encoded_text}&langpair={src_lang}|{t_lang}"
        
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            res_body = response.read().decode('utf-8')
            res_data = json.loads(res_body)
            
            matches = res_data.get("responseData", {})
            translated_text = matches.get("translatedText", "").strip()
            
            if translated_text and "WARNING" not in translated_text.upper() and "INVALID" not in translated_text.upper() and "PLEASE SELECT" not in translated_text.upper():
                return translated_text
    except Exception as e:
        print(f"[Translation Engine Error]: {e}")
        
    return clean
