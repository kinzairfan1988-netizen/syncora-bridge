import os
import logging
from google import genai
from google.genai import types

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AudioModule")

class AudioTranslationModule:
    def __init__(self, api_key: str = None):
        """
        Initializes the Gemini API client for independent audio processing and translation.
        """
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            logger.warning("GEMINI_API_KEY environment variable not set.")
        
        # Initialize Gemini client safely
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    def process_and_translate_audio(self, audio_bytes: bytes, target_language: str = "Urdu") -> str:
        """
        Processes audio input bytes and translates them using Gemini model.
        """
        if not self.client:
            return "Gemini client is not initialized. Please check your API key."

        try:
            logger.info(f"Processing audio stream for translation to {target_language} via Gemini...")
            
            response = self.client.models.generate_content(
                model='gemini-1.5-flash',
                contents=[
                    types.Part.from_bytes(
                        data=audio_bytes,
                        mime_type='audio/webm',
                    ),
                    f"Listen to this audio carefully. Transcribe it and translate it accurately into {target_language}."
                ]
            )
            
            translated_text = response.text
            logger.info("Audio translation completed successfully.")
            return translated_text

        except Exception as e:
            logger.error(f"Error during audio processing: {str(e)}")
            return f"Audio processing failed: {str(e)}"

# Standalone helper function called by server.py
def handle_audio_stream(audio_data: bytes, target_lang: str = "Urdu") -> str:
    module = AudioTranslationModule()
    return module.process_and_translate_audio(audio_data, target_lang)

if __name__ == "__main__":
    print("Audio Module is stable and ready.")
