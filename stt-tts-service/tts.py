import logging
import os
import uuid
from gtts import gTTS

logger = logging.getLogger(__name__)

TTS_OUTPUT_DIR = "/tmp/tts_output"
os.makedirs(TTS_OUTPUT_DIR, exist_ok=True)


def text_to_speech(text: str, lang: str = "en") -> str:
    try:
        logger.info(f"Generating TTS for text: '{text[:60]}...' in lang={lang}")
        output_path = os.path.join(TTS_OUTPUT_DIR, f"{uuid.uuid4()}.mp3")
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.save(output_path)
        logger.info(f"TTS audio saved to: {output_path}")
        return output_path
    except Exception as e:
        logger.error(f"TTS generation failed: {e}")
        raise
