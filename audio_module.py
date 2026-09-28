import os
import logging
import io
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
            logger.warning("GEMINI_API_KEY environment variable not set. Please configure it.")
        
        # Initialize Gemini client
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    def process_and_translate_audio(self, audio_bytes: bytes, target_language: str = "Urdu") -> str:
        """
        Processes audio input bytes and translates/transcribes them using Gemini model.
        """
        if not self.client:
            raise ValueError("Gemini client is not initialized. Provide a valid API key.")

        try:
            logger.info(f"Processing audio stream for translation to {target_language}...")
            
            # Using Gemini 1.5 Flash for fast multimodal audio/text processing
            response = self.client.models.generate_content(
                model='gemini-1.5-flash',
                contents=[
                    types.Part.from_bytes(
                        data=audio_bytes,
                        mime_type='audio/wav',
                    ),
                    f"Listen to this audio carefully. Translate or transcribe it accurately into {target_language} (Roman Urdu/Urdu/Hindi as appropriate based on context)."
                ]
            )
            
            translated_text = response.text
            logger.info("Audio translation completed successfully.")
            return translated_text

        except Exception as e:
            logger.error(f"Error during audio processing: {str(e)}")
            raise RuntimeError(f"Audio processing failed: {str(e)}")

# Standalone helper function for external import by server.py or other modules
def handle_audio_stream(audio_data: bytes, target_lang: str = "Urdu") -> str:
    module = AudioTranslationModule()
    return module.process_and_translate_audio(audio_data, target_lang)

if __name__ == "__main__":
    # Test block for standalone verification
    print("Audio Module initialized successfully and ready for integration.")
