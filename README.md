# ClinicalCopilot

**Real-time Clinical Decision Support for Healthcare Providers**

ClinicalCopilot is a terminal-based AI assistant that monitors your clinical workflow and provides intelligent decision support. It runs 100% locally for PHI privacy, using Ollama for AI analysis and Screenpipe for screen capture.

## Features

- **Real-time Screen Monitoring** - Watches your EMR and clinical tools
- **Local AI Analysis** - All PHI stays on your device (Ollama)
- **Drug Interaction Checking** - Automatic medication safety alerts
- **Clinical Calculators** - GFR, MELD, Wells, CHA₂DS₂-VASc, and more
- **Learning Memory** - Remembers patterns and adapts to your preferences
- **Privacy Filters** - Excludes personal apps from monitoring
- **Clinical Insight Integration** - Deep case analysis when needed
- **Note Critique Portal** - Web-based clinical note review and feedback

## Installation

### Quick Install

```bash
git clone https://github.com/scalver/clinical-copilot.git
cd clinical-copilot
./install.sh
```

The installer will:
- Install Screenpipe and Ollama via Homebrew
- Download the llama3 model
- Install Python dependencies
- Set up auto-start on login
- Guide you through Screen Recording permissions

### Manual Install

```bash
git clone https://github.com/scalver/clinical-copilot.git
cd clinical-copilot
pip install -e .
brew install mediar-ai/screenpipe/screenpipe ollama
ollama pull llama3:latest
```

### Prerequisites

- macOS 12 (Monterey) or later
- Python 3.10+
- Homebrew
- [Ollama](https://ollama.com) - Local LLM runtime
- [Screenpipe](https://github.com/mediar-ai/screenpipe) - Screen capture

## Usage

### Quick Start

```bash
./start-copilot.sh
```

This starts all services and the menu bar app (🐧). Access the Note Critique Portal at:
http://localhost:8080/note_critique_portal.html

### Start Monitoring

```bash
# General medicine mode
copilot start

# Wound care mode
copilot start --mode wound-care

# Learning mode (adapts to your patterns)
copilot start --mode learning
```

### Check Drug Interactions

```bash
copilot interactions warfarin aspirin ibuprofen
```

### Run Clinical Calculators

```bash
copilot calc gfr_ckd_epi    # eGFR
copilot calc meld_score     # MELD/MELD-Na
copilot calc chadsvasc      # CHA₂DS₂-VASc
copilot calc wells_dvt      # Wells' DVT
copilot calc curb65         # CURB-65 pneumonia
```

### Analyze a Case

```bash
copilot analyze "72yo male with chest pain, diaphoresis, nausea. BP 90/60, HR 110"
```

### View History

```bash
copilot history             # Last 24 hours
copilot history --hours 48  # Last 48 hours
copilot search "potassium"  # Search encounters
```

### Configure Privacy

```bash
copilot config --list                    # List excluded apps
copilot config --exclude "Slack"         # Add app to exclusion
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         ClinicalCopilot                         │
│                     (Terminal Application)                      │
└─────────────────────────────┬───────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│  Screenpipe   │    │    Ollama     │    │    Memory     │
│  (Capture)    │    │  (Local LLM)  │    │   (SQLite)    │
└───────────────┘    └───────────────┘    └───────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│   Clinical    │    │     Drug      │    │   Clinical    │
│   Insight     │    │   Checker     │    │  Calculators  │
└───────────────┘    └───────────────┘    └───────────────┘
```

## Data & Privacy

- **All PHI stays local** - SQLite database in `~/.clinical-copilot/`
- **No cloud required** - Ollama runs entirely on your device
- **Privacy filters** - Banking, social media, personal email excluded by default
- **Optional integrations** - Clinical Insight API for deep analysis (your own deployment)

## Commands Reference

| Command | Description |
|---------|-------------|
| `copilot start` | Start monitoring |
| `copilot status` | Check system health |
| `copilot history` | View encounter history |
| `copilot search <query>` | Search encounters |
| `copilot analyze <text>` | Analyze clinical text |
| `copilot calc <calculator>` | Run clinical calculator |
| `copilot interactions <drugs>` | Check drug interactions |
| `copilot config` | Configure settings |
| `copilot learn` | Review alert feedback |

## License

MIT License - See LICENSE file for details.

## Disclaimer

This tool is for clinical decision **support** only. Always verify findings and use clinical judgment. This is not a substitute for professional medical training or established clinical protocols.
