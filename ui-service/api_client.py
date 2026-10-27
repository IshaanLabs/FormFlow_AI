import logging
import httpx

logger = logging.getLogger(__name__)

AGENT_BASE = "http://localhost:8002"
STT_TTS_BASE = "http://localhost:8001"


def extract_fields(file_bytes: bytes, filename: str, content_type: str) -> dict:
    """Upload form to agent service and get session + fields back."""
    try:
        logger.info(f"Calling agent /extract-fields: filename={filename}")
        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                f"{AGENT_BASE}/extract-fields",
                files={"form": (filename, file_bytes, content_type)},
            )
        response.raise_for_status()
        data = response.json()
        logger.info(f"Fields extracted: total={data['total_fields']} session={data['session_id']}")
        return data
    except httpx.HTTPStatusError as e:
        logger.error(f"Agent extract-fields error: {e.response.status_code} {e.response.text}")
        raise Exception(f"Agent error: {e.response.json().get('detail', str(e))}")
    except Exception as e:
        logger.error(f"extract_fields failed: {e}")
        raise


def submit_answer(session_id: str, field_label: str, answer: str) -> dict:
    """Submit an answer for the current field."""
    try:
        logger.info(f"Submitting answer: session={session_id} field='{field_label}' answer='{answer}'")
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{AGENT_BASE}/submit-answer",
                json={"session_id": session_id, "field_label": field_label, "answer": answer},
            )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"submit_answer error: {e.response.text}")
        raise Exception(f"Agent error: {e.response.json().get('detail', str(e))}")
    except Exception as e:
        logger.error(f"submit_answer failed: {e}")
        raise


def update_answer(session_id: str, field_label: str, new_answer: str) -> dict:
    """Correct a previously submitted answer."""
    try:
        logger.info(f"Updating answer: session={session_id} field='{field_label}' new='{new_answer}'")
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{AGENT_BASE}/update-answer",
                json={"session_id": session_id, "field_label": field_label, "new_answer": new_answer},
            )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"update_answer error: {e.response.text}")
        raise Exception(f"Agent error: {e.response.json().get('detail', str(e))}")
    except Exception as e:
        logger.error(f"update_answer failed: {e}")
        raise


def generate_pdf(session_id: str) -> bytes:
    """Generate and return the filled PDF bytes."""
    try:
        logger.info(f"Generating PDF: session={session_id}")
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{AGENT_BASE}/generate-pdf",
                params={"session_id": session_id},
            )
        response.raise_for_status()
        logger.info(f"PDF received: {len(response.content)} bytes")
        return response.content
    except httpx.HTTPStatusError as e:
        logger.error(f"generate_pdf error: {e.response.text}")
        raise Exception(f"Agent error: {e.response.json().get('detail', str(e))}")
    except Exception as e:
        logger.error(f"generate_pdf failed: {e}")
        raise


def get_tts_audio(text: str, lang: str = "en") -> bytes:
    """Call TTS service and return mp3 bytes."""
    try:
        logger.info(f"TTS request: text='{text[:60]}' lang={lang}")
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{STT_TTS_BASE}/tts",
                json={"text": text, "lang": lang},
            )
        response.raise_for_status()
        return response.content
    except Exception as e:
        logger.error(f"TTS request failed: {e}")
        raise


def transcribe_audio(audio_bytes: bytes, filename: str = "audio.wav") -> str:
    """Send audio to STT service and return transcript."""
    try:
        logger.info(f"STT request: filename={filename} size={len(audio_bytes)}")
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{STT_TTS_BASE}/stt",
                files={"audio": (filename, audio_bytes, "audio/wav")},
            )
        response.raise_for_status()
        transcript = response.json()["transcript"]
        logger.info(f"STT transcript: '{transcript}'")
        return transcript
    except Exception as e:
        logger.error(f"STT request failed: {e}")
        raise
