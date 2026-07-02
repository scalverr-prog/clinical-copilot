#!/usr/bin/env python3
"""Service Watchdog - ensures all Clinical Copilot services stay running."""

import subprocess
import time
import os
import signal
from datetime import datetime, timezone
import httpx

SERVICES = {
    "screenpipe": {
        "health_url": "http://localhost:3030/health",
        "start_cmd": ["/usr/local/bin/screenpipe", "--fps", "1", "--disable-audio"],
        "alt_start_cmd": ["/opt/homebrew/bin/screenpipe", "--fps", "1", "--disable-audio"],  # Apple Silicon
        "log": "/tmp/screenpipe.log",
        "stale_check": True,  # Also check for stale data
        "max_stale_seconds": 60,  # Restart if no new captures for 60 seconds
    },
    "clinical_insight": {
        "health_url": "http://localhost:8001/health",
        "start_cmd": None,  # Special handling
        "log": "/tmp/clinical-insight.log",
    },
    "ollama": {
        "health_url": "http://localhost:11434/api/tags",
        "start_cmd": ["ollama", "serve"],
        "log": "/tmp/ollama.log",
    },
}

def check_screenpipe_freshness():
    """Check if screenpipe is actually capturing fresh data."""
    try:
        resp = httpx.get("http://localhost:3030/search",
                        params={"content_type": "ocr", "limit": 1},
                        timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("data"):
                ts_str = data["data"][0].get("content", {}).get("timestamp", "")
                if ts_str:
                    # Parse timestamp and check age
                    capture_time = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc)
                    age_seconds = (now - capture_time).total_seconds()
                    return age_seconds
        return 9999  # Return large number if can't determine
    except Exception as e:
        return 9999

def kill_screenpipe():
    """Force kill screenpipe and related processes."""
    subprocess.run(["pkill", "-9", "screenpipe"], capture_output=True)
    subprocess.run(["pkill", "-9", "-f", "ffmpeg.*screenpipe"], capture_output=True)
    time.sleep(2)

def check_service(name, config):
    """Check if service is healthy."""
    try:
        resp = httpx.get(config["health_url"], timeout=3.0)
        if resp.status_code != 200:
            return False

        # For screenpipe, also check freshness
        if name == "screenpipe" and config.get("stale_check"):
            age = check_screenpipe_freshness()
            max_stale = config.get("max_stale_seconds", 60)
            if age > max_stale:
                print(f"[{time.strftime('%H:%M:%S')}] Screenpipe data is {int(age)}s old (max {max_stale}s) - STALE")
                return False

        return True
    except:
        return False

def start_service(name, config):
    """Start a service."""
    print(f"[{time.strftime('%H:%M:%S')}] Starting {name}...")

    if name == "screenpipe":
        # Force kill first to clean up any zombie processes
        kill_screenpipe()

        # Try primary command, then alt command
        start_cmd = config["start_cmd"]
        if not os.path.exists(start_cmd[0]):
            start_cmd = config.get("alt_start_cmd", start_cmd)

        subprocess.Popen(start_cmd,
                        stdout=open(config["log"], "w"),
                        stderr=subprocess.STDOUT)
        time.sleep(5)  # Give screenpipe more time to start

    elif name == "clinical_insight":
        # Special handling for Clinical Insight
        backend_dir = "/Users/scalver/clinical-copilot-package/clinical_insight_backend"
        cmd = f"cd {backend_dir} && source venv/bin/activate && python3 -m uvicorn app.main:app --port 8001"
        subprocess.Popen(cmd, shell=True,
                        stdout=open(config["log"], "w"),
                        stderr=subprocess.STDOUT)
        time.sleep(3)

    elif config.get("start_cmd"):
        subprocess.Popen(config["start_cmd"],
                        stdout=open(config["log"], "w"),
                        stderr=subprocess.STDOUT)
        time.sleep(3)

    return check_service(name, config)

def main():
    print("=" * 50)
    print("CLINICAL COPILOT SERVICE WATCHDOG")
    print("Keeping all services running...")
    print("=" * 50)
    print()

    while True:
        for name, config in SERVICES.items():
            if not check_service(name, config):
                print(f"[{time.strftime('%H:%M:%S')}] {name} is DOWN - restarting...")
                if start_service(name, config):
                    print(f"[{time.strftime('%H:%M:%S')}] {name} restarted successfully")
                else:
                    print(f"[{time.strftime('%H:%M:%S')}] {name} failed to start")

        time.sleep(10)  # Check every 10 seconds

if __name__ == "__main__":
    main()
