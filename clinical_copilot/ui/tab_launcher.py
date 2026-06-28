#!/usr/bin/env python3
"""Standalone launcher for the ClinicalCopilot floating tab."""

import subprocess
import sys
from pathlib import Path


def ensure_screenpipe():
    """Ensure screenpipe is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "screenpipe"],
            capture_output=True
        )
        if result.returncode != 0:
            print("Starting Screenpipe...")
            subprocess.Popen(
                ["screenpipe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            print("Screenpipe started.")
    except Exception as e:
        print(f"Warning: Could not start Screenpipe: {e}")


def main():
    """Launch the floating tab."""
    # Ensure we're in the right directory
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

    # Ensure screenpipe is running
    ensure_screenpipe()

    # Import and run the floating tab
    from clinical_copilot.ui.floating_tab import FloatingTab

    print("Starting ClinicalCopilot floating tab...")
    print("Click the tab to toggle copilot ON/OFF")
    print("Right-click for menu")
    print("Drag to reposition")

    tab = FloatingTab()
    tab.run()


if __name__ == "__main__":
    main()
