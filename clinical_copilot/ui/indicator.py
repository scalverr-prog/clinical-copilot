"""Simple status indicator for ClinicalCopilot."""

import subprocess
import sys
from typing import Optional


class FloatingIndicator:
    """Simple status indicator using macOS notifications."""

    def __init__(self):
        self._running = False
        self._alert_count = 0

    def start(self):
        """Show startup notification."""
        self._running = True
        self._notify(
            "ClinicalCopilot Active",
            "Monitoring your clinical workflow. Check terminal for details."
        )

    def stop(self):
        """Show stop notification."""
        self._running = False
        self._notify(
            "ClinicalCopilot Stopped",
            f"Session ended. {self._alert_count} alerts generated."
        )

    def update_status(self, status: str):
        """Update status (no-op for simple version)."""
        pass

    def update_alerts(self, count: int):
        """Update alert count."""
        self._alert_count = count

    def show_alert(self, title: str, message: str):
        """Show a macOS notification for important alerts."""
        self._notify(title, message)

    def _notify(self, title: str, message: str):
        """Send a macOS notification."""
        if sys.platform == "darwin":
            try:
                subprocess.run([
                    "osascript", "-e",
                    f'display notification "{message}" with title "{title}"'
                ], capture_output=True, timeout=5)
            except Exception:
                pass  # Silently fail if notifications don't work
