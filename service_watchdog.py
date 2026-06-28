#!/usr/bin/env python3
"""Service Watchdog - ensures all Clinical Copilot services stay running."""

import subprocess
import time
import os
import httpx

SERVICES = {
    "screenpipe": {
        "health_url": "http://localhost:3030/health",
        "start_cmd": ["/usr/local/bin/screenpipe", "--fps", "1"],
        "log": "/tmp/screenpipe.log",
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

def check_service(name, config):
    """Check if service is healthy."""
    try:
        resp = httpx.get(config["health_url"], timeout=3.0)
        return resp.status_code == 200
    except:
        return False

def start_service(name, config):
    """Start a service."""
    print(f"Starting {name}...")

    if name == "clinical_insight":
        # Special handling for Clinical Insight
        backend_dir = "/Users/scalver/clinical-copilot-package/clinical_insight_backend"
        cmd = f"cd {backend_dir} && source venv/bin/activate && python3 -m uvicorn app.main:app --port 8001"
        subprocess.Popen(cmd, shell=True,
                        stdout=open(config["log"], "w"),
                        stderr=subprocess.STDOUT)
    elif config["start_cmd"]:
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
