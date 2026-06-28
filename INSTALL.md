# Clinical Copilot - Installation Guide

## Requirements

- macOS 12+ (Monterey or later)
- Python 3.10+
- Homebrew

## Quick Install

```bash
./install.sh
```

## Manual Install

### 1. Install Dependencies

```bash
# Install Screenpipe (screen capture)
brew install mediar-ai/screenpipe/screenpipe

# Install Ollama (local LLM)
brew install ollama

# Pull the LLM model
ollama pull llama3:latest

# Install Python packages
pip3 install -r requirements.txt
```

### 2. Grant Permissions

- **Screen Recording**: System Preferences → Privacy & Security → Screen Recording → Enable for Terminal/Python
- **Accessibility**: May be needed for some features

### 3. Start Services

```bash
# Start Ollama
ollama serve &

# Start the floating tab
./copilot-tab.sh
```

## Usage

### Floating Tab
- Hover on right edge of screen → tab slides in
- Click "C" → starts copilot, expands terminal portal
- Click again → stops copilot

### Commands (type in the input field)

| Command | Action |
|---------|--------|
| `paste to note` | Paste clipboard to Apple Notes |
| `open <app>` | Open any application |
| `search <query>` | Google search |
| `screenshot` | Capture screen to clipboard |
| `timeline` | Show patient timeline |
| `history <query>` | Search historical data |
| `trend <topic>` | Analyze trends |
| `context` | Show current memory |
| `rag stats` | Show storage stats |

### Patient Safety
- Auto-detects patient from MRN/name on screen
- Alerts when patient changes
- Keeps separate context per patient
- Never mixes patient data

## Data Storage

- RAG database: `~/.clinical-copilot/rag_db/`
- Memory database: `~/.clinical-copilot/memory.db`
- Logs: `~/.clinical-copilot/logs/`

## Troubleshooting

### Screenpipe not working
```bash
# Check if running
curl http://localhost:3030/health

# Restart
pkill screenpipe && screenpipe &
```

### Ollama not responding
```bash
# Check if running
curl http://localhost:11434/api/tags

# Restart
pkill ollama && ollama serve &
```

### Tab not appearing
```bash
# Kill and restart
pkill -f floating_tab
./copilot-tab.sh
```
