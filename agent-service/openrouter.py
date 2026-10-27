import json
import logging

import google.generativeai as genai

logger = logging.getLogger(__name__)

# GEMINI_MODEL = "gemini-2.5-flash-preview-05-20"
GEMINI_MODEL = "gemini-3-flash-preview"

def call_gemini(api_key: str, messages: list, temperature: float = 0.1) -> str:
    """
    Call Gemini 2.5 Flash via Google AI Studio SDK.
    Accepts the same messages format as before:
    [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "..." or [...parts]},
    ]
    Returns the text content of the response.
    """
    logger.info(f"Calling Gemini | model={GEMINI_MODEL} | messages={len(messages)}")

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            generation_config=genai.GenerationConfig(temperature=temperature),
        )

        # Extract system prompt if present
        system_instruction = None
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_instruction = msg["content"]
            else:
                user_messages.append(msg)

        if system_instruction:
            model = genai.GenerativeModel(
                model_name=GEMINI_MODEL,
                system_instruction=system_instruction,
                generation_config=genai.GenerationConfig(temperature=temperature),
            )

        # Build the contents list for the SDK
        contents = []
        for msg in user_messages:
            role = "user" if msg["role"] == "user" else "model"
            content = msg["content"]

            if isinstance(content, str):
                contents.append({"role": role, "parts": [{"text": content}]})
            elif isinstance(content, list):
                # Multimodal: list of {type, text} or {type, image_url}
                parts = []
                for part in content:
                    if part["type"] == "text":
                        parts.append({"text": part["text"]})
                    elif part["type"] == "image_url":
                        # data URL format: "data:image/jpeg;base64,<b64>"
                        data_url = part["image_url"]["url"]
                        if data_url.startswith("data:"):
                            header, b64_data = data_url.split(",", 1)
                            mime_type = header.split(":")[1].split(";")[0]
                            import base64
                            image_bytes = base64.b64decode(b64_data)
                            parts.append({"inline_data": {"mime_type": mime_type, "data": image_bytes}})
                        else:
                            logger.warning(f"Skipping non-data image URL: {data_url[:50]}")
                contents.append({"role": role, "parts": parts})

        response = model.generate_content(contents)
        content = response.text.strip()
        logger.info(f"Gemini response received: {len(content)} chars")
        return content

    except Exception as e:
        logger.error(f"Gemini call failed: {e}")
        raise


def parse_json_response(raw: str) -> dict | list:
    """
    Parse JSON from model response — strips markdown code fences if present.
    If the response is a truncated JSON array, recovers all complete objects.
    """
    trimmed = raw.strip()

    # Strip ```json ... ``` or ``` ... ``` fences
    if trimmed.startswith("```"):
        lines = trimmed.split("\n")
        inner = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
        trimmed = inner.strip()

    # First try: clean parse
    try:
        result = json.loads(trimmed)
        logger.info("JSON parsed successfully from model response")
        return result
    except json.JSONDecodeError as e:
        logger.warning(f"Clean JSON parse failed ({e}), attempting truncation recovery")

    # Recovery: if it's a truncated array, walk back to the last complete object
    if trimmed.startswith("["):
        recovered = _recover_truncated_array(trimmed)
        if recovered:
            logger.info(f"Recovered {len(recovered)} objects from truncated JSON array")
            return recovered

    logger.error(f"Failed to parse JSON from model response.\nRaw: {raw[:300]}")
    raise Exception("Model returned invalid JSON that could not be recovered")


def _recover_truncated_array(raw: str) -> list | None:
    """
    Given a JSON array string that may be cut off mid-way,
    return all fully-formed objects by finding the last valid '},' boundary.
    """
    try:
        # Find the last complete object: scan backwards for '}'
        last_close = raw.rfind("}")
        if last_close == -1:
            return None

        # Reconstruct a valid array up to and including that last '}'
        candidate = raw[:last_close + 1].rstrip().rstrip(",") + "]"

        # It might not start cleanly — ensure it starts with '['
        if not candidate.startswith("["):
            candidate = "[" + candidate

        result = json.loads(candidate)
        return result if isinstance(result, list) else None
    except Exception as e:
        logger.error(f"Truncation recovery failed: {e}")
        return None
