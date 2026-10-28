# FormFlow AI

> AI-powered form filling assistant — upload any government or official form, answer questions by voice or text, and get a filled PDF instantly.

FormFlow AI uses Google Gemini vision to extract every field from a scanned form image or PDF, asks you for the missing information through voice or text, and overlays your answers directly onto the original form — producing a ready-to-submit filled PDF.

---

## Features

- **Vision-based field extraction** — gemini-3-flash-preview reads any printed form (government, KYC, financial) and extracts every fillable field with precise coordinates
- **Voice input** — speak your answers using Whisper STT; the app transcribes and fills automatically
- **Text input** — type answers if you prefer, both modes work side by side
- **Multi-field intelligence** — say "My name is John, born 14th Feb 1990, male" and the AI fills multiple fields at once
- **Smart checkbox ticking** — for select fields (Gender, Marital Status, Nationality etc.), the correct checkbox is ticked on the form rather than writing text
- **Answer correction** — go back and fix any previously submitted answer before generating the PDF
- **Accurate PDF overlay** — filled values are placed at the exact blank space coordinates on the original form, not on a separate summary page
- **Supports images and PDFs** — JPEG, PNG, and PDF uploads all work

---

## Tech Stack

| Layer          | Technology                                            |
| -------------- | ----------------------------------------------------- |
| Vision / AI    | Google gemini-3-flash-preview (via Google AI Studio) |
| Speech-to-Text | OpenAI Whisper (small, runs locally)                  |
| Text-to-Speech | gTTS                                                  |
| PDF Overlay    | PyMuPDF (fitz)                                        |
| Agent API      | FastAPI                                               |
| STT/TTS API    | FastAPI                                               |
| UI             | Streamlit                                             |

---

## Project Structure

```
FormFlow_AI/
├── agent-service/          # Port 8002 — field extraction, session management, PDF generation
│   ├── main.py             # FastAPI routes
│   ├── extractor.py        # Gemini vision — extract fields + coordinates
│   ├── filler.py           # Session state, multi-field answer extraction
│   ├── pdf_overlay.py      # PyMuPDF text + checkbox overlay
│   ├── openrouter.py       # Google AI Studio SDK client
│   ├── .env                # API key config
│   └── requirements.txt
│
├── stt-tts-service/        # Port 8001 — speech transcription and synthesis
│   ├── main.py             # FastAPI routes
│   ├── stt.py              # Whisper small transcription
│   ├── tts.py              # gTTS synthesis
│   └── requirements.txt
│
├── ui-service/             # Port 8501 — Streamlit web interface
│   ├── app.py              # Main UI — upload, fill, download
│   ├── api_client.py       # HTTP clients for agent and STT/TTS services
│   └── requirements.txt
│
└── README.md
```

---

## Installation

### Prerequisites

- Python 3.10+
- A [Google AI Studio](https://aistudio.google.com/apikey) API key

### 1. Clone the repository:

```bash
git clone  https://github.com/IshaanLabs/FormFlow_AI
cd FormFlow_AI
```


### 2. Create and activate a virtual environment:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. STT/TTS Service

```bash
cd stt-tts-service
pip install -r requirements.txt
```

### 4. Agent Service

```bash
cd agent-service
pip install -r requirements.txt
```

### 5. UI

```bash
cd ui-service
pip install -r requirements.txt
```

---

## Configuration

Create a `.env` file inside `agent-service/`:

```env
GOOGLE_AI_STUDIO_API_KEY=AIza-your-key-here
```

Get your key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey).

---

## Usage

Start all three services in separate terminals:

```bash
# Terminal 1 — STT/TTS
cd stt-tts-service
uvicorn main:app --port 8001

# Terminal 2 — Agent
cd agent-service
uvicorn main:app --port 8002

# Terminal 3 — UI
cd ui-service
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

### Flow

1. **Upload** your form (JPG, PNG, or PDF)
2. Click **Extract Fields** — Gemini analyzes the form and identifies every fillable field
3. **Answer each question** by speaking into the mic or typing in the text box
4. The app auto-fills multiple fields if your answer contains more than one value
5. For checkbox fields (Gender, Status etc.), the correct option is ticked automatically
6. Review and **correct any answer** using the answers panel
7. Click **Generate Filled PDF** and download your completed form

---

## Notes

- **Whisper runs locally** — no audio data is sent to any external service
- **Form image stays on your machine** — the original form bytes are stored in the agent service session (in-memory) and never persisted to disk or sent anywhere except to Google AI Studio for field extraction
- **Session expires after 30 minutes** — start over if the session times out
- **Multi-page forms** — currently only the first page is extracted and filled
- **Non-Latin scripts** — field values in Hindi, Tamil, etc. are filled as text where the font supports it; checkbox ticking works for all languages

---

## Contributing

Contributions to this project are welcome! If you have ideas for improvements, bug fixes, or new features, feel free to open an issue or submit a pull request.

---

## License

This project is licensed under the MIT License — see the [MIT License](https://opensource.org/licenses/MIT) file for details.
