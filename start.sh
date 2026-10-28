#!/bin/bash

source venv/bin/activate

cleanup() {
    echo ""
    echo "Stopping all services..."
    kill $(jobs -p) 2>/dev/null
    exit
}

trap cleanup SIGINT SIGTERM

cd stt-tts-service
uvicorn main:app --port 8001 &
cd ..

cd agent-service
uvicorn main:app --port 8002 &
cd ..

cd ui-service
streamlit run app.py &
cd ..

wait