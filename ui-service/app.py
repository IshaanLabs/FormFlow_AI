import logging
import base64

import streamlit as st

from api_client import (
    extract_fields,
    generate_pdf,
    get_tts_audio,
    submit_answer,
    transcribe_audio,
    update_answer,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

st.set_page_config(page_title="Form Filler", page_icon="📄", layout="wide")
st.title("📄 FormFlow AI")
st.caption("AI-powered form filling assistant — upload any government or official form, answer questions by voice or text, and get a filled PDF instantly.")


# ─── Session state init ───────────────────────────────────

def init_state():
    defaults = {
        "session_id": None,
        "fields": [],
        "current_question": None,
        "filled_answers": {},
        "done": False,
        "pdf_bytes": None,
        "uploaded_file_bytes": None,
        "uploaded_file_type": None,
        "uploaded_file_name": None,
        "last_spoken_field": None,   # track which field TTS was last played for
        "step": "upload",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def reset():
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    init_state()


# ─── Helpers ─────────────────────────────────────────────

def play_tts(text: str, key: str, container=None):
    """
    Play TTS audio only once per unique key (field label).
    Avoids replaying audio on every rerun triggered by widget interaction.
    """
    if st.session_state.get("last_spoken_field") == key:
        return
    st.session_state["last_spoken_field"] = key

    target = container or st
    try:
        audio_bytes = get_tts_audio(text)
        b64 = base64.b64encode(audio_bytes).decode()
        target.markdown(
            f'<audio autoplay><source src="data:audio/mp3;base64,{b64}" type="audio/mp3"></audio>',
            unsafe_allow_html=True,
        )
    except Exception as e:
        logger.error(f"TTS playback failed: {e}")
        target.warning(f"⚠️ Could not play audio: {e}")


def show_form_preview(container):
    file_bytes = st.session_state.uploaded_file_bytes
    file_type = st.session_state.uploaded_file_type
    file_name = st.session_state.uploaded_file_name

    if not file_bytes:
        return

    container.markdown("### 📄 Your Form")

    if file_type and file_type.startswith("image"):
        container.image(file_bytes, use_container_width=True)
    else:
        # Browsers block data: URI iframes for PDFs — serve via agent endpoint instead
        session_id = st.session_state.session_id
        preview_url = f"http://localhost:8002/preview/{session_id}"
        container.markdown(
            f'<iframe src="{preview_url}" '
            f'width="100%" height="800px" style="border:1px solid #ddd; border-radius:8px;"></iframe>',
            unsafe_allow_html=True,
        )
        container.caption(f"📎 {file_name}")


def show_progress(container=None):
    target = container or st
    q = st.session_state.current_question
    if q:
        done = q["fields_done"]
        total = q["fields_total"]
        target.progress(
            done / total if total > 0 else 0,
            text=f"Field {done + 1} of {total}",
        )


def handle_submit(field_label: str, answer: str):
    try:
        result = submit_answer(st.session_state.session_id, field_label, answer)

        # Count how many new fields were filled (may be more than 1)
        prev_count = len(st.session_state.filled_answers)
        # Fetch updated filled answers from next_question context
        if result["done"]:
            st.session_state.done = True
            st.session_state.current_question = None
            st.session_state.step = "complete"
        else:
            nq = result["next_question"]
            newly_filled = nq["fields_done"] - prev_count
            if newly_filled > 1:
                st.toast(f"✅ {newly_filled} fields filled from your response!", icon="🎉")
            st.session_state.current_question = nq

        # Sync filled_answers from fields_done count — we don't have the values
        # directly, so just mark the submitted answer and let the next question
        # reflect the real state from the agent
        st.session_state.filled_answers[field_label] = answer

        st.rerun()
    except Exception as e:
        logger.error(f"Submit answer failed: {e}")
        st.error(f"❌ Failed to submit answer: {e}")


# ─── STEP 1: Upload ───────────────────────────────────────

init_state()

if st.session_state.step == "upload":
    uploaded_file = st.file_uploader(
        "Upload your form (JPG, PNG, or PDF)",
        type=["jpg", "jpeg", "png", "pdf"],
    )

    if uploaded_file:
        if uploaded_file.type.startswith("image"):
            st.image(uploaded_file, width=500)
        else:
            st.info(f"📎 PDF uploaded: {uploaded_file.name}")

        if st.button("🔍 Extract Fields", type="primary"):
            with st.spinner("Analyzing form with AI... this may take 15-30 seconds"):
                try:
                    file_bytes = uploaded_file.read()
                    result = extract_fields(file_bytes, uploaded_file.name, uploaded_file.type)

                    st.session_state.session_id = result["session_id"]
                    st.session_state.fields = result["fields"]
                    st.session_state.current_question = result["next_question"]
                    st.session_state.uploaded_file_bytes = file_bytes
                    st.session_state.uploaded_file_type = uploaded_file.type
                    st.session_state.uploaded_file_name = uploaded_file.name
                    st.session_state.step = "filling"

                    logger.info(f"Extraction done: session={result['session_id']} fields={result['total_fields']}")
                    st.rerun()

                except Exception as e:
                    logger.error(f"Extraction failed: {e}")
                    st.error(f"❌ Failed to extract fields: {e}")


# ─── STEP 2: Filling ─────────────────────────────────────

elif st.session_state.step == "filling":

    # Guard: if no question left, move to complete — use st.stop() to prevent further rendering
    if st.session_state.current_question is None or st.session_state.done:
        st.session_state.step = "complete"
        st.rerun()
        st.stop()

    q = st.session_state.current_question

    left_col, right_col = st.columns([1, 1], gap="large")

    show_form_preview(left_col)

    with right_col:
        show_progress()
        st.divider()

        st.subheader(f"📝 {q['field_label']}")
        st.write(f"**{q['question']}**")

        # Play TTS only once per field, not on every rerun
        play_tts(q["question"], key=q["field_label"])

        st.divider()

        # ── Quick-select buttons for options fields ──
        if q.get("options"):
            st.markdown("**Quick select:**")
            cols = st.columns(len(q["options"]))
            for i, opt in enumerate(q["options"]):
                if cols[i].button(opt, key=f"opt_{q['field_label']}_{opt}"):
                    handle_submit(q["field_label"], opt)
            st.divider()

        # ── Voice input ──
        st.markdown("**🎤 Voice Input**")
        audio_input = st.audio_input("Record your answer", key=f"audio_{q['field_label']}")

        if audio_input:
            with st.spinner("Transcribing..."):
                try:
                    audio_bytes = audio_input.read()
                    transcript = transcribe_audio(audio_bytes, filename="answer.wav")
                    st.success(f"Heard: **{transcript}**")
                    if st.button("✅ Use this answer", key=f"use_voice_{q['field_label']}"):
                        handle_submit(q["field_label"], transcript)
                except Exception as e:
                    logger.error(f"STT failed: {e}")
                    st.error(f"❌ Could not transcribe audio: {e}")

        st.divider()

        # ── Text input ──
        st.markdown("**⌨️ Or type your answer**")
        with st.form(key="text_answer_form", clear_on_submit=True):
            text_answer = st.text_input(
                "Your answer",
                placeholder=f"Enter {q['field_label']}...",
            )
            if st.form_submit_button("Submit →", type="primary") and text_answer.strip():
                handle_submit(q["field_label"], text_answer.strip())

        st.divider()

        # ── Answers so far + correction ──
        if st.session_state.filled_answers:
            with st.expander(f"📋 Answers so far ({len(st.session_state.filled_answers)} filled)"):
                for field_label, answer in list(st.session_state.filled_answers.items()):
                    col1, col2, col3 = st.columns([3, 3, 1])
                    col1.write(f"**{field_label}**")
                    col2.write(answer)
                    if col3.button("✏️", key=f"edit_{field_label}"):
                        st.session_state[f"editing_{field_label}"] = True

                    if st.session_state.get(f"editing_{field_label}"):
                        with st.form(key=f"edit_form_{field_label}", clear_on_submit=True):
                            new_val = st.text_input(f"New value for {field_label}", value=answer)
                            if st.form_submit_button("Save") and new_val.strip():
                                try:
                                    update_answer(
                                        st.session_state.session_id,
                                        field_label,
                                        new_val.strip(),
                                    )
                                    st.session_state.filled_answers[field_label] = new_val.strip()
                                    st.session_state[f"editing_{field_label}"] = False
                                    st.success(f"✅ Updated '{field_label}'")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"❌ Update failed: {e}")


# ─── STEP 3: Complete ─────────────────────────────────────

elif st.session_state.step == "complete":
    left_col, right_col = st.columns([1, 1], gap="large")

    show_form_preview(left_col)

    with right_col:
        st.success("✅ All fields filled!")
        play_tts("All fields have been filled. Your form is ready to download.", key="complete")

        st.subheader("📋 Summary")
        for field_label, answer in st.session_state.filled_answers.items():
            col1, col2 = st.columns([2, 3])
            col1.write(f"**{field_label}**")
            col2.write(answer)

        st.divider()

        if st.session_state.pdf_bytes is None:
            if st.button("📥 Generate Filled PDF", type="primary"):
                with st.spinner("Generating your filled form..."):
                    try:
                        pdf_bytes = generate_pdf(st.session_state.session_id)
                        st.session_state.pdf_bytes = pdf_bytes
                        st.rerun()
                    except Exception as e:
                        logger.error(f"PDF generation failed: {e}")
                        st.error(f"❌ PDF generation failed: {e}")

        if st.session_state.pdf_bytes:
            st.download_button(
                label="⬇️ Download Filled Form (PDF)",
                data=st.session_state.pdf_bytes,
                file_name="filled-form.pdf",
                mime="application/pdf",
                type="primary",
            )

        if st.button("🔄 Start Over"):
            reset()
            st.rerun()
