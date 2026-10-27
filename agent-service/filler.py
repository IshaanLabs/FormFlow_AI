import logging
import uuid
import time
from typing import Optional

from openrouter import call_gemini, parse_json_response

logger = logging.getLogger(__name__)

_sessions: dict[str, dict] = {}
SESSION_TTL_SECONDS = 1800  # 30 minutes


def create_session(form_bytes: bytes, content_type: str, extracted_fields: list[dict]) -> str:
    session_id = str(uuid.uuid4())
    extracted_fields = _filter_fields(extracted_fields)
    missing = [f["label"] for f in extracted_fields]

    _sessions[session_id] = {
        "form_bytes": form_bytes,
        "content_type": content_type,
        "fields": extracted_fields,
        "filled": {},
        "missing": missing,
        "current_index": 0,
        "created_at": time.time(),
    }

    logger.info(f"Session created: session_id={session_id} | total_fields={len(extracted_fields)}")
    return session_id


def get_session(session_id: str) -> dict:
    session = _sessions.get(session_id)
    if not session:
        logger.error(f"Session not found: {session_id}")
        raise KeyError(f"Session {session_id} not found")

    age = time.time() - session["created_at"]
    if age > SESSION_TTL_SECONDS:
        logger.warning(f"Session expired: session_id={session_id} age={age:.0f}s")
        del _sessions[session_id]
        raise KeyError(f"Session {session_id} has expired")

    return session


def get_current_question(session_id: str) -> Optional[dict]:
    """
    Returns the next unanswered field as a question dict, or None if all done.
    Skips over any fields that were already filled by multi-field extraction.
    """
    try:
        session = get_session(session_id)
        missing = session["missing"]

        # Advance current_index past any fields already filled
        while session["current_index"] < len(missing):
            label = missing[session["current_index"]]
            if label not in session["filled"]:
                break
            logger.info(f"Skipping already-filled field '{label}'")
            session["current_index"] += 1

        idx = session["current_index"]
        if idx >= len(missing):
            logger.info(f"All fields answered for session: {session_id}")
            return None

        field_label = missing[idx]
        field_def = next((f for f in session["fields"] if f["label"] == field_label), {})
        field_type = field_def.get("field_type", "text")
        options = field_def.get("options") or []

        question = _build_question(field_label, field_type, options)

        # Count truly remaining fields (not yet filled)
        remaining = [m for m in missing[idx:] if m not in session["filled"]]
        fields_done = len(session["filled"])
        fields_total = len(missing)

        logger.info(f"Current question: session={session_id} | field='{field_label}' | done={fields_done}/{fields_total}")

        return {
            "field_label": field_label,
            "question": question,
            "field_type": field_type,
            "options": options,
            "fields_done": fields_done,
            "fields_total": fields_total,
            "remaining_count": len(remaining),
        }

    except KeyError:
        raise


def submit_answer_multi(session_id: str, current_field_label: str, answer: str, api_key: str) -> Optional[dict]:
    """
    Submit a user answer. Uses Gemini to extract values for multiple fields
    from a single response, then advances past all newly filled fields.
    Returns the next question dict, or None if all done.
    """
    try:
        session = get_session(session_id)
        answer = answer.strip()

        if not answer:
            raise ValueError("Answer cannot be empty")

        # Get all still-unanswered fields to check against
        missing = session["missing"]
        unanswered_fields = [
            {"label": m, "field_type": next((f.get("field_type", "text") for f in session["fields"] if f["label"] == m), "text"),
             "options": next((f.get("options") or [] for f in session["fields"] if f["label"] == m), [])}
            for m in missing if m not in session["filled"]
        ]

        logger.info(f"Extracting multi-field answer: session={session_id} | unanswered={len(unanswered_fields)} | answer='{answer}'")

        # Ask Gemini to extract values for any fields it can find in the answer
        extracted = _extract_multi_field_values(answer, unanswered_fields, api_key)

        if extracted:
            for label, value in extracted.items():
                if value and label in [f["label"] for f in session["fields"]]:
                    session["filled"][label] = value
                    logger.info(f"Multi-fill: session={session_id} | field='{label}' | value='{value}'")
        else:
            # Fallback: save just for the current field if Gemini returned nothing
            logger.warning(f"Multi-field extraction returned nothing, saving for current field only")
            session["filled"][current_field_label] = answer

        return get_current_question(session_id)

    except KeyError:
        raise


def update_answer(session_id: str, field_label: str, new_answer: str) -> dict:
    try:
        session = get_session(session_id)
        new_answer = new_answer.strip()

        if not new_answer:
            raise ValueError("New answer cannot be empty")

        if field_label not in session["filled"]:
            logger.warning(f"Tried to update unanswered field='{field_label}' session={session_id}")
            raise KeyError(f"Field '{field_label}' has not been answered yet")

        old_answer = session["filled"][field_label]
        session["filled"][field_label] = new_answer

        logger.info(f"Answer updated: session={session_id} | field='{field_label}' | '{old_answer}' -> '{new_answer}'")

        return {
            "field_label": field_label,
            "old_answer": old_answer,
            "new_answer": new_answer,
            "all_filled": session["filled"],
        }

    except KeyError:
        raise


def get_all_filled(session_id: str) -> dict:
    session = get_session(session_id)
    return session["filled"]


def get_fields_with_coords(session_id: str) -> list[dict]:
    session = get_session(session_id)
    return session["fields"]


def get_form_bytes(session_id: str) -> tuple[bytes, str]:
    session = get_session(session_id)
    return session["form_bytes"], session["content_type"]


def delete_session(session_id: str):
    if session_id in _sessions:
        del _sessions[session_id]
        logger.info(f"Session deleted: {session_id}")


# ─── Multi-field extraction ───────────────────────────────

def _extract_multi_field_values(
    user_answer: str,
    unanswered_fields: list[dict],
    api_key: str,
) -> dict[str, str]:
    """
    Send the user's answer + list of unanswered fields to Gemini.
    Returns a dict of { field_label: extracted_value } for every field
    Gemini could find a value for. Fields with no value are omitted.
    """
    if not unanswered_fields:
        return {}

    fields_desc = "\n".join(
        f'- "{f["label"]}" (type: {f["field_type"]}'
        + (f', options: {f["options"]}' if f.get("options") else "")
        + ")"
        for f in unanswered_fields
    )

    system_prompt = """You are a form filling assistant. The user has provided a response that may contain answers to one or more form fields.

Extract values for as many fields as you can from the user's response.

Rules:
- Only extract a value if you are confident it matches the field
- For select/enum fields, normalize the answer to the closest valid option
- For date fields, normalize to DD/MM/YYYY format if possible
- If a field has no answer in the user's response, omit it from the output
- Return ONLY a valid JSON object mapping field labels to values. No explanation."""

    user_prompt = f"""User's response: "{user_answer}"

Fields to fill:
{fields_desc}

Return a JSON object with the field labels as keys and extracted values as values.
Only include fields you found answers for."""

    try:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        raw = call_gemini(api_key, messages, temperature=0.1)
        result = parse_json_response(raw)

        if not isinstance(result, dict):
            logger.warning(f"Multi-field extraction returned non-dict: {type(result)}")
            return {}

        logger.info(f"Multi-field extraction found values for: {list(result.keys())}")
        return result

    except Exception as e:
        logger.error(f"Multi-field extraction failed: {e}")
        return {}


# ─── Noise filtering ──────────────────────────────────────

_NOISE_LABELS = {
    "new", "yes", "no", "na", "n/a", "date", "sign", "sr", "no.",
    "s.no", "sl", "sl.no", "tick", "check", "box", "field", "value",
    "name", "signature", "place", "office", "seal", "stamp",
}


def _filter_fields(fields: list[dict]) -> list[dict]:
    seen_labels = set()
    filtered = []

    for field in fields:
        label = field.get("label", "").strip()
        if not label:
            continue
        if len(label) < 3:
            logger.debug(f"Filtered short label: '{label}'")
            continue
        if label.lower() in _NOISE_LABELS:
            logger.debug(f"Filtered noise label: '{label}'")
            continue
        if label.lower() in seen_labels:
            logger.debug(f"Filtered duplicate label: '{label}'")
            continue
        seen_labels.add(label.lower())
        filtered.append(field)

    logger.info(f"Field filtering: {len(fields)} -> {len(filtered)} fields after cleanup")
    return filtered


# ─── Question builder ─────────────────────────────────────

def _build_question(field_label: str, field_type: str, options: list[str]) -> str:
    if options:
        options_str = ", ".join(options)
        return f"For {field_label}, please choose one of: {options_str}."
    if field_type == "date":
        return f"Please tell me your {field_label}. You can say it as day, month, year."
    if field_type == "number":
        return f"Please tell me your {field_label} as a number."
    if field_type == "checkbox":
        return f"For {field_label}, please say yes or no."
    return f"Please tell me your {field_label}."
