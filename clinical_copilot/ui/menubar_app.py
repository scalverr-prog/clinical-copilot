"""Menu bar app for Clinical Copilot."""

import subprocess
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
import rumps


class CopilotMenuBar(rumps.App):
    """Menu bar app - click icon to toggle copilot."""

    PROJECT_DIR = Path(__file__).parent.parent.parent
    WATCHDOG_INTERVAL = 30  # Check every 30 seconds
    SCREENPIPE_URL = "http://localhost:3030/health"

    def __init__(self):
        super().__init__("🐧", quit_button=None)
        self.is_on = False
        self.process = None
        self.screenpipe_healthy = True
        self._watchdog_running = False

        # Menu items
        self.menu = [
            rumps.MenuItem("Start Copilot", callback=self.toggle),
            None,  # Separator
            rumps.MenuItem("Status", callback=self.show_status),
            None,
            rumps.MenuItem("Quit", callback=self.quit_app)
        ]

        self._update_icon()

    @rumps.clicked("Start Copilot")
    def toggle(self, sender):
        if self.is_on:
            self._stop()
            sender.title = "Start Copilot"
        else:
            self._start()
            sender.title = "Stop Copilot"

    def _check_screenpipe_health(self) -> bool:
        """Check if Screenpipe HTTP server is responding."""
        try:
            req = urllib.request.Request(self.SCREENPIPE_URL, method='GET')
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def _restart_screenpipe(self):
        """Kill and restart Screenpipe with proper cleanup."""
        # Kill existing processes
        subprocess.run(["pkill", "-9", "screenpipe"], capture_output=True)
        subprocess.run(["pkill", "-9", "-f", "ffmpeg.*\\.screenpipe/data"], capture_output=True)
        time.sleep(1)

        # Start fresh
        subprocess.Popen(
            ["/usr/local/bin/screenpipe", "--fps", "1"],
            stdout=open("/tmp/screenpipe.log", "w"),
            stderr=subprocess.STDOUT
        )

        # Wait for HTTP server
        for _ in range(15):
            time.sleep(1)
            if self._check_screenpipe_health():
                return True
        return False

    def _watchdog_loop(self):
        """Background watchdog that monitors Screenpipe health."""
        while self._watchdog_running:
            time.sleep(self.WATCHDOG_INTERVAL)
            if not self._watchdog_running:
                break

            was_healthy = self.screenpipe_healthy
            self.screenpipe_healthy = self._check_screenpipe_health()

            if not self.screenpipe_healthy:
                # Screenpipe died - attempt recovery
                rumps.notification(
                    "Clinical Copilot",
                    "Screen capture lost",
                    "Attempting to restart Screenpipe..."
                )
                self._update_icon()

                if self._restart_screenpipe():
                    self.screenpipe_healthy = True
                    self._update_icon()
                    rumps.notification(
                        "Clinical Copilot",
                        "Recovered",
                        "Screen capture restored"
                    )
                else:
                    rumps.notification(
                        "Clinical Copilot",
                        "Recovery failed",
                        "Check System Settings > Privacy > Screen Recording"
                    )
            elif not was_healthy and self.screenpipe_healthy:
                # Recovered externally
                self._update_icon()

    def _start(self):
        """Start copilot."""
        self.is_on = True
        self._update_icon()

        rumps.notification(
            "Clinical Copilot",
            "Starting...",
            "Monitoring your clinical workflow"
        )

        # Start screenpipe with proper health verification
        if not self._check_screenpipe_health():
            self._restart_screenpipe()
        self.screenpipe_healthy = self._check_screenpipe_health()

        # Start watchdog thread
        self._watchdog_running = True
        threading.Thread(target=self._watchdog_loop, daemon=True).start()

        # Open terminal with copilot
        cmd = f"cd '{self.PROJECT_DIR}' && python3 -m clinical_copilot.main on"
        script = f'tell application "Terminal" to do script "{cmd}"'
        subprocess.run(["osascript", "-e", script])
        subprocess.run(["osascript", "-e", 'tell application "Terminal" to activate'])

    def _stop(self):
        """Stop copilot."""
        # Stop watchdog first
        self._watchdog_running = False

        subprocess.run(["pkill", "-f", "clinical_copilot.main"], capture_output=True)
        subprocess.run(["pkill", "-f", "screenpipe"], capture_output=True)

        self.is_on = False
        self._update_icon()

        rumps.notification(
            "Clinical Copilot",
            "Stopped",
            "Monitoring disabled"
        )

    def _update_icon(self):
        """Update menu bar icon based on state."""
        if self.is_on:
            if self.screenpipe_healthy:
                self.title = "🐧"  # Running and healthy
            else:
                self.title = "🐧💤"  # Running but degraded
        else:
            self.title = "🐧"  # Stopped (same icon, menu shows state)

    @rumps.clicked("Status")
    def show_status(self, _):
        result = subprocess.run(
            ["python3", "-m", "clinical_copilot.main", "status"],
            cwd=str(self.PROJECT_DIR),
            capture_output=True,
            text=True
        )
        rumps.alert("Copilot Status", result.stdout[:500] if result.stdout else "Status check complete")

    @rumps.clicked("Quit")
    def quit_app(self, _):
        if self.is_on:
            self._stop()
        rumps.quit_application()


def main():
    CopilotMenuBar().run()


if __name__ == "__main__":
    main()
