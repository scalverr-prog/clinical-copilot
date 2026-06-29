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
    """Get current screen text from Screenpipe - find first valid clinical content."""
    try:
        resp = httpx.get("http://localhost:3030/search",
                        params={"content_type": "ocr", "limit": 5},
                        timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            for item in data.get("data", []):
                text = item.get("content", {}).get("text", "")
                app = item.get("content", {}).get("app_name", "")
                # Skip empty, Terminal, Control Center, and Claude
                if len(text) > 50 and "Terminal" not in app and "Control" not in app and "Claude" not in app:
                    return text, app
    except Exception as e:
        console.print(f"[red]Screenpipe error: {e}[/red]")
    return None, None

def get_clinical_interpretation(text, findings):
    """Send to Clinical Insight for LLM analysis and interpretation."""
    try:
        # Quick health check first
        try:
            httpx.get("http://localhost:8001/health", timeout=2.0)
        except:
            return None

        # Format the findings into a clinical prompt
        findings_summary = []
        for key, value in findings.items():
            if key == "CONCERNS":
                findings_summary.append(f"⚠️ CONCERNS: {', '.join(value)}")
            else:
                findings_summary.append(f"• {key}: {value}")

        prompt = f"""You are a clinical detective. Your job is to find ERRORS, INCONSISTENCIES, and OVERLOOKED problems that a busy clinician might miss.

CLINICAL DATA:
{chr(10).join(findings_summary)}

TEXT:
{text[:2000]}

Find and report ONLY things that DON'T ADD UP:

• CONTRADICTIONS - Symptoms that contradict each other or the diagnosis
  (e.g., "seizure" but patient conversant and not post-ictal = not a true seizure)

• DOESN'T FIT - Findings that don't match the stated diagnosis
  (e.g., "cellulitis" but no warmth, erythema, or tenderness documented)

• OVERLOOKED CLUES - Symptoms mentioned but not addressed in the plan
  (e.g., patient has chest pain but no EKG ordered, or fever but no cultures)

• MATH ERRORS - Wrong dosing, weights, or calculations
  (e.g., creatinine clearance not adjusted for renal dosing)

• MISSING LOGIC - Steps skipped in clinical reasoning
  (e.g., started antibiotics without identifying source of infection)

Be a skeptic. If something seems off, call it out. If everything is consistent and logical, say "No inconsistencies found."

Do NOT give generic advice. Only report specific problems you found in THIS case."""

        # Create conversation
        resp = httpx.post("http://localhost:8001/api/chat/new", timeout=10.0)
        if resp.status_code != 200:
            return None
        conv_id = resp.json().get("conversation_id")

        # Get interpretation (5 min timeout for LLM on Intel Mac CPU)
        result = httpx.post(
            "http://localhost:8001/api/chat/message",
            json={"conversation_id": conv_id, "message": prompt},
            timeout=300.0
        )
        if result.status_code == 200:
            return result.json().get("response")
    except Exception as e:
        console.print(f"[dim]  (Interpretation unavailable: {e})[/dim]")
    return None


def extract_clinical_data(text):
    """Extract critical clinical data points."""
    findings = {}
    concerns = []

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

    # VITALS - critical to extract
    vitals = {}
    temp = re.search(r'T[:\s]*(\d{2,3}\.?\d?)°?[CF]', text)
    if temp:
        vitals['Temp'] = temp.group(1)
        if float(temp.group(1)) > 38.0:
            concerns.append("🔥 FEVER")

    hr = re.search(r'HR[:\s]*(\d{2,3})\s*(?:bpm)?', text, re.I)
    if hr:
        vitals['HR'] = hr.group(1)
        if int(hr.group(1)) > 100:
            concerns.append("⚡ TACHYCARDIA")

    bp = re.search(r'BP[:\s]*(\d{2,3})/(\d{2,3})', text, re.I)
    if bp:
        vitals['BP'] = f"{bp.group(1)}/{bp.group(2)}"
        if int(bp.group(1)) < 100:
            concerns.append("⬇️ HYPOTENSION")

    spo2 = re.search(r'SpO2?[:\s]*(\d{2,3})%?', text, re.I)
    if spo2:
        vitals['SpO2'] = spo2.group(1) + "%"
        if int(spo2.group(1)) < 94:
            concerns.append("🫁 LOW O2")

    if vitals:
        findings['Vitals'] = vitals

    # WOUND measurements
    wound = re.search(r'(\d+\.?\d*)\s*[x×]\s*(\d+\.?\d*)\s*[x×]?\s*(\d+\.?\d*)?\s*cm', text, re.I)
    if wound:
        if wound.group(3):
            findings['Wound Size'] = f"{wound.group(1)} x {wound.group(2)} x {wound.group(3)} cm"
        else:
            findings['Wound Size'] = f"{wound.group(1)} x {wound.group(2)} cm"

    # Wound composition
    gran = re.search(r'(\d+)%\s*granulation', text, re.I)
    slough = re.search(r'(\d+)%\s*slough', text, re.I)
    if gran or slough:
        comp = []
        if gran: comp.append(f"{gran.group(1)}% granulation")
        if slough: comp.append(f"{slough.group(1)}% slough")
        findings['Wound Bed'] = ", ".join(comp)

    # ALLERGIES
    allergy = re.search(r'(?:allerg(?:y|ies)|NKA)[:\s]*([^.•\n]+)', text, re.I)
    if allergy and 'no known' not in allergy.group(1).lower():
        findings['Allergies'] = allergy.group(1).strip()[:50]

    # Diagnoses
    dx_patterns = [
        r'(?:diabetes|DM|T1DM|T2DM)',
        r'(?:ulcer|DFU|wound)',
        r'(?:hypertension|HTN)',
        r'(?:CHF|heart failure)',
        r'(?:CKD|kidney disease)',
        r'(?:infection|cellulitis|osteomyelitis)',
        r'(?:sepsis|SIRS)',
    ]
    dx_found = []
    for pattern in dx_patterns:
        if re.search(pattern, text, re.I):
            match = re.search(pattern, text, re.I)
            dx_found.append(match.group(0))
    if dx_found:
        findings['Diagnoses'] = list(set(dx_found))

    # Medications
    med_patterns = r'\b(bactrim|metformin|insulin|warfarin|aspirin|lisinopril|metoprolol|gabapentin|prednisone|vancomycin|zosyn|cipro|doxycycline)\b'
    meds = re.findall(med_patterns, text, re.I)
    if meds:
        findings['Medications'] = list(set(meds))

    # Labs ordered
    lab_patterns = r'(?:HbA1c|A1C|CBC|CMP|BMP|ESR|CRP|wound culture|blood culture|x-ray|MRI|CT|cultures?)'
    labs = re.findall(lab_patterns, text, re.I)
    if labs:
        findings['Labs/Imaging'] = list(set(labs))

    # Additional critical concerns (add to existing list from vitals)
    if re.search(r'(?:necrotic|necrosis|gangrene)', text, re.I):
        concerns.append("⚫ NECROTIC TISSUE")
    if re.search(r'(?:sepsis|SIRS)', text, re.I):
        concerns.append("🚨 SEPSIS RISK")
    if re.search(r'(?:infected|infection|cellulitis)', text, re.I):
        concerns.append("🦠 INFECTION")
    if re.search(r'(?:plantar|heel|forefoot)', text, re.I) and re.search(r'(?:ulcer|DFU)', text, re.I):
        concerns.append("🦴 OSTEOMYELITIS RISK")
    if re.search(r'(?:osteomyelitis|probe-to-bone)', text, re.I):
        concerns.append("🦴 OSTEOMYELITIS")
    if re.search(r'(?:MRSA|resistant)', text, re.I):
        concerns.append("⚠️ MRSA")
    if re.search(r'(?:amputation)', text, re.I):
        concerns.append("🦿 AMPUTATION RISK")
    if re.search(r'(?:food insecurity|homeless)', text, re.I):
        concerns.append("🏠 SOCIAL FACTORS")
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
                    # Show brief extracted data
                    console.print("[bold cyan]── CLINICAL DATA ──[/bold cyan]")
                    if 'CONCERNS' in findings:
                        console.print(f"[bold red]⚠️ CONCERNS: {findings['CONCERNS']}[/bold red]")
                    if 'Vitals' in findings:
                        console.print(f"  Vitals: {findings['Vitals']}")
                    if 'Diagnoses' in findings:
                        console.print(f"  Diagnoses: {findings['Diagnoses']}")

                    # Get LLM interpretation (runs in background thread)
                    import threading
                    def run_analysis(txt, fnd):
                        console.print("[dim]  🔄 Getting clinical review...[/dim]")
                        interp = get_clinical_interpretation(txt, fnd)
                        if interp:
                            console.print("\n[bold yellow]── CLINICAL REVIEW ──[/bold yellow]")
                            for line in interp.split('\n'):
                                if line.strip():
                                    # Color code by urgency and type
                                    upper = line.upper()
                                    if any(w in upper for w in ['SEPSIS', 'STAT', 'URGENT', 'IMMEDIATE', 'CRITICAL', 'EMERGENCY']):
                                        console.print(f"  [bold white on red]{line}[/bold white on red]")
                                    elif 'MISSING' in upper or 'NOT DOCUMENTED' in upper or 'NO MENTION' in upper:
                                        console.print(f"  [bold red]{line}[/bold red]")
                                    elif 'RED FLAG' in upper or 'CONCERN' in upper or 'WARNING' in upper:
                                        console.print(f"  [bold red]{line}[/bold red]")
                                    elif any(w in upper for w in ['CONTRAINDICATED', 'ALLERGY', 'INTERACTION', 'HOLD', 'STOP']):
                                        console.print(f"  [bold magenta]{line}[/bold magenta]")
                                    elif 'QUESTION' in upper or '?' in line:
                                        console.print(f"  [bold cyan]{line}[/bold cyan]")
                                    elif any(w in upper for w in ['RECOMMEND', 'CONSIDER', 'SUGGEST', 'ORDER', 'CHECK', 'VERIFY']):
                                        console.print(f"  [bold green]{line}[/bold green]")
                                    elif line.strip().startswith(('1.', '2.', '3.')):
                                        console.print(f"  [bold white]{line}[/bold white]")
                                    else:
                                        console.print(f"  {line}")
                            console.print()
                        else:
                            console.print("[dim]  (Clinical Insight busy or unavailable)[/dim]\n")

                    threading.Thread(target=run_analysis, args=(text, findings), daemon=True).start()
                else:
                    console.print("[dim]  (No clinical data found)[/dim]")

            time.sleep(1)

    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")

if __name__ == "__main__":
    main()
