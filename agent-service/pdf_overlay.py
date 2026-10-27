import base64
import logging

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# Text overlay settings
FONT_COLOR = (0.0, 0.0, 0.6)   # dark blue
FONT_NAME = "helv"              # Helvetica built-in in PyMuPDF

# Approximate character width ratio for Helvetica (width = font_size * ratio)
_CHAR_WIDTH_RATIO = 0.55


def _clip_text_to_width(text: str, max_width_pts: float, font_size: float) -> str:
    """
    Truncate text so it fits within max_width_pts at the given font_size.
    Uses an approximate char width for Helvetica.
    """
    char_width = font_size * _CHAR_WIDTH_RATIO
    max_chars = int(max_width_pts / char_width)
    if len(text) <= max_chars:
        return text
    clipped = text[:max(1, max_chars - 1)]
    logger.debug(f"Clipped text '{text}' to '{clipped}' to fit {max_width_pts:.1f}pts")
    return clipped


def overlay_text_on_form(
    form_bytes: bytes,
    content_type: str,
    filled_fields: dict[str, str],
    field_coords: list[dict],
) -> bytes:
    """
    Overlay filled text values on the original form at the blank_x/blank_y coordinates.

    Args:
        form_bytes:    raw bytes of the uploaded form (image or PDF)
        content_type:  MIME type
        filled_fields: { "Full Name": "John Doe", ... }
        field_coords:  list of field dicts with blank_x, blank_y, blank_width, blank_height as %

    Returns:
        PDF bytes of the filled form
    """
    logger.info(f"Starting PDF overlay | content_type={content_type} | fields_to_fill={len(filled_fields)}")

    try:
        if content_type == "application/pdf":
            doc = _load_pdf(form_bytes)
        else:
            doc = _image_to_pdf_doc(form_bytes, content_type)

        page = doc[0]
        page_width = page.rect.width
        page_height = page.rect.height

        logger.info(f"Page dimensions: {page_width:.1f} x {page_height:.1f} pts")

        filled_count = 0
        skipped_count = 0

        for field in field_coords:
            label = field.get("label", "")
            value = filled_fields.get(label, "")

            if not value:
                skipped_count += 1
                logger.debug(f"Skipping field '{label}' — no value")
                continue

            try:
                blank_x_pct = float(field["blank_x"])
                blank_y_pct = float(field["blank_y"])
                blank_w_pct = float(field.get("blank_width", 20.0))
                blank_h_pct = float(field.get("blank_height", 5.0))

                # Convert % to PDF points
                x = (blank_x_pct / 100.0) * page_width
                y_from_top = (blank_y_pct / 100.0) * page_height
                field_width_pts = (blank_w_pct / 100.0) * page_width
                field_height_pts = (blank_h_pct / 100.0) * page_height

                # Font size: fit within field height with padding, capped between 6 and 11
                font_size = max(6.0, min(11.0, field_height_pts * 0.55))

                # Clip value text to fit within field width
                value = _clip_text_to_width(value, field_width_pts, font_size)

                # Y position: place baseline at vertical center of the blank area
                # PDF Y origin is bottom-left, so flip: page_height - y_from_top gives top of field
                # then go down by half the field height to center, minus a small baseline offset
                y_pdf = page_height - y_from_top - (field_height_pts * 0.5) + (font_size * 0.3)

                # X position: small left padding inside the blank area
                x_pdf = x + 2

                page.insert_text(
                    fitz.Point(x_pdf, y_pdf),
                    value,
                    fontname=FONT_NAME,
                    fontsize=font_size,
                    color=FONT_COLOR,
                )

                filled_count += 1
                logger.info(f"Filled '{label}' at ({x_pdf:.1f}, {y_pdf:.1f}) size={font_size:.1f} value='{value}'")

            except Exception as e:
                logger.error(f"Failed to overlay field '{label}': {e}")
                skipped_count += 1
                continue

        logger.info(f"Overlay complete | filled={filled_count} | skipped={skipped_count}")

        pdf_bytes = doc.tobytes()
        doc.close()
        return pdf_bytes

    except Exception as e:
        logger.error(f"PDF overlay failed: {e}")
        raise


def _load_pdf(pdf_bytes: bytes) -> fitz.Document:
    """Load a PDF from bytes."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        logger.info(f"PDF loaded: {doc.page_count} pages")
        return doc
    except Exception as e:
        logger.error(f"Failed to load PDF: {e}")
        raise


def _image_to_pdf_doc(image_bytes: bytes, content_type: str) -> fitz.Document:
    """
    Wrap an image (JPEG/PNG) into a PyMuPDF document so we can overlay text on it.
    The image becomes the background of a single PDF page.
    """
    try:
        # Determine image type
        if "jpeg" in content_type or "jpg" in content_type:
            img_ext = "jpeg"
        elif "png" in content_type:
            img_ext = "png"
        else:
            img_ext = "jpeg"
            logger.warning(f"Unknown image content_type={content_type}, defaulting to jpeg")

        # Open image with fitz to get dimensions
        img_doc = fitz.open(stream=image_bytes, filetype=img_ext)
        img_page = img_doc[0]
        img_rect = img_page.rect

        # Create a new PDF with the same dimensions as the image
        pdf_doc = fitz.open()
        pdf_page = pdf_doc.new_page(width=img_rect.width, height=img_rect.height)

        # Embed the image as the page background
        pdf_page.insert_image(pdf_page.rect, stream=image_bytes)

        img_doc.close()
        logger.info(f"Image wrapped into PDF page: {img_rect.width:.1f} x {img_rect.height:.1f}")
        return pdf_doc

    except Exception as e:
        logger.error(f"Failed to convert image to PDF doc: {e}")
        raise
