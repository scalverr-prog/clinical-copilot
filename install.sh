#!/bin/bash

# Clinical Copilot - Installation Script
# =======================================

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "=================================="
echo "  Clinical Copilot Installer"
echo "=================================="
echo ""

# Check macOS version
echo -e "${YELLOW}Checking system requirements...${NC}"
macos_version=$(sw_vers -productVersion | cut -d. -f1)
if [ "$macos_version" -lt 12 ]; then
    echo -e "${RED}Error: macOS 12 (Monterey) or later required${NC}"
    exit 1
fi
echo "  ✓ macOS version OK"

# Check for Homebrew
if ! command -v brew &> /dev/null; then
    echo -e "${RED}Error: Homebrew not found${NC}"
    echo "Install it with: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    exit 1
fi
echo "  ✓ Homebrew found"

# Check Python version
python_version=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d. -f1,2)
python_major=$(echo "$python_version" | cut -d. -f1)
python_minor=$(echo "$python_version" | cut -d. -f2)
if [ "$python_major" -lt 3 ] || ([ "$python_major" -eq 3 ] && [ "$python_minor" -lt 10 ]); then
    echo -e "${RED}Error: Python 3.10+ required (found $python_version)${NC}"
    exit 1
fi
echo "  ✓ Python $python_version found"

echo ""
echo -e "${YELLOW}Installing dependencies...${NC}"

# Install Screenpipe
echo ""
echo "Installing Screenpipe (screen capture)..."
if brew list screenpipe &>/dev/null; then
    echo "  ✓ Screenpipe already installed"
else
    brew tap mediar-ai/screenpipe 2>/dev/null || true
    brew install mediar-ai/screenpipe/screenpipe
    echo "  ✓ Screenpipe installed"
fi

# Install Ollama
echo ""
echo "Installing Ollama (local LLM)..."
if brew list ollama &>/dev/null; then
    echo "  ✓ Ollama already installed"
else
    brew install ollama
    echo "  ✓ Ollama installed"
fi

# Start Ollama service
echo ""
echo "Starting Ollama service..."
pkill ollama 2>/dev/null || true
ollama serve &>/dev/null &
sleep 2
echo "  ✓ Ollama service started"

# Pull LLM model
echo ""
echo "Pulling llama3 model (this may take a while)..."
if ollama list | grep -q "llama3:latest"; then
    echo "  ✓ llama3:latest already downloaded"
else
    ollama pull llama3:latest
    echo "  ✓ llama3:latest downloaded"
fi

# Install Python packages
echo ""
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    echo "Installing Python packages..."
    pip3 install -r "$SCRIPT_DIR/requirements.txt"
    echo "  ✓ Python packages installed"
else
    echo -e "${YELLOW}Note: requirements.txt not found, skipping Python packages${NC}"
fi

# Create data directories
echo ""
echo "Creating data directories..."
mkdir -p ~/.clinical-copilot/rag_db
mkdir -p ~/.clinical-copilot/logs
echo "  ✓ Data directories created"

# Setup auto-start on login using AppleScript app + Login Items
echo ""
echo "Setting up auto-start on login..."
mkdir -p ~/Applications

# Create AppleScript app wrapper
APP_PATH="$HOME/Applications/ClinicalCopilot.app"
osacompile -o "$APP_PATH" -e "do shell script \"$SCRIPT_DIR/start-copilot.sh > /tmp/clinical-copilot.log 2>&1 &\""

# Remove old LaunchAgent if exists
launchctl unload "$HOME/Library/LaunchAgents/com.clinical.copilot.plist" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/com.clinical.copilot.plist" 2>/dev/null || true

# Add to Login Items (remove first to avoid duplicates)
osascript -e 'tell application "System Events" to delete (every login item whose name is "ClinicalCopilot")' 2>/dev/null || true
osascript -e "tell application \"System Events\" to make login item at end with properties {path:\"$APP_PATH\", hidden:false}"

echo "  ✓ Auto-start enabled (copilot starts on login)"

# Setup permissions
echo ""
echo -e "${YELLOW}Setting up permissions...${NC}"
echo ""
echo "Screenpipe needs Screen Recording permission to capture clinical apps."
echo ""
echo "Please add BOTH of these to Screen Recording and enable them:"
echo "  1. screenpipe"
echo "  2. ClinicalCopilot (in ~/Applications)"
echo ""
open "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
echo ""
read -p "Press Enter after you've enabled both in Screen Recording..."
echo "  ✓ Permissions configured"

echo ""
echo -e "${GREEN}=================================="
echo "  Installation Complete!"
echo "==================================${NC}"
echo ""
echo "To start now:"
echo "  ./start-copilot.sh"
echo ""
echo "Or open the app:"
echo "  open ~/Applications/ClinicalCopilot.app"
echo ""
echo "The copilot will start automatically on login."
echo ""
echo "To disable auto-start:"
echo "  Go to System Settings > General > Login Items"
echo "  Remove 'ClinicalCopilot' from the list"
echo ""
