"""Rich terminal UI for ClinicalCopilot."""

import os
from datetime import datetime
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.layout import Layout
from rich.live import Live
from rich.text import Text
from rich.align import Align

from ..analysis.clinical_analyzer import ClinicalAlert, AlertLevel
from ..config import settings


class TerminalUI:
    """Rich terminal interface for ClinicalCopilot."""

    # Alert level styling
    ALERT_STYLES = {
        AlertLevel.ALERT: ("bold red", "[!]"),
        AlertLevel.WARNING: ("bold yellow", "[*]"),
        AlertLevel.SUGGESTION: ("bold cyan", "[>]"),
        AlertLevel.INFO: ("dim", "[i]"),
    }

    def __init__(self):
        self.console = Console(force_terminal=True)
        self._start_time = datetime.now()
        self._encounter_count = 0
        self._alert_count = 0
        self._current_mode = settings.specialty_mode
        self._status = "Initializing"
        self._alerts: list[ClinicalAlert] = []
        self._max_alerts = 10

    def clear(self):
        """Clear the terminal."""
        self.console.clear()

    def print_banner(self):
        """Print the application banner."""
        banner = """
╔═══════════════════════════════════════════════════════════════════╗
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
╚═══════════════════════════════════════════════════════════════════╝
"""
        self.console.print(banner, style="bold blue")

    def print_status_bar(self):
        """Print the status bar."""
        uptime = datetime.now() - self._start_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m"

        status_table = Table.grid(expand=True)
        status_table.add_column(justify="left", ratio=1)
        status_table.add_column(justify="center", ratio=1)
        status_table.add_column(justify="right", ratio=1)

        status_table.add_row(
            f"[bold]Status:[/bold] {self._status}",
            f"[bold]Mode:[/bold] {self._current_mode.title()}",
            f"[bold]Uptime:[/bold] {uptime_str}",
        )
        status_table.add_row(
            f"[bold]Encounters:[/bold] {self._encounter_count}",
            f"[bold]Alerts:[/bold] {self._alert_count}",
            f"[bold]Time:[/bold] {datetime.now().strftime('%H:%M:%S')}",
        )

        self.console.print(Panel(status_table, title="ClinicalCopilot", border_style="blue"))

    def format_alert(self, alert: ClinicalAlert) -> Panel:
        """Format an alert as a Rich panel."""
        style, prefix = self.ALERT_STYLES.get(
            alert.level,
            ("white", "[?]")
        )

        time_str = alert.timestamp.strftime("%H:%M:%S")
        title = f"{prefix} {alert.level.value.upper()} [{time_str}]"

        content = Text()
        content.append(alert.message)
        if alert.details:
            content.append(f"\n{alert.details}", style="dim")
        if alert.source_app:
            content.append(f"\n[Source: {alert.source_app}]", style="dim italic")

        return Panel(
            content,
            title=title,
            title_align="left",
            border_style=style.split()[-1],  # Get color from style
        )

    def add_alert(self, alert: ClinicalAlert):
        """Add an alert to the display."""
        self._alerts.append(alert)
        self._alert_count += 1
        # Keep only recent alerts
        if len(self._alerts) > self._max_alerts:
            self._alerts = self._alerts[-self._max_alerts:]

    def print_alerts(self):
        """Print all current alerts."""
        if not self._alerts:
            self.console.print(
                Panel(
                    "[dim]No alerts - monitoring...[/dim]",
                    title="Alerts",
                    border_style="dim"
                )
            )
            return

        for alert in reversed(self._alerts[-5:]):  # Show last 5
            self.console.print(self.format_alert(alert))

    def print_help(self):
        """Print help information."""
        help_table = Table(title="Commands", show_header=False, box=None)
        help_table.add_column("Key", style="bold cyan")
        help_table.add_column("Action")

        help_table.add_row("d", "Show alert details")
        help_table.add_row("c", "Open Clinical Insight")
        help_table.add_row("h", "View history")
        help_table.add_row("s", "Search")
        help_table.add_row("m", "Change mode")
        help_table.add_row("?", "Show this help")
        help_table.add_row("q", "Quit")

        self.console.print(Panel(help_table, border_style="dim"))

    def update_status(self, status: str):
        """Update the status message."""
        self._status = status

    def update_mode(self, mode: str):
        """Update the specialty mode."""
        self._current_mode = mode

    def increment_encounters(self):
        """Increment encounter count."""
        self._encounter_count += 1

    def render_dashboard(self):
        """Render the full dashboard."""
        self.clear()
        self.print_status_bar()
        self.console.print()
        self.print_alerts()
        self.console.print()
        self.print_help()

    def print_message(self, message: str, style: str = ""):
        """Print a message."""
        self.console.print(message, style=style)

    def print_error(self, message: str):
        """Print an error message."""
        self.console.print(f"[bold red]Error:[/bold red] {message}")

    def print_success(self, message: str):
        """Print a success message."""
        self.console.print(f"[bold green]Success:[/bold green] {message}")

    def print_table(self, title: str, headers: list[str], rows: list[list[str]]):
        """Print a table."""
        table = Table(title=title)
        for header in headers:
            table.add_column(header)
        for row in rows:
            table.add_row(*row)
        self.console.print(table)

    def prompt(self, message: str) -> str:
        """Prompt for user input."""
        return self.console.input(f"[bold cyan]{message}[/bold cyan] ")

    def confirm(self, message: str) -> bool:
        """Prompt for confirmation."""
        response = self.prompt(f"{message} [y/N]").lower()
        return response in ("y", "yes")
