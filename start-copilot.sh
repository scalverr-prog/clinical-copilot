#!/bin/bash
# ClinicalCopilot - Robust startup with health verification

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Setup PATH for both Intel and Apple Silicon Macs
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

# Wait for a service to respond, with retries
wait_for_service() {
    local url="$1"
    local name="$2"
    local max_attempts="${3:-10}"
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if curl -s --connect-timeout 2 "$url" > /dev/null 2>&1; then
            return 0
        fi
        sleep 1
        ((attempt++))
    done
    return 1
}

# Find screenpipe binary (Intel or Apple Silicon)
find_screenpipe() {
    if [ -x "/opt/homebrew/bin/screenpipe" ]; then
        echo "/opt/homebrew/bin/screenpipe"
    elif [ -x "/usr/local/bin/screenpipe" ]; then
        echo "/usr/local/bin/screenpipe"
    elif command -v screenpipe &> /dev/null; then
        command -v screenpipe
    else
        echo ""
    fi
}

# NOTE: Penguin (menubar_app) is NEVER killed - it persists across restarts

# --- SCREENPIPE: Screen capture for clinical monitoring ---
echo -n "Screenpipe: "
if curl -s --connect-timeout 2 http://localhost:3030/health > /dev/null 2>&1; then
    echo -e "${GREEN}running${NC}"
else
    SCREENPIPE_BIN=$(find_screenpipe)
    if [ -z "$SCREENPIPE_BIN" ]; then
        echo -e "${YELLOW}not installed (optional) - brew install mediar-ai/screenpipe/screenpipe${NC}"
    else
        # Kill zombie processes
        if pgrep -x screenpipe > /dev/null 2>&1; then
            pkill -9 screenpipe 2>/dev/null
            pkill -9 -f "ffmpeg.*screenpipe" 2>/dev/null
            sleep 1
        fi

        echo -n "starting... "
        "$SCREENPIPE_BIN" --fps 1 > /tmp/screenpipe.log 2>&1 &

        if wait_for_service "http://localhost:3030/health" "Screenpipe" 15; then
            echo -e "${GREEN}ready${NC}"
        else
            echo -e "${YELLOW}failed - check /tmp/screenpipe.log${NC}"
        fi
    fi
fi

# --- OLLAMA ---
echo -n "Ollama: "
if curl -s --connect-timeout 2 http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo -e "${GREEN}running${NC}"
else
    if command -v ollama &> /dev/null; then
        echo -n "starting... "
        ollama serve > /tmp/ollama.log 2>&1 &
        if wait_for_service "http://localhost:11434/api/tags" "Ollama" 10; then
            echo -e "${GREEN}ready${NC}"
        else
            echo -e "${RED}failed${NC}"
        fi
    else
        echo -e "${RED}not installed - run: brew install ollama${NC}"
    fi
fi

# --- CLINICAL INSIGHT (bundled backend with vector DB) ---
CLINICAL_INSIGHT_DIR="$SCRIPT_DIR/clinical_insight_backend"
echo -n "Clinical Insight: "
if curl -s --connect-timeout 2 http://localhost:8001/health > /dev/null 2>&1; then
    echo -e "${GREEN}running${NC}"
else
    if [ -d "$CLINICAL_INSIGHT_DIR" ]; then
        echo -n "starting... "
        (
            cd "$CLINICAL_INSIGHT_DIR"
            if [ -f "venv/bin/activate" ]; then
                source venv/bin/activate
            fi
            python3 -m uvicorn app.main:app --port 8001 > /tmp/clinical-insight.log 2>&1 &
        )
        if wait_for_service "http://localhost:8001/health" "Clinical Insight" 10; then
            echo -e "${GREEN}ready${NC}"
        else
            echo -e "${YELLOW}failed - check /tmp/clinical-insight.log${NC}"
        fi
    else
        echo -e "${RED}not found${NC}"
    fi
fi

# --- NOTE CRITIQUE PORTAL (HTTP server) ---
echo -n "Note Critique Portal: "
if curl -s --connect-timeout 2 http://localhost:8080 > /dev/null 2>&1; then
    echo -e "${GREEN}running${NC}"
else
    # Start simple HTTP server for the portal
    (cd "$SCRIPT_DIR" && python3 -m http.server 8080 > /tmp/portal-server.log 2>&1 &)
    sleep 1
    if curl -s --connect-timeout 2 http://localhost:8080 > /dev/null 2>&1; then
        echo -e "${GREEN}ready at http://localhost:8080/note_critique_portal.html${NC}"
    else
        echo -e "${YELLOW}unavailable${NC}"
    fi
fi

# --- MENU BAR (penguin icon - NEVER terminated, only start if not running) ---
if ! pgrep -f "menubar_app" > /dev/null 2>&1; then
    nohup python3 -m clinical_copilot.ui.menubar_app > /tmp/menubar.log 2>&1 &
fi

# --- SERVICE WATCHDOG (keeps services running) ---
nohup python3 "$SCRIPT_DIR/service_watchdog.py" > /tmp/watchdog.log 2>&1 &

# --- CLINICAL MONITOR (Terminal popup with Rich formatting - auto-starts) ---
osascript -e "
tell application \"Terminal\"
    activate
    do script \"cd '$SCRIPT_DIR' && python3 simple_monitor.py\"
end tell
"

echo ""
echo "✓ Clinical Copilot monitoring started"
echo "✓ Penguin icon in menu bar"
echo "✓ Uses Clinical Insight with mistral:7b"
echo "✓ Press Ctrl+C in terminal to stop"
echo "✓ Note Critique Portal: http://localhost:8080/note_critique_portal.html"
