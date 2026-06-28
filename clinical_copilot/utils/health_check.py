"""Health checking for system components."""

import subprocess
import time
from typing import Optional
from pydantic import BaseModel
from rich.table import Table
from rich.console import Console

from ..capture.screenpipe import ScreenpipeClient
from ..analysis.ollama_client import OllamaClient
from ..tools.clinical_insight import ClinicalInsightClient
from ..config import settings


class ComponentStatus(BaseModel):
    """Status of a system component."""
    name: str
    healthy: bool
    message: str
    optional: bool = False
    recovery_hint: Optional[str] = None


class HealthChecker:
    """Check health of all system components."""

    def __init__(self):
        self.console = Console()

    def check_screenpipe(self) -> ComponentStatus:
        """Check Screenpipe status."""
        try:
            client = ScreenpipeClient()
            healthy = client.health_check()
            client.close()

            if healthy:
                return ComponentStatus(
                    name="Screenpipe",
                    healthy=True,
                    message=f"Running at {settings.screenpipe.base_url}",
                )
            else:
                # Check if process exists but HTTP server is dead (zombie state)
                result = subprocess.run(
                    ["pgrep", "-x", "screenpipe"],
                    capture_output=True
                )
                if result.returncode == 0:
                    msg = "Process running but HTTP server unresponsive (zombie)"
                    hint = "Run: pkill -9 screenpipe && screenpipe &"
                else:
                    msg = "Not running - screen capture disabled"
                    hint = "Run: screenpipe &"

                return ComponentStatus(
                    name="Screenpipe",
                    healthy=False,
                    message=msg,
                    recovery_hint=hint,
                )
        except Exception as e:
            return ComponentStatus(
                name="Screenpipe",
                healthy=False,
                message=f"Error: {str(e)}",
                recovery_hint="Run: screenpipe &",
            )

    def repair_screenpipe(self) -> bool:
        """Attempt to repair Screenpipe by restarting it."""
        self.console.print("[yellow]Repairing Screenpipe...[/yellow]")

        # Kill any existing processes
        subprocess.run(["pkill", "-9", "screenpipe"], capture_output=True)
        subprocess.run(
            ["pkill", "-9", "-f", "ffmpeg.*\\.screenpipe/data"],
            capture_output=True
        )
        time.sleep(1)

        # Start fresh
        subprocess.Popen(
            ["/usr/local/bin/screenpipe", "--fps", "1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # Wait for HTTP server
        for i in range(15):
            time.sleep(1)
            client = ScreenpipeClient()
            if client.health_check():
                client.close()
                self.console.print("[green]Screenpipe recovered[/green]")
                return True
            client.close()

        self.console.print("[red]Screenpipe repair failed[/red]")
        return False

    def check_ollama(self) -> ComponentStatus:
        """Check Ollama status."""
        try:
            client = OllamaClient()
            healthy = client.health_check()

            if healthy:
                models = client.list_models()
                model = client.get_available_model()
                client.close()

                if model:
                    return ComponentStatus(
                        name="Ollama",
                        healthy=True,
                        message=f"Running with {len(models)} models, using {model}",
                    )
                else:
                    return ComponentStatus(
                        name="Ollama",
                        healthy=False,
                        message="Running but no suitable models found",
                    )
            else:
                return ComponentStatus(
                    name="Ollama",
                    healthy=False,
                    message="Not responding - run 'ollama serve'",
                )
        except Exception as e:
            return ComponentStatus(
                name="Ollama",
                healthy=False,
                message=f"Error: {str(e)}",
            )

    def check_clinical_insight(self) -> ComponentStatus:
        """Check Clinical Insight API status."""
        try:
            client = ClinicalInsightClient()
            healthy = client.health_check()
            client.close()

            if healthy:
                return ComponentStatus(
                    name="Clinical Insight",
                    healthy=True,
                    message=f"Available at {settings.clinical_insight.base_url}",
                    optional=True,
                )
            else:
                return ComponentStatus(
                    name="Clinical Insight",
                    healthy=False,
                    message="Not responding - deep analysis disabled",
                    optional=True,
                )
        except Exception as e:
            return ComponentStatus(
                name="Clinical Insight",
                healthy=False,
                message=f"Not available: {str(e)}",
                optional=True,
            )

    def check_database(self) -> ComponentStatus:
        """Check database status."""
        try:
            from ..memory.db import Database
            db = Database()
            stats = db.get_stats()

            return ComponentStatus(
                name="Database",
                healthy=True,
                message=f"OK - {stats.get('encounters_count', 0)} encounters stored",
            )
        except Exception as e:
            return ComponentStatus(
                name="Database",
                healthy=False,
                message=f"Error: {str(e)}",
            )

    def run_all_checks(self) -> list[ComponentStatus]:
        """Run all health checks."""
        return [
            self.check_screenpipe(),
            self.check_ollama(),
            self.check_clinical_insight(),
            self.check_database(),
        ]

    def print_status(self, statuses: Optional[list[ComponentStatus]] = None):
        """Print health status as a table."""
        if statuses is None:
            statuses = self.run_all_checks()

        table = Table(title="System Health")
        table.add_column("Component", style="bold")
        table.add_column("Status")
        table.add_column("Details")

        for status in statuses:
            if status.healthy:
                status_str = "[bold green]OK[/bold green]"
            elif status.optional:
                status_str = "[yellow]WARN[/yellow]"
            else:
                status_str = "[bold red]FAIL[/bold red]"

            table.add_row(
                status.name,
                status_str,
                status.message,
            )

        self.console.print(table)

        # Show recovery hints for failed components
        failed = [s for s in statuses if not s.healthy and s.recovery_hint]
        if failed:
            self.console.print("\n[bold]Recovery commands:[/bold]")
            for status in failed:
                self.console.print(f"  {status.name}: [cyan]{status.recovery_hint}[/cyan]")

    def is_healthy(self, statuses: Optional[list[ComponentStatus]] = None) -> bool:
        """Check if system is healthy enough to run."""
        if statuses is None:
            statuses = self.run_all_checks()

        # Required components
        for status in statuses:
            if not status.optional and not status.healthy:
                return False

        return True
