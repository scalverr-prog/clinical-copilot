#!/bin/bash
# ClinicalCopilot - Stop Script

echo "Stopping ClinicalCopilot..."
# NOTE: Penguin (menubar_app) is NEVER terminated - it stays in menu bar always
pkill -f "floating_tab" 2>/dev/null || true
pkill -f "clinical_copilot.main" 2>/dev/null || true
pkill -f "uvicorn app.main:app --port 8001" 2>/dev/null || true
pkill -f "http.server 8080" 2>/dev/null || true
pkill -f "screenpipe" 2>/dev/null || true
pkill -f "ffmpeg.*screenpipe" 2>/dev/null || true
sleep 1
echo "Stopped."
