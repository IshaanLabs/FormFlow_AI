import logging
import whisper

logger = logging.getLogger(__name__)

_model = None


def load_model():
    global _model
    if _model is None:
        logger.info("Loading Whisper small model...")
        try:
            _model = whisper.load_model("small")
            logger.info("Whisper small model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            raise
    return _model


def transcribe_audio(audio_path: str) -> str:
    try:
        model = load_model()
        logger.info(f"Transcribing audio file: {audio_path}")
        result = model.transcribe(audio_path)
        transcript = result["text"].strip()
        logger.info(f"Transcription result: {transcript}")
        return transcript
    except Exception as e:
        logger.error(f"Transcription failed for {audio_path}: {e}")
        raise
