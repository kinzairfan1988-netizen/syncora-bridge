def translate_text_engine(text: str, target_lang: str) -> str:
    clean = text.strip()
    if not clean:
        return ""
    
    target_lang = target_lang.strip().lower()
    
    # Accurate mapping for all target languages including Chinese
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
    
    # Use auto-detection safely for all languages
    sl_lang = "auto"
    
    try:
        encoded_text = urllib.parse.quote(clean)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={sl_lang}&tl={t_lang}&dt=t&q={encoded_text}"
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
