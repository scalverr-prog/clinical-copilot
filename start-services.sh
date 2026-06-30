#!/bin/bash
# Auto-start and keep Clinical Insight alive

BACKEND_DIR="/Users/scalver/clinical-copilot-package/clinical_insight_backend"
LOG="/tmp/clinical-insight.log"

# Function to start Clinical Insight
start_clinical_insight() {
    if ! curl -s http://localhost:8001/health --max-time 2 > /dev/null 2>&1; then
        echo "$(date): Starting Clinical Insight..."
        pkill -9 -f "uvicorn.*8001" 2>/dev/null
        sleep 1
        cd "$BACKEND_DIR" && ./venv/bin/python3 -m uvicorn app.main:app --port 8001 --workers 2 >> "$LOG" 2>&1 &
        sleep 3
    fi
}

# Function to start Ollama
start_ollama() {
    if ! curl -s http://localhost:11434/api/tags --max-time 2 > /dev/null 2>&1; then
        echo "$(date): Starting Ollama..."
        open -a Ollama
        sleep 5
    fi
}

# Start both
start_ollama
start_clinical_insight

# Keep checking every 30 seconds
while true; do
    sleep 30
    start_clinical_insight
    start_ollama
done
