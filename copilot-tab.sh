#!/bin/bash
# Start Clinical Copilot floating tab
cd "$(dirname "$0")"
pkill -f "floating_tab" 2>/dev/null
sleep 1
python3 -m clinical_copilot.ui.floating_tab &
disown
echo "Copilot tab started - hover on right edge of screen"
