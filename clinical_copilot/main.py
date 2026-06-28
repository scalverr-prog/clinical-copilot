"""Clinical Copilot - Clinical Insight for finding what humans miss."""

import time
import sys
import os
import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

console = Console(force_terminal=True, width=100)


@click.group()
@click.version_option(version="1.0.0", prog_name="ClinicalCopilot")
def cli():
    """ClinicalCopilot - Clinical Decision Support"""
    pass


@cli.command()
def start():
    """Start Clinical Copilot - submit notes for analysis."""
    import httpx

    banner = """
[bold cyan]╔═══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║     ██████╗██╗     ██╗███╗   ██╗██╗ ██████╗ █████╗ ██╗           ║
║    ██╔════╝██║     ██║████╗  ██║██║██╔════╝██╔══██╗██║           ║
║    ██║     ██║     ██║██╔██╗ ██║██║██║     ███████║██║           ║
║    ██║     ██║     ██║██║╚██╗██║██║██║     ██╔══██║██║           ║
║    ╚██████╗███████╗██║██║ ╚████║██║╚██████╗██║  ██║███████╗      ║
║     ╚═════╝╚══════╝╚═╝╚═╝  ╚═══╝╚═╝ ╚═════╝╚═╝  ╚═╝╚══════╝      ║
║                       COPILOT v1.0                                ║
║                                                                   ║
║          Real-time Clinical Decision Support                      ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝[/bold cyan]
"""
    console.print(banner)
    console.print("\n[dim]Commands:[/dim]")
    console.print("[dim]  [bold]s[/bold] or [bold]submit[/bold]  = paste a note for analysis[/dim]")
    console.print("[dim]  [bold]m[/bold] or [bold]monitor[/bold] = watch screen for clinical data[/dim]")
    console.print("[dim]  [bold]q[/bold] or [bold]quit[/bold]    = exit[/dim]\n")

    # Check Clinical Insight is running
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get("http://localhost:8001/health")
            if resp.status_code == 200:
                console.print("[green]✓ Clinical Insight ready[/green]\n")
            else:
                console.print("[red]✗ Clinical Insight not responding[/red]")
                console.print("[dim]Run: ./start-copilot.sh[/dim]\n")
                return
    except:
        console.print("[red]✗ Clinical Insight not running[/red]")
        console.print("[dim]Run: ./start-copilot.sh[/dim]\n")
        return

    # Main loop
    while True:
        try:
            cmd = input("[copilot] > ").strip().lower()

            if cmd in ["quit", "q", "exit"]:
                console.print("\n[dim]Goodbye![/dim]\n")
                break
            elif cmd in ["submit", "s"]:
                submit_note()
            elif cmd in ["monitor", "m", "watch", "w"]:
                watch_screen()
            elif cmd == "":
                continue
            else:
                console.print("[dim]Commands: submit (s), monitor (m), quit (q)[/dim]")

        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye![/dim]\n")
            break


def submit_note():
    """Submit a clinical note for analysis."""
    import httpx

    console.print("\n[bold cyan]═══ 📋 SUBMIT CLINICAL NOTE ═══[/bold cyan]")
    console.print("[dim]Paste your note below. Press Enter twice when done.[/dim]\n")

    # Collect multi-line input
    lines = []
    empty_count = 0
    while True:
        try:
            line = input()
            if line == "":
                empty_count += 1
                if empty_count >= 2:
                    break
                lines.append(line)
            else:
                empty_count = 0
                lines.append(line)
        except EOFError:
            break

    note = "\n".join(lines).strip()

    if not note:
        console.print("[yellow]No note provided.[/yellow]\n")
        return

    console.print(f"\n[dim]Analyzing ({len(note)} characters)...[/dim]")
    console.print("[dim]This may take 1-3 minutes on Intel Mac[/dim]\n")

    try:
        start_time = time.time()

        # Create conversation
        with httpx.Client(timeout=10.0) as client:
            conv_resp = client.post("http://localhost:8001/api/chat/new")
            conv_id = conv_resp.json().get("conversation_id")

        # Send note for analysis
        with httpx.Client(timeout=300.0) as client:
            result = client.post(
                "http://localhost:8001/api/chat/message",
                json={
                    "conversation_id": conv_id,
                    "message": f"Review this clinical note. Find safety concerns, drug interactions, gaps, or anything the clinician might have missed:\n\n{note}"
                }
            )
            analysis = result.json().get("response", "No response")

        processing_time = int(time.time() - start_time)

        # Display formatted results with pager for long content
        display_analysis(analysis, processing_time)

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]\n")


def display_analysis(analysis: str, processing_time: int):
    """Display analysis results with word wrapping."""

    console.print()
    box_top("cyan")
    box_title(f"CLINICAL INSIGHT ANALYSIS ({processing_time}s)", "cyan")
    box_top("cyan")
    box_empty("cyan")

    # Format and display analysis
    for line in analysis.split('\n'):
        if not line.strip():
            box_empty("cyan")
            continue

        # Highlight section headers
        if line.startswith("**") or line.startswith("STEP"):
            box_empty("cyan")
            clean = line.replace("**", "").replace(":", "")
            box_line(f"[bold yellow]{clean[:56]}[/bold yellow]", "cyan")
            continue

        # Word wrap
        words = line.split()
        current = ""
        for word in words:
            if len(current) + len(word) < 56:
                current += word + " "
            else:
                box_line(current, "cyan")
                current = word + " "
        if current:
            box_line(current, "cyan")

    box_empty("cyan")
    box_bottom("cyan")
    console.print()
    console.print("[dim]Scroll up to see full analysis[/dim]")
    console.print()


def display_analysis_sidebyside(note: str, analysis: str, processing_time: int):
    """Display original note and analysis side by side."""
    from rich.table import Table
    from rich.text import Text

    console.print()
    console.print(f"[bold cyan]═══ CLINICAL INSIGHT ANALYSIS ({processing_time}s) ═══[/bold cyan]")
    console.print()

    # Create side-by-side table
    table = Table(show_header=True, header_style="bold", expand=True, box=None)
    table.add_column("ORIGINAL NOTE", style="white", width=45)
    table.add_column("│", style="dim", width=1, justify="center")
    table.add_column("ANALYSIS & FEEDBACK", style="cyan", width=45)

    # Wrap text for columns
    def wrap_text(text, width=42):
        lines = []
        for paragraph in text.split('\n'):
            if not paragraph.strip():
                lines.append("")
                continue
            words = paragraph.split()
            current = ""
            for word in words:
                if len(current) + len(word) + 1 <= width:
                    current += word + " "
                else:
                    if current:
                        lines.append(current.rstrip())
                    current = word + " "
            if current:
                lines.append(current.rstrip())
        return lines

    note_lines = wrap_text(note)
    analysis_lines = wrap_text(analysis)

    # Pad to same length
    max_lines = max(len(note_lines), len(analysis_lines))
    while len(note_lines) < max_lines:
        note_lines.append("")
    while len(analysis_lines) < max_lines:
        analysis_lines.append("")

    # Add rows
    for i, (note_line, analysis_line) in enumerate(zip(note_lines, analysis_lines)):
        # Highlight analysis headers
        if analysis_line.startswith("**") or analysis_line.startswith("STEP") or analysis_line.upper() == analysis_line and len(analysis_line) > 3:
            analysis_line = f"[bold yellow]{analysis_line.replace('**', '')}[/bold yellow]"
        table.add_row(note_line, "│", analysis_line)

    console.print(table)
    console.print()
    console.print("[dim]Scroll up to see full comparison[/dim]")
    console.print()


def analyze_screen_once():
    """Analyze current screen content once."""
    from .monitor.screen_monitor import ScreenMonitor

    console.print("\n[bold cyan]═══ 👁️  ANALYZING SCREEN ═══[/bold cyan]")
    console.print("[dim]Extracting clinical data from your screen...[/dim]\n")

    monitor = ScreenMonitor()
    context = monitor.check_for_clinical_content()

    if not context:
        console.print("[yellow]No clinical data detected on screen.[/yellow]")
        console.print("[dim]Make sure you have a patient chart or clinical note visible.[/dim]\n")
        return

    console.print(f"[green]Found:[/green] {context.summary()}\n")

    console.print("[dim]Analyzing with Clinical Insight...[/dim]")
    console.print("[dim]This may take 1-2 minutes[/dim]\n")

    start_time = time.time()
    analysis = monitor.analyze_with_clinical_insight(context)
    processing_time = int(time.time() - start_time)

    if analysis:
        display_analysis(analysis, processing_time)
    else:
        console.print("[red]Analysis failed[/red]\n")


W = 64  # Box width

def box_top(color="white"):
    console.print(f"[{color}]+{'-' * (W-2)}+[/{color}]")

def box_title(title, color="white"):
    padding = W - 4 - len(title)
    left = padding // 2
    right = padding - left
    console.print(f"[{color}]|[/{color}] {' ' * left}[bold {color}]{title}[/bold {color}]{' ' * right} [{color}]|[/{color}]")

def box_line(text, color="white"):
    # Remove markup for length calc
    plain = text
    for tag in ["[green]", "[/green]", "[dim]", "[/dim]", "[bold]", "[/bold]", "[cyan]", "[/cyan]", "[red]", "[/red]", "[yellow]", "[/yellow]"]:
        plain = plain.replace(tag, "")
    spaces = W - 4 - len(plain)
    if spaces < 0:
        text = text[:W-7] + "..."
        spaces = 0
    console.print(f"[{color}]|[/{color}] {text}{' ' * spaces} [{color}]|[/{color}]")

def box_empty(color="white"):
    console.print(f"[{color}]|{' ' * (W-2)}|[/{color}]")

def box_bottom(color="white"):
    console.print(f"[{color}]+{'-' * (W-2)}+[/{color}]")


def ensure_screenpipe():
    """Ensure Screenpipe is running, restart if needed."""
    import httpx
    import subprocess

    try:
        with httpx.Client(timeout=3.0) as client:
            health = client.get("http://localhost:3030/health")
            if health.status_code == 200:
                return True
    except:
        pass

    # Try to restart Screenpipe
    try:
        screenpipe_bin = "/usr/local/bin/screenpipe"
        if not os.path.exists(screenpipe_bin):
            screenpipe_bin = "/opt/homebrew/bin/screenpipe"
        if os.path.exists(screenpipe_bin):
            subprocess.Popen(
                [screenpipe_bin, "--fps", "1"],
                stdout=open("/tmp/screenpipe.log", "w"),
                stderr=subprocess.STDOUT
            )
            time.sleep(5)
            with httpx.Client(timeout=3.0) as client:
                health = client.get("http://localhost:3030/health")
                return health.status_code == 200
    except:
        pass

    return False


def ensure_clinical_insight():
    """Ensure Clinical Insight is running, restart if needed."""
    import httpx
    import subprocess

    try:
        with httpx.Client(timeout=3.0) as client:
            health = client.get("http://localhost:8001/health")
            if health.status_code == 200:
                return True
    except:
        pass

    # Try to restart Clinical Insight
    try:
        backend_dir = "/Users/scalver/clinical-copilot-package/clinical_insight_backend"
        if os.path.exists(backend_dir):
            subprocess.Popen(
                f"cd {backend_dir} && source venv/bin/activate && python3 -m uvicorn app.main:app --port 8001 > /tmp/clinical-insight.log 2>&1",
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(3)
            # Verify it started
            with httpx.Client(timeout=3.0) as client:
                health = client.get("http://localhost:8001/health")
                return health.status_code == 200
    except:
        pass

    return False


def deep_analyze(clinical_data: dict) -> str:
    """Send clinical data to Clinical Insight for deep analytical reasoning."""
    import httpx

    # Ensure Clinical Insight is running (auto-restart if needed)
    if not ensure_clinical_insight():
        return "Clinical Insight unavailable - pattern alerts only"

    # Build comprehensive prompt with all available clinical data
    parts = ["=== PATIENT DATA ==="]

    if clinical_data.get('vitals'):
        parts.append(f"VITALS: {clinical_data['vitals']}")
    if clinical_data.get('medications'):
        parts.append(f"MEDICATIONS: {', '.join(clinical_data['medications'][:8])}")
    if clinical_data.get('labs'):
        parts.append(f"LABS: {clinical_data['labs']}")
    if clinical_data.get('diagnoses'):
        parts.append(f"DIAGNOSES: {', '.join(clinical_data['diagnoses'][:5])}")
    if clinical_data.get('wound_info'):
        parts.append(f"WOUND: {clinical_data['wound_info']}")
    if clinical_data.get('concerns'):
        parts.append(f"FLAGGED CONCERNS: {', '.join(clinical_data['concerns'])}")
    if clinical_data.get('raw_text'):
        # Send more context for better analysis
        parts.append(f"CLINICAL NOTE:\n{clinical_data['raw_text'][:600]}")

    parts.append("")
    parts.append("You are a clinical documentation and safety expert. Review this case for:")
    parts.append("")
    parts.append("1. INCONSISTENCIES: Does the note make sense? Any contradictions or illogical findings?")
    parts.append("2. GAPS: What's missing from the workup? (labs, imaging, consults not ordered)")
    parts.append("3. RISKS: What complications could develop given this presentation?")
    parts.append("4. INTERACTIONS: Any dangerous drug/disease/procedure interactions?")
    parts.append("5. DOCUMENTATION: Is anything unclear, missing required elements, or poorly documented?")
    parts.append("6. NEXT STEPS: What must be done before discharge/sign-off?")
    parts.append("")
    parts.append("Be specific to THIS patient. Quote exact findings. Flag any concerns.")

    prompt = "\n".join(parts)

    try:
        # Create conversation with Clinical Insight
        with httpx.Client(timeout=10.0) as client:
            conv_resp = client.post("http://localhost:8001/api/chat/new")
            if conv_resp.status_code != 200:
                return "Failed to create conversation"
            conv_id = conv_resp.json().get("conversation_id")
            if not conv_id:
                return "No conversation ID returned"

        # Send for analysis (90 second timeout for Intel Mac)
        with httpx.Client(timeout=90.0) as client:
            result = client.post(
                "http://localhost:8001/api/chat/message",
                json={
                    "conversation_id": conv_id,
                    "message": prompt
                }
            )
            if result.status_code == 200:
                return result.json().get("response", "No analysis available")
            else:
                return f"Analysis failed (status {result.status_code})"

    except httpx.TimeoutException:
        return "Analysis timed out - LLM is busy. Try again."
    except httpx.ConnectError:
        return "Cannot connect to Clinical Insight"
    except Exception as e:
        return f"Analysis error: {str(e)[:50]}"


def watch_screen():
    """Real-time clinical monitoring with instant feedback and auto-recovery."""
    from .analysis.clinical_analyzer import ClinicalAnalyzer, AlertLevel
    from .capture.screenpipe import ScreenpipeClient
    from .monitor.screen_monitor import ScreenMonitor
    from datetime import datetime
    import httpx
    import threading

    # Quick service check (no restart - just verify)
    screen_ok = False
    insight_ok = False

    try:
        with httpx.Client(timeout=2.0) as client:
            screen_ok = client.get("http://localhost:3030/health").status_code == 200
    except:
        pass

    try:
        with httpx.Client(timeout=2.0) as client:
            insight_ok = client.get("http://localhost:8001/health").status_code == 200
    except:
        pass

    # Header
    console.print()
    box_top("cyan")
    box_title("CLINICAL COPILOT - REAL-TIME", "cyan")
    box_top("cyan")
    status = f"[green]* Screen[/green]" if screen_ok else "[red]x Screen[/red]"
    status += f"  [green]* Insight[/green]" if insight_ok else "  [red]x Insight[/red]"
    box_line(status, "cyan")
    box_line("[dim]Monitoring... Press Ctrl+C to stop[/dim]", "cyan")
    box_bottom("cyan")
    console.print()

    if not screen_ok:
        console.print("[red]Screenpipe not running. Run ./start-copilot.sh[/red]")
        return
    if not insight_ok:
        console.print("[yellow]Clinical Insight not running - pattern alerts only[/yellow]")

    # Initialize
    analyzer = ClinicalAnalyzer()
    screenpipe = ScreenpipeClient()
    screen_monitor = ScreenMonitor()
    alert_count = 0
    scan_count = 0
    last_text = ""
    last_analysis_time = 0
    analysis_running = False

    STYLES = {
        AlertLevel.ALERT: ("red", "!! CRITICAL !!"),
        AlertLevel.WARNING: ("yellow", "** WARNING **"),
        AlertLevel.SUGGESTION: ("cyan", ">> SUGGESTION"),
        AlertLevel.INFO: ("blue", "-- INFO --"),
    }

    def run_analysis(text):
        nonlocal analysis_running
        try:
            console.print()
            box_top("magenta")
            box_title("CLINICAL ANALYSIS", "magenta")
            box_top("magenta")
            box_line("[dim]Thinking...[/dim]", "magenta")

            # Extract all clinical context
            ctx = screen_monitor.extract_clinical_data(text)
            data = {
                'vitals': ctx.vitals,
                'medications': ctx.medications,
                'labs': ctx.labs,
                'diagnoses': ctx.diagnoses,
                'wound_info': ctx.wound_info,
                'concerns': ctx.concerns,
                'raw_text': text[:800]  # More context for better analysis
            }

            result = deep_analyze(data)

            # Show result
            for line in result.split('\n')[:15]:  # Limit output
                if line.strip():
                    box_line(line[:58], "magenta")

            box_bottom("magenta")
        except Exception as e:
            box_line(f"[red]Error: {str(e)[:50]}[/red]", "magenta")
            box_bottom("magenta")
        finally:
            analysis_running = False

    try:
        while True:
            try:
                time_str = datetime.now().strftime("%H:%M:%S")
                scan_count += 1

                # Show scanning feedback every 5 seconds
                if scan_count % 5 == 1:
                    console.print(f"[dim]{time_str} Scanning screen...[/dim]")

                # Periodic service health check (every 30 scans)
                if scan_count % 30 == 0:
                    if not ensure_screenpipe():
                        console.print("[yellow]Screenpipe restarting...[/yellow]")
                        screenpipe = ScreenpipeClient()  # Reinitialize client

                content = screenpipe.get_current_context()

                if content and content.text_content and len(content.text_content) > 20:
                    text = content.text_content

                    # Show what app we're seeing
                    if scan_count % 10 == 1:
                        console.print(f"[dim]  App: {content.app_name} ({len(text)} chars)[/dim]")

                    # Process content - either new or periodic refresh
                    content_changed = (text != last_text)
                    if content_changed:
                        last_text = text
                        console.print(f"[green]{time_str} New content detected[/green]")

                        # Extract and show clinical context
                        ctx = screen_monitor.extract_clinical_data(text)
                        if ctx.diagnoses or ctx.concerns or ctx.wound_info:
                            console.print(f"[cyan]  Extracted:[/cyan]", end="")
                            if ctx.diagnoses:
                                console.print(f" Dx:{ctx.diagnoses[:3]}", end="")
                            if ctx.concerns:
                                console.print(f" Concerns:{ctx.concerns}", end="")
                            if ctx.wound_info.get('present'):
                                console.print(f" [Wound]", end="")
                            console.print()

                        # Quick checks for critical values
                        alerts = analyzer.quick_check(content)

                        for alert in alerts:
                            if not analyzer.is_duplicate_alert(alert):
                                analyzer.record_alert(alert)
                                alert_count += 1
                                style, prefix = STYLES.get(alert.level, ("white", "??"))

                                console.print()
                                box_top(style)
                                box_title(prefix, style)
                                box_top(style)
                                box_line(f"[bold]{alert.message[:56]}[/bold]", style)
                                if alert.details:
                                    for dline in alert.details.split('\n')[:3]:
                                        box_line(dline[:56], style)
                                box_line(f"[dim]{time_str}[/dim]", style)
                                box_bottom(style)

                        # Deep analysis every 10 seconds if we have content
                        now = time.time()
                        clinical_keywords = ['patient', 'vitals', 'diagnosis', 'mg', 'prbc', 'surgery',
                                           'pacu', 'icu', 'mrn', 'yo ', 'y/o', 'clinical', 'allergies',
                                           'labs', 'bp', 'hr', 'rr', 'temp', 'spo2', 'assessment',
                                           'medical', 'health', 'treatment', 'medication', 'hospital',
                                           'wound', 'ulcer', 'dfu', 'diabetic', 'necrotic', 'debride',
                                           'culture', 'x-ray', 'mri', 'consult', 'hba1c', 'encounter',
                                           'subjective', 'objective', 'soap', 'icd', 'cpt', 'orders']
                        is_clinical = any(k in text.lower() for k in clinical_keywords)

                        if is_clinical and not analysis_running and (now - last_analysis_time) > 10:
                            console.print(f"[cyan]{time_str} Clinical content detected - analyzing...[/cyan]")
                            last_analysis_time = now
                            analysis_running = True
                            threading.Thread(target=run_analysis, args=(text,), daemon=True).start()

                    # Show active alerts count periodically even if content unchanged
                    elif scan_count % 15 == 0 and alert_count > 0:
                        console.print(f"[dim]{time_str} Active concerns: {alert_count} alerts[/dim]")

            except Exception as e:
                console.print(f"[dim]Scan error: {e}[/dim]")

            time.sleep(1)

    except KeyboardInterrupt:
        console.print()
        box_top("dim")
        box_title("SESSION ENDED", "dim")
        box_top("dim")
        box_line(f"Alerts: {alert_count} | Scans: {scan_count}", "dim")
        box_bottom("dim")
        console.print()
        analyzer.close()
        screenpipe.close()


@cli.command()
def status():
    """Check system status."""
    import httpx

    console.print("\n[bold]System Health:[/bold]\n")

    # Check Screenpipe
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get("http://localhost:3030/health")
            if resp.status_code == 200:
                console.print("[green]✓ Screenpipe[/green] - screen capture active")
            else:
                console.print("[yellow]○ Screenpipe[/yellow] - not responding")
    except:
        console.print("[yellow]○ Screenpipe[/yellow] - not running (screen monitoring disabled)")

    # Check Ollama
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get("http://localhost:11434/api/tags")
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                console.print(f"[green]✓ Ollama[/green] - {len(models)} model(s)")
            else:
                console.print("[red]✗ Ollama[/red]")
    except:
        console.print("[red]✗ Ollama not running[/red]")

    # Check Clinical Insight
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get("http://localhost:8001/health")
            if resp.status_code == 200:
                data = resp.json()
                console.print(f"[green]✓ Clinical Insight[/green] - {data.get('llm_provider', 'unknown')}")
            else:
                console.print("[red]✗ Clinical Insight[/red]")
    except:
        console.print("[red]✗ Clinical Insight not running[/red]")

    console.print()


@cli.command()
def submit():
    """Submit a clinical note for analysis (standalone)."""
    submit_note()


@cli.command()
def monitor():
    """Start monitoring immediately (auto-start mode)."""
    import httpx

    banner = """
[bold cyan]╔═══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║     ██████╗██╗     ██╗███╗   ██╗██╗ ██████╗ █████╗ ██╗           ║
║    ██╔════╝██║     ██║████╗  ██║██║██╔════╝██╔══██╗██║           ║
║    ██║     ██║     ██║██╔██╗ ██║██║██║     ███████║██║           ║
║    ██║     ██║     ██║██║╚██╗██║██║██║     ██╔══██║██║           ║
║    ╚██████╗███████╗██║██║ ╚████║██║╚██████╗██║  ██║███████╗      ║
║     ╚═════╝╚══════╝╚═╝╚═╝  ╚═══╝╚═╝ ╚═════╝╚═╝  ╚═╝╚══════╝      ║
║                       COPILOT v1.0                                ║
║                                                                   ║
║          Real-time Clinical Decision Support                      ║
║          Using Clinical Insight + mistral:7b                      ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝[/bold cyan]
"""
    console.print(banner)

    # Check services with retry
    insight_ok = False
    for attempt in range(3):
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get("http://localhost:8001/health")
                if resp.status_code == 200:
                    insight_ok = True
                    break
        except:
            time.sleep(1)

    if insight_ok:
        console.print("[green]✓ Clinical Insight ready[/green]")
    else:
        console.print("[yellow]○ Clinical Insight not available - pattern alerts only[/yellow]")

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get("http://localhost:3030/health")
            if resp.status_code == 200:
                console.print("[green]✓ Screenpipe ready[/green]\n")
            else:
                console.print("[yellow]○ Screenpipe not responding[/yellow]\n")
    except:
        console.print("[yellow]○ Screenpipe not running[/yellow]\n")

    # Auto-start monitoring with crash protection
    try:
        watch_screen()
    except Exception as e:
        console.print(f"[red]Monitor error: {e}[/red]")
        console.print("[dim]Restarting in 5 seconds...[/dim]")
        time.sleep(5)
        watch_screen()  # Retry once


def main():
    cli()


if __name__ == "__main__":
    main()
