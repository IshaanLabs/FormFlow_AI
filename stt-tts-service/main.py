import logging
import os
import tempfile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from stt import transcribe_audio
from tts import text_to_speech

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="STT/TTS Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class TTSRequest(BaseModel):
    text: str
    lang: str = "en"


@app.get("/health")
def health():
    return {"status": "ok", "service": "stt-tts"}


@app.post("/stt")
async def speech_to_text(audio: UploadFile = File(...)):
    """
    Accept an audio file (wav, mp3, m4a, webm) and return the transcript.
    """
    logger.info(f"STT request received: filename={audio.filename}, content_type={audio.content_type}")

    suffix = os.path.splitext(audio.filename or "audio.wav")[1] or ".wav"

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await audio.read()
            tmp.write(content)
            tmp_path = tmp.name
        logger.info(f"Audio saved to temp file: {tmp_path} ({len(content)} bytes)")
    except Exception as e:
        logger.error(f"Failed to save uploaded audio: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save audio: {e}")

    try:
        transcript = transcribe_audio(tmp_path)
        return {"transcript": transcript}
    except Exception as e:
        logger.error(f"STT failed: {e}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
            logger.info(f"Temp audio file cleaned up: {tmp_path}")


@app.post("/tts")
def text_to_speech_endpoint(request: TTSRequest):
    """
    Accept text and return an mp3 audio file.
    """
    logger.info(f"TTS request received: text='{request.text[:60]}', lang={request.lang}")

    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    try:
        audio_path = text_to_speech(request.text, lang=request.lang)
        return FileResponse(
            path=audio_path,
            media_type="audio/mpeg",
            filename="response.mp3",
        )
    except Exception as e:
        logger.error(f"TTS endpoint failed: {e}")
        raise HTTPException(status_code=500, detail=f"TTS failed: {e}")
