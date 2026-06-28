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

# Kill old menu bar
pkill -f "menubar_app" 2>/dev/null || true

# --- SCREENPIPE: Full health verification ---
echo -n "Screenpipe: "
if curl -s --connect-timeout 2 http://localhost:3030/health > /dev/null 2>&1; then
    echo -e "${GREEN}running${NC}"
else
    SCREENPIPE_BIN=$(find_screenpipe)
    if [ -z "$SCREENPIPE_BIN" ]; then
        echo -e "${RED}not installed - run: brew install mediar-ai/screenpipe/screenpipe${NC}"
    else
        # Process exists but HTTP not responding = zombie state
        if pgrep -x screenpipe > /dev/null 2>&1; then
            echo -e "${YELLOW}zombie (restarting)${NC}"
            pkill -9 screenpipe 2>/dev/null
            pkill -9 -f "ffmpeg.*screenpipe" 2>/dev/null
            sleep 1
        else
            echo -n "starting... "
        fi

        # Clean up any orphaned ffmpeg processes from screenpipe
        pkill -9 -f "ffmpeg.*\.screenpipe/data" 2>/dev/null || true

        # Start fresh
        "$SCREENPIPE_BIN" --fps 1 > /tmp/screenpipe.log 2>&1 &

        # Wait for HTTP server to actually respond
        if wait_for_service "http://localhost:3030/health" "Screenpipe" 15; then
            echo -e "${GREEN}ready${NC}"
        else
            echo -e "${RED}failed to start - check /tmp/screenpipe.log${NC}"
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

# --- CLINICAL INSIGHT (optional - only if installed locally) ---
CLINICAL_INSIGHT_DIR="$HOME/clinical-insight/backend"
if [ -d "$CLINICAL_INSIGHT_DIR" ]; then
    echo -n "Clinical Insight: "
    if curl -s --connect-timeout 2 http://localhost:8001/health > /dev/null 2>&1; then
        echo -e "${GREEN}running${NC}"
    else
        echo -n "starting... "
        (
            cd "$CLINICAL_INSIGHT_DIR"
            if [ -f "venv/bin/activate" ]; then
                source venv/bin/activate
                uvicorn app.main:app --port 8001 > /tmp/clinical-insight.log 2>&1 &
            fi
        )
        if wait_for_service "http://localhost:8001/health" "Clinical Insight" 10; then
            echo -e "${GREEN}ready${NC}"
        else
            echo -e "${YELLOW}unavailable (optional)${NC}"
        fi
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

# --- MENU BAR ---
nohup python3 -m clinical_copilot.ui.menubar_app > /tmp/menubar.log 2>&1 &

echo ""
echo "✓ Copilot ready - click 🐧 in menu bar"
echo "✓ Note Critique Portal: http://localhost:8080/note_critique_portal.html"
