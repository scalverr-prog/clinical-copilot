"""Clinical Copilot - Clinical Insight for finding what humans miss."""

import time
import sys
import click
from rich.console import Console

console = Console(force_terminal=True)


@click.group()
@click.version_option(version="1.0.0", prog_name="ClinicalCopilot")
def cli():
    """ClinicalCopilot - Clinical Decision Support"""
    pass


@cli.command()
def start():
    """Start Clinical Copilot - submit notes for analysis."""
    import httpx

    console.print("\n[bold cyan]╔══════════════════════════════════════════════════════════════════╗[/bold cyan]")
    console.print("[bold cyan]║              🐧 CLINICAL COPILOT                                 ║[/bold cyan]")
    console.print("[bold cyan]║              Finding what humans miss                            ║[/bold cyan]")
    console.print("[bold cyan]╚══════════════════════════════════════════════════════════════════╝[/bold cyan]")
    console.print("\n[dim]Commands: [bold]submit[/bold] or [bold]s[/bold] = analyze a note   [bold]quit[/bold] or [bold]q[/bold] = exit[/dim]\n")

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
            elif cmd == "":
                continue
            else:
                console.print("[dim]Commands: submit (s), quit (q)[/dim]")

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

        # Display formatted results
        console.print(f"[bold cyan]╔══════════════════════════════════════════════════════════════════╗[/bold cyan]")
        console.print(f"[bold cyan]║  🧠 CLINICAL INSIGHT ANALYSIS ({processing_time}s)                          ║[/bold cyan]")
        console.print(f"[bold cyan]╚══════════════════════════════════════════════════════════════════╝[/bold cyan]\n")

        # Format sections with colors
        formatted = analysis
        formatted = formatted.replace("**What I noticed:**", "\n[bold yellow]🔍 WHAT I NOTICED:[/bold yellow]")
        formatted = formatted.replace("**How these connect:**", "\n[bold blue]🔗 HOW THESE CONNECT:[/bold blue]")
        formatted = formatted.replace("**Why this matters:**", "\n[bold red]⚠️  WHY THIS MATTERS:[/bold red]")
        formatted = formatted.replace("**What the data doesn't answer:**", "\n[bold magenta]❓ INFORMATION GAPS:[/bold magenta]")
        formatted = formatted.replace("**Recommendation:**", "\n[bold green]✅ RECOMMENDATION:[/bold green]")

        console.print(formatted)
        console.print("\n[dim]═══════════════════════════════════════════════════════════════════[/dim]\n")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]\n")


@cli.command()
def status():
    """Check system status."""
    import httpx

    console.print("\n[bold]System Status:[/bold]\n")

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
