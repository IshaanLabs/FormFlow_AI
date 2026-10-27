import base64
import logging
import os

import fitz  # PyMuPDF

from openrouter import call_gemini, parse_json_response

logger = logging.getLogger(__name__)


def _pdf_first_page_to_base64(pdf_bytes: bytes) -> str:
    """Convert the first page of a PDF to a JPEG base64 image for vision."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc[0]
        # Render at 2x zoom for better OCR accuracy
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("jpeg")
        doc.close()
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        logger.info(f"PDF first page rendered to JPEG: {len(img_bytes)} bytes")
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        logger.error(f"Failed to render PDF page to image: {e}")
        raise


def _image_bytes_to_base64(image_bytes: bytes, content_type: str) -> str:
    """Convert raw image bytes to base64 data URL."""
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{content_type};base64,{b64}"


def extract_fields(file_bytes: bytes, content_type: str, api_key: str) -> list[dict]:
    """
    Send the form image to Gemini vision and extract all fields with coordinates.
    Retries once with a reduced prompt if the first response is truncated.
    """
    logger.info(f"Extracting fields from form | content_type={content_type}")

    try:
        if content_type == "application/pdf":
            image_data_url = _pdf_first_page_to_base64(file_bytes)
        else:
            image_data_url = _image_bytes_to_base64(file_bytes, content_type)
    except Exception as e:
        logger.error(f"Failed to prepare image for extraction: {e}")
        raise

    fields = _call_extract(api_key, image_data_url, limit=None)

    # If we got very few fields back it likely means the response was heavily truncated
    # Retry once asking the model to limit output to the most important fields only
    if len(fields) < 3:
        logger.warning(f"Only {len(fields)} fields returned, retrying with reduced prompt")
        fields = _call_extract(api_key, image_data_url, limit=20)

    logger.info(f"Extracted {len(fields)} fields from form")
    return fields


def _call_extract(api_key: str, image_data_url: str, limit: int | None) -> list[dict]:
    """
    Single extraction attempt. limit=None means extract all fields;
    limit=N means ask the model to return only the N most important fields
    to avoid response truncation.
    """
    limit_instruction = (
        f"IMPORTANT: Return at most {limit} of the most important fillable fields only. "
        "Skip checkboxes, decorative elements, and optional fields. "
        "Prioritise: name, date of birth, address, ID numbers, phone, signature fields."
        if limit
        else ""
    )

    system_prompt = f"""You are a form field extractor. Analyze the government form image and extract every fillable field.

For each field return:
- label: the field label text (in English if possible, otherwise original language)
- label_x, label_y: approximate position of the label text as percentage of image width/height (0-100)
- blank_x, blank_y: approximate position of the BLANK SPACE where the answer should be written, as percentage of image width/height (0-100). This is the actual empty box or line where text will be filled in — NOT the label position.
- blank_width, blank_height: size of the blank space as percentage of image width/height
- field_type: one of "text", "date", "number", "select", "checkbox"
- options: for "select" fields (like Gender, Category, Marital Status), list the allowed options as an array of strings. For all other field types set this to null.
- required: true or false

IMPORTANT:
- blank_x/blank_y must point to the empty answer area, not the label
- For fields where the blank is to the RIGHT of the label, blank_x will be larger than label_x
- For fields where the blank is BELOW the label, blank_y will be larger than label_y
- For Gender fields, options should be ["Male", "Female", "Other"] unless the form shows different options
- For fields with a fixed set of printed choices (checkboxes in a row, printed options), set field_type to "select" and list those choices in options
- Be thorough — include every single field
{limit_instruction}

Return ONLY a valid JSON array. No explanation, no markdown fences."""

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Extract all form fields with their blank space coordinates."},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        },
    ]

    try:
        raw = call_gemini(api_key, messages, temperature=0.1)
        fields = parse_json_response(raw)

        if not isinstance(fields, list):
            logger.error(f"Expected list from model, got: {type(fields)}")
            raise Exception("Model did not return a list of fields")

        return fields

    except Exception as e:
        logger.error(f"Field extraction attempt failed: {e}")
        raise
