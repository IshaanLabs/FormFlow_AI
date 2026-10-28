@echo off

echo Starting STT/TTS Service...
start "STT-TTS" cmd /k "call venv\Scripts\activate.bat && cd stt-tts-service && uvicorn main:app --port 8001"

echo Starting Agent Service...
start "Agent" cmd /k "call venv\Scripts\activate.bat && cd agent-service && uvicorn main:app --port 8002"

echo Starting Streamlit UI...
start "UI" cmd /k "call venv\Scripts\activate.bat && cd ui-service && streamlit run app.py"

echo All services started.