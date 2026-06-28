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
    console.print("[dim]  [bold]m[/bold] or [bold]monitor[/bold] = analyze what's on screen now[/dim]")
    console.print("[dim]  [bold]w[/bold] or [bold]watch[/bold]   = continuous screen monitoring[/dim]")
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
            elif cmd in ["monitor", "m"]:
                analyze_screen_once()
            elif cmd in ["watch", "w"]:
                watch_screen()
            elif cmd == "":
                continue
            else:
                console.print("[dim]Commands: submit (s), monitor (m), watch (w), quit (q)[/dim]")

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
    import textwrap

    console.print()
    console.print("[bold cyan]╔══════════════════════════════════════════════════════════════════╗[/bold cyan]")
    console.print(f"[bold cyan]║  🧠 CLINICAL INSIGHT ANALYSIS ({processing_time}s)                          ║[/bold cyan]")
    console.print("[bold cyan]╚══════════════════════════════════════════════════════════════════╝[/bold cyan]")
    console.print()

    # Format sections with visual markers and colors
    formatted = analysis

    # Replace section headers with colored versions
    formatted = formatted.replace("**What I noticed:**", "\n[bold yellow]🔍 WHAT I NOTICED:[/bold yellow]\n" + "─" * 50)
    formatted = formatted.replace("**How these connect:**", "\n\n[bold blue]🔗 HOW THESE CONNECT:[/bold blue]\n" + "─" * 50)
    formatted = formatted.replace("**Why this matters:**", "\n\n[bold red]⚠️  WHY THIS MATTERS:[/bold red]\n" + "─" * 50)
    formatted = formatted.replace("**What the data doesn't answer:**", "\n\n[bold magenta]❓ INFORMATION GAPS:[/bold magenta]\n" + "─" * 50)
    formatted = formatted.replace("**Recommendation:**", "\n\n[bold green]✅ RECOMMENDATION:[/bold green]\n" + "─" * 50)

    # Print with word wrapping
    console.print(formatted)
    console.print()
    console.print("[dim]═══════════════════════════════════════════════════════════════════[/dim]")
    console.print("[dim]Scroll up in terminal to see full analysis (Cmd+↑ or scroll)[/dim]")
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


def watch_screen():
    """Continuously watch screen for clinical content."""
    from .monitor.screen_monitor import ScreenMonitor
    import httpx

    console.print("\n[bold cyan]═══ 👁️  WATCHING SCREEN ═══[/bold cyan]")
    console.print("[dim]Monitoring for clinical content... Press Ctrl+C to stop[/dim]\n")

    # Check Screenpipe
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get("http://localhost:3030/health")
            if resp.status_code != 200:
                console.print("[red]Screenpipe not responding[/red]")
                console.print("[dim]Run: ./start-copilot.sh[/dim]\n")
                return
    except:
        console.print("[red]Screenpipe not running[/red]")
        console.print("[dim]Run: ./start-copilot.sh[/dim]\n")
        return

    console.print("[green]✓ Screenpipe connected[/green]")
    console.print("[dim]Watching for clinical data (checking every 10 seconds)...[/dim]\n")

    monitor = ScreenMonitor()
    last_mrn = None
    check_count = 0

    try:
        while True:
            check_count += 1
            context = monitor.check_for_clinical_content()

            if context and context.has_clinical_data():
                # New patient or new significant data
                if context.mrn != last_mrn:
                    last_mrn = context.mrn
                    console.print(f"\n[bold green]━━━ New patient data detected ━━━[/bold green]")
                    console.print(f"[cyan]{context.summary()}[/cyan]")
                    console.print("[dim]Analyzing...[/dim]")

                    analysis = monitor.analyze_with_clinical_insight(context)
                    if analysis:
                        # Show brief alert, not full analysis
                        lines = analysis.split('\n')[:10]
                        for line in lines:
                            if line.strip():
                                console.print(f"  {line}")
                        console.print("[dim]  ... (type 'm' for full analysis)[/dim]\n")

            # Status indicator every 30 seconds
            if check_count % 3 == 0:
                console.print(f"[dim]... watching ({check_count * 10}s)[/dim]", end="\r")

            time.sleep(10)

    except KeyboardInterrupt:
        console.print("\n[dim]Stopped watching.[/dim]\n")


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


def main():
    cli()


if __name__ == "__main__":
    main()
