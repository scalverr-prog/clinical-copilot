"""Menu bar app for Clinical Copilot."""

import subprocess
import threading
import time
import urllib.request
import urllib.error
import json
from pathlib import Path
import rumps


class CopilotMenuBar(rumps.App):
    """Menu bar app - click icon to toggle copilot."""

    PROJECT_DIR = Path(__file__).parent.parent.parent
    WATCHDOG_INTERVAL = 30  # Check every 30 seconds
    SCREENPIPE_URL = "http://localhost:3030/health"
    CLINICAL_INSIGHT_URL = "http://localhost:8001"

    # Animated spinner frames for processing
    SPINNER_FRAMES = ["🐧⏳", "🐧⌛", "🐧🔄", "🐧⏳", "🐧⌛", "🐧💭"]

    def __init__(self):
        super().__init__("🐧", quit_button=None)
        self.is_on = False
        self.process = None
        self.screenpipe_healthy = True
        self._watchdog_running = False
        self._animating = False

        # Menu items
        self.menu = [
            rumps.MenuItem("Start Copilot", callback=self.toggle),
            rumps.MenuItem("Submit Note", callback=self.submit_note),
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
        cmd = f"cd '{self.PROJECT_DIR}' && python3 -m clinical_copilot.main start"
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

    @rumps.clicked("Submit Note")
    def submit_note(self, _):
        """Open a window to submit a clinical note for analysis."""
        # Bring window to front
        subprocess.run(["osascript", "-e", 'tell application "System Events" to set frontmost of process "Python" to true'])

        # Get note from user via clipboard or dialog
        window = rumps.Window(
            message="🐧 Paste your clinical note below for analysis:\n\n(Analysis takes ~90 seconds on Intel Mac)",
            title="🐧 Clinical Copilot - Submit Note",
            default_text="",
            ok="Analyze",
            cancel="Cancel",
            dimensions=(500, 300)
        )
        response = window.run()

        if response.clicked and response.text.strip():
            note = response.text.strip()

            # Start animated spinner
            self._animating = True
            threading.Thread(target=self._animate_icon, daemon=True).start()

            # Show processing notification
            rumps.notification(
                "Clinical Copilot",
                "Analyzing note...",
                f"Processing {len(note)} characters. Result will popup when ready (~90 sec)"
            )

            # Run analysis in background thread
            threading.Thread(
                target=self._analyze_note,
                args=(note,),
                daemon=True
            ).start()

    def _animate_icon(self):
        """Animate the menu bar icon while processing."""
        frame = 0
        while self._animating:
            self.title = self.SPINNER_FRAMES[frame % len(self.SPINNER_FRAMES)]
            frame += 1
            time.sleep(0.5)

    def _analyze_note(self, note: str):
        """Send note to Clinical Insight API and display results."""
        import tempfile
        import time as t

        def log(msg):
            with open("/tmp/copilot_debug.log", "a") as f:
                f.write(f"{t.strftime('%H:%M:%S')} {msg}\n")

        try:
            import httpx
            log("Starting analysis...")

            start_time = t.time()

            # Create conversation
            log("Creating conversation...")
            with httpx.Client(timeout=10.0) as client:
                conv_resp = client.post(f"{self.CLINICAL_INSIGHT_URL}/api/chat/new")
                conv_id = conv_resp.json().get("conversation_id")
            log(f"Conversation: {conv_id}")

            # Send note for analysis (longer timeout for inference)
            log("Sending note for analysis...")
            with httpx.Client(timeout=300.0) as client:
                result = client.post(
                    f"{self.CLINICAL_INSIGHT_URL}/api/chat/message",
                    json={
                        "conversation_id": conv_id,
                        "message": f"Review this clinical note for safety concerns, drug interactions, and gaps:\n\n{note}"
                    }
                )
                analysis = result.json().get("response", "No response")
            log(f"Got response: {len(analysis)} chars")

            processing_time = int(t.time() - start_time)
            log(f"Processing time: {processing_time}s")

            # Stop animation and restore icon
            self._animating = False
            self.title = "🐧"

            # Write a Python script to display side-by-side output
            import base64
            note_b64 = base64.b64encode(note.encode()).decode()
            analysis_b64 = base64.b64encode(analysis.encode()).decode()
            log("Encoded note and analysis")

            script = f'''#!/usr/bin/env python3
import sys
import base64
sys.path.insert(0, "{self.PROJECT_DIR}")
from clinical_copilot.main import display_analysis_sidebyside

note = base64.b64decode("{note_b64}").decode()
analysis = base64.b64decode("{analysis_b64}").decode()
display_analysis_sidebyside(note, analysis, {processing_time})
input("\\nPress Enter to close...")
'''
            # Save script to fixed location (avoids temp file issues)
            script_path = "/tmp/copilot_analysis.py"
            with open(script_path, 'w') as f:
                f.write(script)
            log(f"Script saved to {script_path}")

            # Send notification with sound
            log("Sending notification...")
            rumps.notification(
                "🐧 Clinical Copilot",
                f"✅ Analysis complete! ({processing_time}s)",
                "🐧 Results ready - opening Terminal...",
                sound=True
            )

            # Play alert sound for extra attention
            subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"])

            # Open Terminal with formatted output and bring to front
            log("Opening Terminal...")
            cmd = f"cd /Users/scalver/clinical-copilot-package && python3 {script_path}"
            applescript = f'tell application "Terminal" to do script "{cmd}"'
            subprocess.run(["osascript", "-e", applescript])
            # Bring Terminal to front aggressively
            subprocess.run(["osascript", "-e", '''
                tell application "Terminal"
                    activate
                    set frontmost to true
                end tell
            '''])
            log("Done!")

        except Exception as e:
            log(f"ERROR: {e}")
            self._animating = False
            self.title = "🐧"
            rumps.notification(
                "🐧 Clinical Copilot",
                "❌ Analysis failed",
                str(e)[:100]
            )

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
