#!/bin/bash
# ClinicalCopilot - Stop Script

echo "Stopping ClinicalCopilot..."
pkill -f "menubar_app" 2>/dev/null || true
pkill -f "clinical_copilot" 2>/dev/null || true
pkill -f "uvicorn app.main:app --port 8001" 2>/dev/null || true
pkill -f "http.server 8080" 2>/dev/null || true
pkill -f "screenpipe" 2>/dev/null || true
pkill -f "ffmpeg.*screenpipe" 2>/dev/null || true
sleep 1
echo "Stopped."
