#!/usr/bin/env python3
"""Simple Clinical Monitor - reliable extraction and display."""

import time
import httpx
import re
import subprocess
import os
import signal
import sys
from rich.console import Console
from rich.panel import Panel

console = Console()

# Exit cleanly when Terminal window is closed
def handle_exit(signum, frame):
    console.print("\n[dim]Monitor stopped.[/dim]")
    sys.exit(0)

signal.signal(signal.SIGHUP, handle_exit)  # Terminal closed
signal.signal(signal.SIGTERM, handle_exit)  # Kill signal

# Track last restart attempts to prevent spam
_last_screenpipe_restart = 0
_last_clinical_insight_restart = 0
RESTART_COOLDOWN = 30  # seconds between restart attempts

def is_process_running(name):
    """Check if a process is running."""
    try:
        result = subprocess.run(["pgrep", "-f", name], capture_output=True)
        return result.returncode == 0
    except:
        return False

def ensure_services():
    """Ensure services are running. Smart checks with cooldown."""
    global _last_screenpipe_restart, _last_clinical_insight_restart
    now = time.time()

    # Check Screenpipe (2s timeout, respects cooldown)
    try:
        httpx.get("http://localhost:3030/health", timeout=2.0)
    except:
        if now - _last_screenpipe_restart > RESTART_COOLDOWN:
            if not is_process_running("screenpipe"):
                console.print("[yellow]Starting Screenpipe...[/yellow]")
                subprocess.Popen(["/usr/local/bin/screenpipe", "--fps", "1"],
                                stdout=open("/tmp/screenpipe.log", "w"),
                                stderr=subprocess.STDOUT)
                _last_screenpipe_restart = now

    # Check Clinical Insight (2s timeout, respects cooldown)
    try:
        httpx.get("http://localhost:8001/health", timeout=2.0)
    except:
        if now - _last_clinical_insight_restart > RESTART_COOLDOWN:
            if not is_process_running("uvicorn app.main:app --port 8001"):
                console.print("[yellow]Starting Clinical Insight...[/yellow]")
                backend_dir = "/Users/scalver/clinical-copilot-package/clinical_insight_backend"
                cmd = f"cd {backend_dir} && source venv/bin/activate && python3 -m uvicorn app.main:app --port 8001"
                subprocess.Popen(cmd, shell=True,
                                stdout=open("/tmp/clinical-insight.log", "w"),
                                stderr=subprocess.STDOUT)
                _last_clinical_insight_restart = now

def get_screen_text():
    """Get current screen text from Screenpipe."""
    try:
        resp = httpx.get("http://localhost:3030/search",
                        params={"content_type": "ocr", "limit": 10},
                        timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            for item in data.get("data", []):
                text = item.get("content", {}).get("text", "")
                app = item.get("content", {}).get("app_name", "")
                if len(text) > 50 and "Terminal" not in app and "Control" not in app:
                    return text, app
    except Exception as e:
        console.print(f"[red]Screenpipe error: {e}[/red]")
    return None, None

def extract_clinical_data(text):
    """Extract critical clinical data points."""
    findings = {}

    # ICD codes
    icd_codes = re.findall(r'\b[A-Z]\d{2,3}\.?\d{0,2}\b', text)
    if icd_codes:
        findings['ICD Codes'] = list(set(icd_codes))[:5]

    # Patient demographics
    age_match = re.search(r'(\d{1,3})[-\s]?(?:yo|y/?o|year)', text, re.I)
    if age_match:
        findings['Age'] = age_match.group(1)

    sex_match = re.search(r'\b(male|female|M|F)\b', text, re.I)
    if sex_match:
        findings['Sex'] = sex_match.group(1)

    # Diagnoses
    dx_patterns = [
        r'(?:diabetes|DM|T1DM|T2DM)',
        r'(?:ulcer|DFU|wound)',
        r'(?:hypertension|HTN)',
        r'(?:CHF|heart failure)',
        r'(?:CKD|kidney disease)',
        r'(?:infection|cellulitis|osteomyelitis)',
    ]
    dx_found = []
    for pattern in dx_patterns:
        if re.search(pattern, text, re.I):
            match = re.search(pattern, text, re.I)
            dx_found.append(match.group(0))
    if dx_found:
        findings['Diagnoses'] = dx_found

    # Medications
    med_patterns = r'\b(bactrim|metformin|insulin|warfarin|aspirin|lisinopril|metoprolol|gabapentin|prednisone)\b'
    meds = re.findall(med_patterns, text, re.I)
    if meds:
        findings['Medications'] = list(set(meds))

    # Labs ordered
    lab_patterns = r'(?:HbA1c|A1C|CBC|CMP|BMP|ESR|CRP|wound culture|blood culture|x-ray|MRI)'
    labs = re.findall(lab_patterns, text, re.I)
    if labs:
        findings['Labs/Imaging'] = list(set(labs))

    # Critical concerns
    concerns = []
    if re.search(r'(?:necrotic|necrosis|gangrene)', text, re.I):
        concerns.append("NECROTIC TISSUE")
    if re.search(r'(?:fever|sepsis|infection|cellulitis)', text, re.I):
        concerns.append("INFECTION RISK")
    if re.search(r'(?:plantar|heel|forefoot)', text, re.I) and re.search(r'(?:ulcer|DFU)', text, re.I):
        concerns.append("OSTEOMYELITIS RISK")
    if re.search(r'(?:osteomyelitis|probe-to-bone)', text, re.I):
        concerns.append("OSTEOMYELITIS WORKUP")
    if re.search(r'(?:vascular|ABI|ischemia|perfusion)', text, re.I):
        concerns.append("VASCULAR ASSESSMENT")
    if re.search(r'(?:HBOT|hypoxia|TcPO2)', text, re.I):
        concerns.append("HYPOXIA/HBOT")
    if re.search(r'(?:off-?loading|TCC|total.?contact)', text, re.I):
        concerns.append("OFFLOADING NEEDED")
    if re.search(r'(?:vitals.*not documented|no vitals)', text, re.I):
        concerns.append("MISSING VITALS")
    if concerns:
        findings['CONCERNS'] = concerns

    # Clinical recommendations extracted
    recs = []
    if re.search(r'consider.*vascular', text, re.I):
        recs.append("Vascular surgery referral")
    if re.search(r'consider.*MRI|obtain.*MRI', text, re.I):
        recs.append("MRI for osteomyelitis")
    if re.search(r'consider.*HBOT', text, re.I):
        recs.append("HBOT if hypoxia documented")
    if re.search(r'consider.*graft|consider.*CTP', text, re.I):
        recs.append("Graft/CTP after wound bed ready")
    if recs:
        findings['RECOMMENDATIONS'] = recs

    return findings

def main():
    console.print(Panel.fit(
        "[bold cyan]CLINICAL COPILOT - SIMPLE MONITOR[/bold cyan]\n"
        "Continuously extracts clinical context from screen\n"
        "[dim]Auto-starts services if needed[/dim]",
        border_style="cyan"
    ))

    # Ensure services are running (auto-start if needed)
    ensure_services()

    # Verify services
    try:
        httpx.get("http://localhost:3030/health", timeout=2.0)
        console.print("[green]✓ Screenpipe ready[/green]")
    except:
        console.print("[red]✗ Screenpipe failed to start[/red]")
        return

    try:
        httpx.get("http://localhost:8001/health", timeout=2.0)
        console.print("[green]✓ Clinical Insight ready[/green]")
    except:
        console.print("[yellow]○ Clinical Insight not available - extraction only[/yellow]")

    console.print("\n[dim]Monitoring... Press Ctrl+C to stop[/dim]\n")

    last_text = ""
    scan = 0

    try:
        while True:
            scan += 1
            time_str = time.strftime("%H:%M:%S")

            # Check services only every 30 seconds (not every scan)
            if scan % 30 == 1:
                ensure_services()

            # Show scanning every 10 seconds
            if scan % 10 == 1:
                console.print(f"[dim]{time_str} Scanning...[/dim]")

            text, app = get_screen_text()

            if text and text != last_text:
                last_text = text
                console.print(f"\n[green]{time_str} Content from: {app}[/green]")

                # Extract clinical data
                findings = extract_clinical_data(text)

                if findings:
                    console.print("[bold cyan]── EXTRACTED DATA ──[/bold cyan]")
                    for key, value in findings.items():
                        if key == "CONCERNS":
                            console.print(f"[bold red]⚠️ {key}: {value}[/bold red]")
                        else:
                            console.print(f"  {key}: {value}")
                    console.print()
                else:
                    console.print("[dim]  (No clinical data extracted)[/dim]")

            time.sleep(1)

    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")

if __name__ == "__main__":
    main()
