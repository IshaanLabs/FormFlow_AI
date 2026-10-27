import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from extractor import extract_fields
from filler import (
    create_session,
    delete_session,
    get_all_filled,
    get_current_question,
    get_fields_with_coords,
    get_form_bytes,
    submit_answer_multi,
    update_answer,
)
from pdf_overlay import overlay_text_on_form

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

GOOGLE_AI_STUDIO_API_KEY = os.getenv("GOOGLE_AI_STUDIO_API_KEY", "")

app = FastAPI(title="Form Filler Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Request / Response models ───────────────────────────

class SubmitAnswerRequest(BaseModel):
    session_id: str
    field_label: str
    answer: str


class UpdateAnswerRequest(BaseModel):
    session_id: str
    field_label: str
    new_answer: str


# ─── Routes ──────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "agent"}


@app.post("/extract-fields")
async def extract_fields_endpoint(form: UploadFile = File(...)):
    """
    Upload a form image or PDF.
    Returns session_id + extracted fields + first question to ask the user.
    """
    if not GOOGLE_AI_STUDIO_API_KEY:
        raise HTTPException(status_code=503, detail="GOOGLE_AI_STUDIO_API_KEY not configured")

    logger.info(f"Extract fields request: filename={form.filename} content_type={form.content_type}")

    allowed_types = {"image/jpeg", "image/jpg", "image/png", "application/pdf"}
    if form.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {form.content_type}. Allowed: {allowed_types}",
        )

    try:
        file_bytes = await form.read()
        logger.info(f"Form file read: {len(file_bytes)} bytes")
    except Exception as e:
        logger.error(f"Failed to read uploaded file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read file: {e}")

    try:
        fields = extract_fields(file_bytes, form.content_type, GOOGLE_AI_STUDIO_API_KEY)
    except Exception as e:
        logger.error(f"Field extraction failed: {e}")
        raise HTTPException(status_code=500, detail=f"Field extraction failed: {e}")

    if not fields:
        raise HTTPException(status_code=422, detail="No fields could be extracted from the form")

    try:
        session_id = create_session(file_bytes, form.content_type, fields)
        first_question = get_current_question(session_id)
    except Exception as e:
        logger.error(f"Session creation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Session creation failed: {e}")

    return {
        "session_id": session_id,
        "total_fields": len(fields),
        "fields": fields,
        "next_question": first_question,
    }


@app.post("/submit-answer")
def submit_answer_endpoint(request: SubmitAnswerRequest):
    """
    Submit an answer for the current field.
    Gemini extracts values for multiple fields from a single response.
    Returns the next question or done=True if all fields are answered.
    """
    logger.info(f"Submit answer: session={request.session_id} field='{request.field_label}' answer='{request.answer}'")

    if not GOOGLE_AI_STUDIO_API_KEY:
        raise HTTPException(status_code=503, detail="GOOGLE_AI_STUDIO_API_KEY not configured")

    try:
        next_question = submit_answer_multi(
            request.session_id,
            request.field_label,
            request.answer,
            GOOGLE_AI_STUDIO_API_KEY,
        )
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Submit answer failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    if next_question is None:
        return {"done": True, "next_question": None}

    return {"done": False, "next_question": next_question}


@app.post("/update-answer")
def update_answer_endpoint(request: UpdateAnswerRequest):
    """
    Correct or modify a previously submitted answer.
    """
    logger.info(f"Update answer: session={request.session_id} field='{request.field_label}' new='{request.new_answer}'")

    try:
        result = update_answer(request.session_id, request.field_label, request.new_answer)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Update answer failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return result


@app.post("/generate-pdf")
def generate_pdf_endpoint(session_id: str):
    """
    Generate the filled PDF for a session.
    Returns the PDF file as a binary response.
    """
    logger.info(f"Generate PDF request: session={session_id}")

    try:
        filled_fields = get_all_filled(session_id)
        field_coords = get_fields_with_coords(session_id)
        form_bytes, content_type = get_form_bytes(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to retrieve session data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    if not filled_fields:
        raise HTTPException(status_code=400, detail="No fields have been filled yet")

    try:
        pdf_bytes = overlay_text_on_form(form_bytes, content_type, filled_fields, field_coords)
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")

    logger.info(f"PDF generated successfully: {len(pdf_bytes)} bytes | session={session_id}")

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=filled-form-{session_id[:8]}.pdf"},
    )


@app.get("/preview/{session_id}")
def preview_form(session_id: str):
    """
    Serve the original uploaded form bytes so the UI can embed it in an iframe.
    Browsers block data: URI iframes for PDFs, so we serve it via a real URL instead.
    """
    try:
        form_bytes, content_type = get_form_bytes(session_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return Response(
        content=form_bytes,
        media_type=content_type,
        headers={"Content-Disposition": "inline"},
    )


@app.delete("/session/{session_id}")
def delete_session_endpoint(session_id: str):
    """Clean up a session."""
    try:
        delete_session(session_id)
    except Exception as e:
        logger.error(f"Session deletion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    return {"deleted": True, "session_id": session_id}
