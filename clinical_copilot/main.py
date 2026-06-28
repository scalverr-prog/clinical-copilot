"""Main CLI entry point for ClinicalCopilot."""

import time
import signal
import sys
from datetime import datetime
from typing import Optional

import click
from rich.console import Console

from .config import settings
from .capture.screenpipe import ScreenpipeClient
from .capture.privacy_filter import PrivacyFilter
from .analysis.clinical_analyzer import ClinicalAnalyzer
from .analysis.ollama_client import OllamaClient
from .memory.db import Database
from .memory.patient_memory import PatientMemory
from .memory.preference_memory import PreferenceMemory
from .memory.pattern_memory import PatternMemory
from .tools.clinical_insight import ClinicalInsightClient
from .tools.calculators import ClinicalCalculators
from .tools.drug_checker import DrugChecker
from .ui.terminal import TerminalUI
from .ui.alerts import AlertDisplay
from .ui.indicator import FloatingIndicator
from .utils.health_check import HealthChecker


console = Console(force_terminal=True)


class ClinicalCopilot:
    """Main application class."""

    def __init__(self, mode: str = "general"):
        self.mode = mode
        settings.specialty_mode = mode
        settings.ensure_dirs()

        # Initialize components
        self.db = Database()
        self.screenpipe = ScreenpipeClient()
        self.privacy_filter = PrivacyFilter()
        self.analyzer = ClinicalAnalyzer()
        self.patient_memory = PatientMemory(self.db)
        self.preference_memory = PreferenceMemory(self.db)
        self.pattern_memory = PatternMemory(self.db)
        self.drug_checker = DrugChecker()

        # UI
        self.ui = TerminalUI()
        self.alert_display = AlertDisplay(
            console=self.ui.console,
            preference_memory=self.preference_memory
        )
        self.indicator = FloatingIndicator()

        # State
        self._running = False
        self._session_id: Optional[int] = None
        self._last_app: Optional[str] = None

        # Critical thresholds for instant alerts
        self._vital_thresholds = {
            "sbp": {"low": 90, "high": 180},
            "dbp": {"low": 60, "high": 120},
            "hr": {"low": 50, "high": 120},
            "rr": {"low": 10, "high": 24},
            "temp": {"low": 95, "high": 101.5},
            "spo2": {"low": 92, "high": 100},
        }
        self._lab_thresholds = {
            "potassium": {"low": 3.0, "high": 6.0},
            "k": {"low": 3.0, "high": 6.0},
            "sodium": {"low": 125, "high": 155},
            "na": {"low": 125, "high": 155},
            "glucose": {"low": 60, "high": 400},
            "creatinine": {"low": 0, "high": 4.0},
            "cr": {"low": 0, "high": 4.0},
            "hemoglobin": {"low": 7.0, "high": 20},
            "hgb": {"low": 7.0, "high": 20},
            "troponin": {"low": 0, "high": 0.04},
            "lactate": {"low": 0, "high": 4.0},
        }

    def _check_vital_instant(self, name: str, value: float, app: str):
        """Check a single vital and return alert if critical."""
        from .analysis.clinical_analyzer import ClinicalAlert, AlertLevel
        name = name.lower()
        if name not in self._vital_thresholds:
            return None
        thresh = self._vital_thresholds[name]
        if value < thresh["low"]:
            return ClinicalAlert(
                level=AlertLevel.ALERT,
                message=f"LOW {name.upper()}: {value}",
                details=f"Below {thresh['low']}",
                timestamp=datetime.now(),
                source_app=app,
                confidence=0.95,
                category="vitals",
            )
        elif value > thresh["high"]:
            return ClinicalAlert(
                level=AlertLevel.ALERT,
                message=f"HIGH {name.upper()}: {value}",
                details=f"Above {thresh['high']}",
                timestamp=datetime.now(),
                source_app=app,
                confidence=0.95,
                category="vitals",
            )
        return None

    def _check_lab_instant(self, name: str, value: float, app: str):
        """Check a single lab and return alert if critical."""
        from .analysis.clinical_analyzer import ClinicalAlert, AlertLevel
        name = name.lower().replace("+", "")
        if name not in self._lab_thresholds:
            return None
        thresh = self._lab_thresholds[name]
        if value < thresh["low"]:
            return ClinicalAlert(
                level=AlertLevel.ALERT,
                message=f"LOW {name.upper()}: {value}",
                details=f"Below {thresh['low']}",
                timestamp=datetime.now(),
                source_app=app,
                confidence=0.95,
                category="labs",
            )
        elif value > thresh["high"]:
            return ClinicalAlert(
                level=AlertLevel.ALERT,
                message=f"HIGH {name.upper()}: {value}",
                details=f"Above {thresh['high']}",
                timestamp=datetime.now(),
                source_app=app,
                confidence=0.95,
                category="labs",
            )
        return None

    def start(self):
        """Start the monitoring loop."""
        self._running = True
        self._session_id = self.db.start_session(self.mode)

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

        self.ui.clear()
        self.ui.print_banner()
        self.ui.print_message("Starting ClinicalCopilot...", style="bold")

        # Health check
        checker = HealthChecker()
        statuses = checker.run_all_checks()
        checker.print_status(statuses)

        if not checker.is_healthy(statuses):
            self.ui.print_error("Required components not available. Please check setup.")
            return

        self.ui.print_success("All systems ready!")
        self.ui.update_status("Monitoring")

        # Show startup notification
        self.indicator.start()
        time.sleep(1)

        # Main loop
        self._monitoring_loop()

    def _monitoring_loop(self):
        """Main monitoring loop - REAL-TIME alerts."""
        poll_interval = 0.5  # Poll every 500ms for faster response
        last_content_hash = None

        console.print("\n[bold green]✓ Copilot active - real-time monitoring[/bold green]")
        console.print("[dim]Press Ctrl+C to stop[/dim]\n")

        while self._running:
            try:
                # Get current screen content
                content = self.screenpipe.get_current_context()

                if not content or not content.text_content:
                    time.sleep(poll_interval)
                    continue

                # Apply privacy filter
                filtered = self.privacy_filter.filter_content(content)
                if not filtered:
                    time.sleep(poll_interval)
                    continue

                # Track app changes
                if self._last_app != filtered.app_name:
                    if self._last_app:
                        self.pattern_memory.record_workflow_transition(
                            self._last_app, filtered.app_name
                        )
                    self._last_app = filtered.app_name
                    sys.stdout.write(f"\r→ {filtered.app_name:<55}\n")
                    sys.stdout.flush()

                # Only analyze if content changed
                content_hash = hash(filtered.text_content[:500])
                if content_hash != last_content_hash:
                    last_content_hash = content_hash
                    from .analysis.clinical_analyzer import ClinicalAlert, AlertLevel

                    # Extract patient info first
                    patient_info = self.analyzer.extract_patient_info(filtered.text_content)
                    patient_name = patient_info.get("name") if patient_info else None
                    patient_mrn = patient_info.get("mrn") if patient_info else None

                    # Show patient change
                    if patient_info and (patient_name or patient_mrn):
                        patient_str = self.analyzer.get_patient_context()
                        sys.stdout.write(f"\r👤 {patient_str:<55}\n")
                        sys.stdout.flush()

                    # REAL-TIME: Check vitals and show EACH alert immediately
                    vitals = self.analyzer._extract_vitals(filtered.text_content)
                    for vital_name, value in vitals.items():
                        alert = self._check_vital_instant(vital_name, value, filtered.app_name)
                        if alert and not self.analyzer.is_duplicate_alert(alert):
                            alert.patient_name = patient_name
                            alert.patient_mrn = patient_mrn
                            self.analyzer.record_alert(alert)
                            self.ui.add_alert(alert)
                            console.print()
                            self.alert_display.display(alert)
                            sys.stdout.flush()

                    # REAL-TIME: Check labs and show EACH alert immediately
                    labs = self.analyzer._extract_labs(filtered.text_content)
                    for lab_name, value in labs.items():
                        alert = self._check_lab_instant(lab_name, value, filtered.app_name)
                        if alert and not self.analyzer.is_duplicate_alert(alert):
                            alert.patient_name = patient_name
                            alert.patient_mrn = patient_mrn
                            self.analyzer.record_alert(alert)
                            self.ui.add_alert(alert)
                            console.print()
                            self.alert_display.display(alert)
                            sys.stdout.flush()

                    # REAL-TIME: Check drug interactions
                    drug_alerts = self.drug_checker.analyze_screen_for_interactions(
                        filtered.text_content
                    )
                    for interaction in drug_alerts:
                        alert = ClinicalAlert(
                            level=AlertLevel.WARNING if interaction.severity.value != "contraindicated" else AlertLevel.ALERT,
                            message=f"Drug Interaction: {interaction.drug1} + {interaction.drug2}",
                            details=interaction.description,
                            timestamp=datetime.now(),
                            source_app=filtered.app_name,
                            category="medications",
                            patient_name=patient_name,
                            patient_mrn=patient_mrn,
                        )
                        if not self.analyzer.is_duplicate_alert(alert):
                            self.analyzer.record_alert(alert)
                            self.ui.add_alert(alert)
                            console.print()
                            self.alert_display.display(alert)
                            sys.stdout.flush()

                    # BACKGROUND: LLM for deeper insights
                    import threading
                    _pname, _pmrn = patient_name, patient_mrn  # Capture for closure
                    def run_llm():
                        try:
                            context = self.patient_memory.get_working_memory_context()
                            result = self.analyzer.analyze_with_llm(filtered, context)
                            for alert in result.alerts:
                                if not self.analyzer.is_duplicate_alert(alert):
                                    alert.patient_name = _pname
                                    alert.patient_mrn = _pmrn
                                    self.analyzer.record_alert(alert)
                                    self.ui.add_alert(alert)
                                    console.print()
                                    self.alert_display.display(alert)
                        except:
                            pass
                    threading.Thread(target=run_llm, daemon=True).start()

                # Update UI and indicator
                self.ui.update_status("Monitoring")
                self.indicator.update_alerts(self.ui._alert_count)

                # Sleep before next poll
                time.sleep(poll_interval)

            except KeyboardInterrupt:
                break
            except Exception as e:
                self.ui.print_error(f"Error in monitoring loop: {e}")
                time.sleep(poll_interval)

        self._shutdown()

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals."""
        self._running = False

    def _shutdown(self):
        """Clean shutdown."""
        self.ui.print_message("\nShutting down...", style="bold")

        # End session
        if self._session_id:
            self.db.end_session(
                self._session_id,
                self.ui._encounter_count,
                self.ui._alert_count
            )

        # Show session summary
        summary = self.preference_memory.get_session_summary()
        if summary.get("feedback_count", 0) > 0:
            self.ui.print_message(
                f"Session summary: {summary['feedback_count']} feedback items, "
                f"{summary['helpfulness_rate']:.0%} helpfulness rate"
            )

        # Cleanup
        self.indicator.stop()
        self.screenpipe.close()
        self.analyzer.close()

        self.ui.print_success("Goodbye!")


@click.group()
@click.version_option(version="1.0.0", prog_name="ClinicalCopilot")
def cli():
    """ClinicalCopilot - Real-time Clinical Decision Support"""
    pass


@cli.command()
@click.option(
    "--mode", "-m",
    type=click.Choice(["general", "wound-care", "learning"]),
    default="general",
    help="Specialty mode to use"
)
def start(mode: str):
    """Start the clinical copilot monitoring."""
    copilot = ClinicalCopilot(mode=mode)
    copilot.start()


@cli.command(name="on")
@click.option(
    "--mode", "-m",
    type=click.Choice(["general", "wound-care", "learning"]),
    default="general",
    help="Specialty mode to use"
)
def turn_on(mode: str):
    """Turn on copilot (alias for start)."""
    console.print("[bold green]Copilot ON[/bold green]")
    copilot = ClinicalCopilot(mode=mode)
    copilot.start()


@cli.command(name="off")
def turn_off():
    """Turn off any running copilot."""
    import os
    console.print("[bold yellow]Stopping copilot...[/bold yellow]")
    os.system("pkill -f 'copilot start' 2>/dev/null")
    os.system("pkill -f 'copilot on' 2>/dev/null")
    console.print("[bold green]Copilot OFF[/bold green]")


@cli.command()
def status():
    """Check system status."""
    checker = HealthChecker()
    checker.print_status()


@cli.command()
@click.option("--hours", "-h", default=24, help="Hours of history to show")
@click.option("--limit", "-l", default=20, help="Maximum entries to show")
def history(hours: int, limit: int):
    """View encounter history."""
    db = Database()
    encounters = db.get_recent_encounters(hours=hours, limit=limit)

    if not encounters:
        console.print("No encounters found.")
        return

    from rich.table import Table
    table = Table(title=f"Recent Encounters (last {hours}h)")
    table.add_column("Time")
    table.add_column("App")
    table.add_column("Summary")
    table.add_column("Alerts")

    for enc in encounters:
        import json
        alerts = json.loads(enc.get('alerts_json', '[]'))
        alert_count = len(alerts)

        table.add_row(
            enc.get('timestamp', '')[:19],
            enc.get('app_name', 'Unknown'),
            (enc.get('analysis_summary', '') or '')[:50],
            str(alert_count),
        )

    console.print(table)


@cli.command()
@click.argument("query")
def search(query: str):
    """Search encounter history."""
    db = Database()
    results = db.search_encounters(query)

    if not results:
        console.print(f"No results for '{query}'")
        return

    console.print(f"Found {len(results)} results:")
    for enc in results[:10]:
        console.print(f"  - [{enc.get('timestamp', '')[:10]}] {enc.get('analysis_summary', '')[:60]}")


@cli.command()
@click.argument("text")
def analyze(text: str):
    """Analyze clinical text using Clinical Insight."""
    try:
        client = ClinicalInsightClient()
        result = client.analyze_case(text)
        client.close()

        console.print("\n[bold]Analysis:[/bold]")
        console.print(result.analysis)

        if result.gaps:
            console.print("\n[bold]Information Gaps:[/bold]")
            for gap in result.gaps:
                console.print(f"  - {gap}")

        if result.red_flags:
            console.print("\n[bold red]Red Flags:[/bold red]")
            for flag in result.red_flags:
                console.print(f"  [red]![/red] {flag}")

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")


@cli.command()
@click.option("--exclude", "-e", multiple=True, help="Apps to exclude")
@click.option("--list", "-l", "list_excluded", is_flag=True, help="List excluded apps")
def config(exclude: tuple, list_excluded: bool):
    """Configure privacy settings."""
    pf = PrivacyFilter()

    if list_excluded:
        status = pf.get_status()
        console.print("[bold]Excluded Apps:[/bold]")
        for app in sorted(status['excluded_apps']):
            console.print(f"  - {app}")
        return

    for app in exclude:
        pf.add_excluded(app)
        console.print(f"Added '{app}' to exclusion list")


@cli.command()
def learn():
    """Review and train on recent alerts."""
    pm = PreferenceMemory()
    stats = pm.get_alert_stats()

    console.print("[bold]Alert Statistics:[/bold]")
    console.print(f"  Total alerts: {stats.get('total', 0)}")
    console.print(f"  Marked helpful: {stats.get('helpful', 0)}")
    console.print(f"  Marked not helpful: {stats.get('not_helpful', 0)}")

    prefs = pm.get_all_preferences()
    if prefs:
        console.print("\n[bold]Learned Preferences:[/bold]")
        for key, pref in list(prefs.items())[:10]:
            console.print(f"  - {key}: confidence {pref.confidence:.2f}")


@cli.command()
@click.argument("calculator", type=click.Choice(ClinicalCalculators.list_calculators()))
def calc(calculator: str):
    """Run a clinical calculator interactively."""
    console.print(f"[bold]{calculator.upper()} Calculator[/bold]\n")

    if calculator == "gfr_ckd_epi":
        cr = float(click.prompt("Creatinine (mg/dL)"))
        age = int(click.prompt("Age"))
        female = click.confirm("Female?")
        result = ClinicalCalculators.gfr_ckd_epi(cr, age, female)

    elif calculator == "meld_score":
        bili = float(click.prompt("Bilirubin (mg/dL)"))
        inr = float(click.prompt("INR"))
        cr = float(click.prompt("Creatinine (mg/dL)"))
        na = click.prompt("Sodium (mEq/L, or skip)", default="")
        dialysis = click.confirm("On dialysis?", default=False)
        sodium = float(na) if na else None
        result = ClinicalCalculators.meld_score(bili, inr, cr, sodium, dialysis)

    elif calculator == "chadsvasc":
        result = ClinicalCalculators.chadsvasc(
            chf=click.confirm("CHF?", default=False),
            hypertension=click.confirm("Hypertension?", default=False),
            age_65_74=click.confirm("Age 65-74?", default=False),
            age_75_plus=click.confirm("Age 75+?", default=False),
            diabetes=click.confirm("Diabetes?", default=False),
            stroke_tia=click.confirm("Stroke/TIA history?", default=False),
            vascular_disease=click.confirm("Vascular disease?", default=False),
            female=click.confirm("Female?", default=False),
        )

    else:
        console.print(f"Calculator '{calculator}' not fully implemented yet.")
        return

    console.print(f"\n[bold]Result:[/bold]")
    console.print(f"  Score: {result.score}")
    console.print(f"  Interpretation: {result.interpretation}")
    console.print(f"  Risk Level: {result.risk_level.value}")


@cli.command()
@click.argument("drugs", nargs=-1)
def interactions(drugs: tuple):
    """Check drug interactions."""
    if len(drugs) < 2:
        console.print("Please provide at least 2 drugs to check.")
        return

    checker = DrugChecker()
    results = checker.check_list(list(drugs))

    if not results:
        console.print("[green]No interactions found.[/green]")
        return

    console.print(f"[bold]Found {len(results)} interaction(s):[/bold]\n")
    for interaction in results:
        severity_colors = {
            "contraindicated": "bold red",
            "major": "red",
            "moderate": "yellow",
            "minor": "dim",
        }
        color = severity_colors.get(interaction.severity.value, "white")
        console.print(f"[{color}]{interaction.severity.value.upper()}[/{color}]: "
                      f"{interaction.drug1} + {interaction.drug2}")
        console.print(f"  {interaction.description}")
        if interaction.recommendation:
            console.print(f"  -> {interaction.recommendation}")
        console.print()


@cli.command()
@click.argument("what", type=click.Choice(["suggestions", "warnings", "info", "all"]))
def suppress(what: str):
    """Suppress alert types. Options: suggestions, warnings, info, all"""
    from .memory.preference_memory import PreferenceMemory
    prefs = PreferenceMemory()

    level_map = {
        "suggestions": "suggestion",
        "warnings": "warning",
        "info": "info",
    }

    if what == "all":
        for level in level_map.values():
            prefs.suppress_level(level)
        console.print("[yellow]Suppressed all non-critical alerts.[/yellow]")
    else:
        level = level_map[what]
        prefs.suppress_level(level)
        console.print(f"[yellow]Suppressed {what}.[/yellow]")

    console.print("[dim]Critical alerts will still be shown.[/dim]")


@cli.command()
@click.argument("what", type=click.Choice(["suggestions", "warnings", "info", "all"]))
def unsuppress(what: str):
    """Re-enable suppressed alert types."""
    from .memory.preference_memory import PreferenceMemory
    prefs = PreferenceMemory()

    level_map = {
        "suggestions": "suggestion",
        "warnings": "warning",
        "info": "info",
    }

    if what == "all":
        prefs.clear_suppressions()
        console.print("[green]All alerts re-enabled.[/green]")
    else:
        level = level_map[what]
        prefs.unsuppress_level(level)
        console.print(f"[green]Re-enabled {what}.[/green]")


@cli.command()
def suppressed():
    """Show currently suppressed alert types."""
    from .memory.preference_memory import PreferenceMemory
    prefs = PreferenceMemory()
    status = prefs.get_suppressed()

    console.print("[bold]Suppressed Alerts:[/bold]")

    if status["levels"]:
        console.print(f"  Levels: {', '.join(status['levels'])}")
    else:
        console.print("  Levels: [dim]none[/dim]")

    if status["categories"]:
        console.print(f"  Categories: {', '.join(status['categories'])}")
    else:
        console.print("  Categories: [dim]none[/dim]")


@cli.command()
def preferences():
    """Show learned alert preferences and scores."""
    from .memory.preference_memory import PreferenceMemory
    prefs = PreferenceMemory()

    console.print("[bold]Learned Preferences:[/bold]\n")

    # Show scores by level
    console.print("[cyan]Alert Level Scores:[/cyan]")
    for level in ["alert", "warning", "suggestion", "info"]:
        score_key = f"alert_scores_{level}"
        scores = prefs.get_preference(score_key)
        if scores and scores.get("scores"):
            avg = scores.get("avg", 0)
            count = len(scores["scores"])
            bar = "█" * int(avg) + "░" * (5 - int(avg))
            status = "[green]showing[/green]" if avg >= 2 else "[red]auto-hidden[/red]"
            console.print(f"  {level:12} {bar} {avg:.1f}/5 ({count} ratings) {status}")
        else:
            console.print(f"  {level:12} [dim]no ratings yet[/dim]")

    # Show scores by category
    console.print("\n[cyan]Category Scores:[/cyan]")
    all_prefs = prefs.get_all_preferences()
    cat_scores = {k: v for k, v in all_prefs.items() if k.startswith("category_scores_")}

    if cat_scores:
        for key, pref in cat_scores.items():
            category = key.replace("category_scores_", "")
            try:
                import json
                scores = json.loads(pref.value) if isinstance(pref.value, str) else pref.value
                avg = scores.get("avg", 0)
                count = len(scores.get("scores", []))
                bar = "█" * int(avg) + "░" * (5 - int(avg))
                console.print(f"  {category:15} {bar} {avg:.1f}/5 ({count} ratings)")
            except:
                pass
    else:
        console.print("  [dim]no category ratings yet[/dim]")

    # Show suppressed
    status = prefs.get_suppressed()
    if status["levels"] or status["categories"]:
        console.print("\n[yellow]Manually Suppressed:[/yellow]")
        if status["levels"]:
            console.print(f"  Levels: {', '.join(status['levels'])}")
        if status["categories"]:
            console.print(f"  Categories: {', '.join(status['categories'])}")


def main():
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
