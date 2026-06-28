"""Alert display and management."""

import sys
import threading
from datetime import datetime
from typing import Optional, Callable
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from ..analysis.clinical_analyzer import ClinicalAlert, AlertLevel
from ..memory.preference_memory import PreferenceMemory


class AlertDisplay:
    """Manages alert display and user interaction."""

    def __init__(
        self,
        console: Optional[Console] = None,
        preference_memory: Optional[PreferenceMemory] = None,
        interactive: bool = True
    ):
        self.console = console or Console()
        self.preferences = preference_memory or PreferenceMemory()
        self._pending_feedback: list[tuple[ClinicalAlert, int]] = []
        self.interactive = interactive
        self._dismiss_lock = threading.Lock()
        self._resolved_alerts: list[str] = []  # Track resolved alert messages

    def should_display(self, alert: ClinicalAlert) -> bool:
        """Check if alert should be displayed based on preferences."""
        # Skip if already resolved this session
        if alert.message in self._resolved_alerts:
            return False
        return self.preferences.should_show_alert(alert)

    def is_resolved(self, alert: ClinicalAlert) -> bool:
        """Check if alert was marked resolved."""
        return alert.message in self._resolved_alerts

    def get_resolved_count(self) -> int:
        """Get count of resolved alerts this session."""
        return len(self._resolved_alerts)

    def clear_resolved(self):
        """Clear resolved alerts (new patient/session)."""
        self._resolved_alerts.clear()

    def display(self, alert: ClinicalAlert, show_dismiss: bool = True):
        """Display an alert to the user."""
        if not self.should_display(alert):
            return

        # Style based on level
        styles = {
            AlertLevel.ALERT: ("bold white on red", "CRITICAL"),
            AlertLevel.WARNING: ("bold black on yellow", "WARNING"),
            AlertLevel.SUGGESTION: ("bold white on blue", "SUGGESTION"),
            AlertLevel.INFO: ("dim", "INFO"),
        }

        style, label = styles.get(alert.level, ("white", "ALERT"))
        time_str = alert.timestamp.strftime("%H:%M:%S")

        # Build alert content
        content = Text()

        # Show patient info first if available
        if alert.patient_name or alert.patient_mrn:
            patient_str = ""
            if alert.patient_name:
                patient_str += alert.patient_name
            if alert.patient_mrn:
                patient_str += f" (MRN: {alert.patient_mrn})"
            content.append(f"👤 {patient_str}\n", style="bold white")

        content.append(f"[{time_str}] ", style="dim")
        content.append(f"{label}: ", style=style)
        content.append(alert.message)

        if alert.details:
            content.append(f"\n  → {alert.details}", style="dim")

        if alert.source_text:
            content.append(f"\n  📍 Source: \"{alert.source_text}\"", style="italic cyan")

        if alert.category:
            content.append(f" [{alert.category}]", style="italic dim")

        # Add interactive options
        if self.interactive and show_dismiss:
            content.append(f"\n  ", style="dim")
            content.append("[1-5] score", style="dim green")
            content.append(" | [r]esolved", style="dim magenta")
            if alert.level != AlertLevel.ALERT:
                content.append(f" | [d]ismiss {label.lower()}s | [c]ategory", style="dim cyan")
            content.append(" | [Enter] skip", style="dim")

        # Print with appropriate panel style
        border_colors = {
            AlertLevel.ALERT: "red",
            AlertLevel.WARNING: "yellow",
            AlertLevel.SUGGESTION: "cyan",
            AlertLevel.INFO: "dim",
        }

        self.console.print(Panel(
            content,
            border_style=border_colors.get(alert.level, "white"),
            padding=(0, 1),
        ))

        # Handle interactive input (scoring, dismiss)
        if self.interactive and show_dismiss:
            self._handle_interactive_input(alert)

        # Track for feedback
        self._pending_feedback.append((alert, datetime.now().timestamp()))

    def _handle_interactive_input(self, alert: ClinicalAlert):
        """Handle user input for scoring and dismissing alerts."""
        import select

        # Non-blocking check for input (wait up to 3 seconds)
        try:
            if sys.stdin in select.select([sys.stdin], [], [], 3.0)[0]:
                with self._dismiss_lock:
                    key = sys.stdin.readline().strip().lower()

                    # Handle scoring (1-5)
                    if key in ('1', '2', '3', '4', '5'):
                        score = int(key)
                        was_helpful = score >= 3
                        self.preferences.record_alert_feedback(alert, was_helpful)
                        self._record_score(alert, score)

                        if score >= 4:
                            self.console.print(f"[green]Scored {score}/5 - learning to show more like this[/green]")
                        elif score <= 2:
                            self.console.print(f"[yellow]Scored {score}/5 - learning to show fewer like this[/yellow]")
                        else:
                            self.console.print(f"[dim]Scored {score}/5[/dim]")

                    elif key == 'r':
                        # Mark as resolved
                        self._resolved_alerts.append(alert.message)
                        self.console.print(f"[magenta]✓ Marked resolved[/magenta]")

                    elif key == 'd' and alert.level != AlertLevel.ALERT:
                        # Dismiss this alert level
                        self.preferences.suppress_level(alert.level.value)
                        self.console.print(f"[yellow]Suppressed all {alert.level.value}s[/yellow]")

                    elif key == 'c' and alert.category:
                        # Dismiss this category
                        self.preferences.suppress_category(alert.category)
                        self.console.print(f"[yellow]Suppressed category: {alert.category}[/yellow]")

        except (OSError, ValueError):
            # Not a terminal or select not supported
            pass

    def _record_score(self, alert: ClinicalAlert, score: int):
        """Record detailed score for learning."""
        # Store score in preferences for fine-grained learning
        score_key = f"alert_scores_{alert.level.value}"
        scores = self.preferences.get_preference(score_key) or {"scores": [], "avg": 0}

        scores["scores"].append(score)
        # Keep last 50 scores
        scores["scores"] = scores["scores"][-50:]
        scores["avg"] = sum(scores["scores"]) / len(scores["scores"])

        self.preferences.set_preference(score_key, scores, "user_scoring")

        # Also track by category
        if alert.category:
            cat_score_key = f"category_scores_{alert.category}"
            cat_scores = self.preferences.get_preference(cat_score_key) or {"scores": [], "avg": 0}
            cat_scores["scores"].append(score)
            cat_scores["scores"] = cat_scores["scores"][-50:]
            cat_scores["avg"] = sum(cat_scores["scores"]) / len(cat_scores["scores"])
            self.preferences.set_preference(cat_score_key, cat_scores, "user_scoring")

    def display_batch(self, alerts: list[ClinicalAlert]):
        """Display multiple alerts."""
        # Sort by severity
        severity_order = {
            AlertLevel.ALERT: 0,
            AlertLevel.WARNING: 1,
            AlertLevel.SUGGESTION: 2,
            AlertLevel.INFO: 3,
        }
        sorted_alerts = sorted(alerts, key=lambda a: severity_order[a.level])

        for alert in sorted_alerts:
            self.display(alert)

    def request_feedback(
        self,
        alert: ClinicalAlert,
        callback: Optional[Callable[[ClinicalAlert, bool], None]] = None
    ):
        """Request feedback on an alert."""
        self.console.print()
        response = self.console.input(
            "[dim]Was this alert helpful? (y/n/skip): [/dim]"
        ).lower()

        if response in ("y", "yes"):
            self.preferences.record_alert_feedback(alert, was_helpful=True)
            if callback:
                callback(alert, True)
        elif response in ("n", "no"):
            self.preferences.record_alert_feedback(alert, was_helpful=False)
            if callback:
                callback(alert, False)
        # Skip = no feedback recorded

    def format_alert_summary(self, alerts: list[ClinicalAlert]) -> str:
        """Format a summary of alerts."""
        if not alerts:
            return "No alerts"

        counts = {level: 0 for level in AlertLevel}
        for alert in alerts:
            counts[alert.level] += 1

        parts = []
        if counts[AlertLevel.ALERT]:
            parts.append(f"{counts[AlertLevel.ALERT]} critical")
        if counts[AlertLevel.WARNING]:
            parts.append(f"{counts[AlertLevel.WARNING]} warnings")
        if counts[AlertLevel.SUGGESTION]:
            parts.append(f"{counts[AlertLevel.SUGGESTION]} suggestions")
        if counts[AlertLevel.INFO]:
            parts.append(f"{counts[AlertLevel.INFO]} info")

        return ", ".join(parts)

    def get_alert_stats(self) -> dict:
        """Get statistics about displayed alerts."""
        return self.preferences.get_alert_stats()
