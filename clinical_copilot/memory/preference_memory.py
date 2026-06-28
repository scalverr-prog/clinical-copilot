"""User preference learning and memory."""

from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel

from .db import Database
from ..analysis.clinical_analyzer import ClinicalAlert, AlertLevel
from ..config import settings


class UserPreference(BaseModel):
    """A learned user preference."""
    key: str
    value: Any
    confidence: float
    learned_from: str
    update_count: int


class PreferenceMemory:
    """Learns and remembers user preferences over time."""

    # Preference categories
    CATEGORIES = {
        "alert_preferences": "How user responds to different alert types",
        "workflow_patterns": "User's typical workflow patterns",
        "specialty_focus": "Areas of clinical focus",
        "communication_style": "Preferred communication style",
    }

    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()
        self._session_feedback: list[dict] = []

    def record_alert_feedback(
        self,
        alert: ClinicalAlert,
        was_helpful: bool,
        user_action: Optional[str] = None
    ):
        """Record user feedback on an alert."""
        # Save to database
        alert_id = self.db.record_alert(
            level=alert.level.value,
            message=alert.message,
            source_app=alert.source_app,
        )
        self.db.mark_alert_feedback(alert_id, was_helpful, user_action)

        # Track in session
        self._session_feedback.append({
            "alert_level": alert.level.value,
            "category": alert.category,
            "was_helpful": was_helpful,
            "user_action": user_action,
            "timestamp": datetime.now(),
        })

        # Learn from feedback
        self._learn_from_feedback(alert, was_helpful)

    def _learn_from_feedback(
        self,
        alert: ClinicalAlert,
        was_helpful: bool
    ):
        """Learn preferences from feedback."""
        # Track helpfulness by alert level
        level_key = f"alert_helpfulness_{alert.level.value}"
        current = self.db.get_preference(level_key)

        if current:
            # Update running average
            try:
                import json
                data = json.loads(current['value'])
                total = data.get('total', 0) + 1
                helpful = data.get('helpful', 0) + (1 if was_helpful else 0)
                data = {'total': total, 'helpful': helpful, 'rate': helpful / total}
            except:
                data = {'total': 1, 'helpful': 1 if was_helpful else 0, 'rate': 1.0 if was_helpful else 0.0}
        else:
            data = {'total': 1, 'helpful': 1 if was_helpful else 0, 'rate': 1.0 if was_helpful else 0.0}

        self.db.set_preference(
            key=level_key,
            value=data,
            learned_from="alert_feedback",
        )

        # Track by category if available
        if alert.category:
            cat_key = f"category_helpfulness_{alert.category}"
            cat_current = self.db.get_preference(cat_key)

            if cat_current:
                try:
                    import json
                    data = json.loads(cat_current['value'])
                    total = data.get('total', 0) + 1
                    helpful = data.get('helpful', 0) + (1 if was_helpful else 0)
                    data = {'total': total, 'helpful': helpful, 'rate': helpful / total}
                except:
                    data = {'total': 1, 'helpful': 1 if was_helpful else 0, 'rate': 1.0 if was_helpful else 0.0}
            else:
                data = {'total': 1, 'helpful': 1 if was_helpful else 0, 'rate': 1.0 if was_helpful else 0.0}

            self.db.set_preference(
                key=cat_key,
                value=data,
                learned_from="alert_feedback",
            )

    def set_preference(
        self,
        key: str,
        value: Any,
        source: str = "manual"
    ):
        """Manually set a preference."""
        self.db.set_preference(
            key=key,
            value=value,
            learned_from=source,
            confidence=0.9 if source == "manual" else 0.5,
        )

    def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a preference value."""
        pref = self.db.get_preference(key)
        if pref:
            try:
                import json
                return json.loads(pref['value'])
            except:
                return pref['value']
        return default

    def suppress_level(self, level: str):
        """Suppress all alerts of a specific level."""
        suppressed = self.get_preference("suppressed_levels") or []
        if level not in suppressed:
            suppressed.append(level)
            self.set_preference("suppressed_levels", suppressed, "manual")

    def unsuppress_level(self, level: str):
        """Re-enable alerts of a specific level."""
        suppressed = self.get_preference("suppressed_levels") or []
        if level in suppressed:
            suppressed.remove(level)
            self.set_preference("suppressed_levels", suppressed, "manual")

    def suppress_category(self, category: str):
        """Suppress all alerts of a specific category."""
        suppressed = self.get_preference("suppressed_categories") or []
        if category not in suppressed:
            suppressed.append(category)
            self.set_preference("suppressed_categories", suppressed, "manual")

    def unsuppress_category(self, category: str):
        """Re-enable alerts of a specific category."""
        suppressed = self.get_preference("suppressed_categories") or []
        if category in suppressed:
            suppressed.remove(category)
            self.set_preference("suppressed_categories", suppressed, "manual")

    def get_suppressed(self) -> dict:
        """Get all suppressed levels and categories."""
        return {
            "levels": self.get_preference("suppressed_levels") or [],
            "categories": self.get_preference("suppressed_categories") or [],
        }

    def clear_suppressions(self):
        """Clear all suppressions."""
        self.set_preference("suppressed_levels", [], "manual")
        self.set_preference("suppressed_categories", [], "manual")

    def should_show_alert(self, alert: ClinicalAlert) -> bool:
        """Determine if an alert should be shown based on learned preferences."""
        # Check manual suppressions first
        suppressed_levels = self.get_preference("suppressed_levels") or []
        if alert.level.value in suppressed_levels:
            return False

        suppressed_categories = self.get_preference("suppressed_categories") or []
        if alert.category and alert.category in suppressed_categories:
            return False

        # Always show critical alerts (unless manually suppressed above)
        if alert.level == AlertLevel.ALERT:
            return True

        # Check user scores (more granular than helpfulness)
        score_key = f"alert_scores_{alert.level.value}"
        scores = self.get_preference(score_key)
        if scores and isinstance(scores, dict):
            if len(scores.get("scores", [])) >= 5:  # Need enough data
                avg = scores.get("avg", 3)
                if avg < 2.0:  # Average score below 2 = suppress
                    return False

        # Check category scores
        if alert.category:
            cat_score_key = f"category_scores_{alert.category}"
            cat_scores = self.get_preference(cat_score_key)
            if cat_scores and isinstance(cat_scores, dict):
                if len(cat_scores.get("scores", [])) >= 5:
                    avg = cat_scores.get("avg", 3)
                    if avg < 2.0:
                        return False

        # Check level helpfulness (legacy)
        level_key = f"alert_helpfulness_{alert.level.value}"
        level_pref = self.get_preference(level_key)

        if level_pref and isinstance(level_pref, dict):
            # If this level has low helpfulness rate, skip
            if level_pref.get('total', 0) >= 5:  # Need enough data
                if level_pref.get('rate', 1.0) < 0.3:  # Less than 30% helpful
                    return False

        # Check category helpfulness (legacy)
        if alert.category:
            cat_key = f"category_helpfulness_{alert.category}"
            cat_pref = self.get_preference(cat_key)

            if cat_pref and isinstance(cat_pref, dict):
                if cat_pref.get('total', 0) >= 5:
                    if cat_pref.get('rate', 1.0) < 0.2:  # Less than 20% helpful
                        return False

        return True

    def get_alert_stats(self) -> dict:
        """Get statistics about alert feedback."""
        return self.db.get_alert_stats()

    def get_all_preferences(self) -> dict[str, UserPreference]:
        """Get all learned preferences."""
        prefs = {}
        all_prefs = self.db.get_all_preferences()

        for key, value in all_prefs.items():
            db_pref = self.db.get_preference(key)
            if db_pref:
                prefs[key] = UserPreference(
                    key=key,
                    value=value,
                    confidence=db_pref.get('confidence', 0.5),
                    learned_from=db_pref.get('learned_from', 'unknown'),
                    update_count=db_pref.get('update_count', 1),
                )

        return prefs

    def export_preferences(self) -> dict:
        """Export preferences for backup/transfer."""
        return {
            "preferences": self.db.get_all_preferences(),
            "alert_stats": self.get_alert_stats(),
            "exported_at": datetime.now().isoformat(),
        }

    def get_session_summary(self) -> dict:
        """Get summary of this session's feedback."""
        if not self._session_feedback:
            return {"feedback_count": 0}

        helpful_count = sum(1 for f in self._session_feedback if f['was_helpful'])

        return {
            "feedback_count": len(self._session_feedback),
            "helpful_count": helpful_count,
            "helpfulness_rate": helpful_count / len(self._session_feedback),
            "categories": list(set(
                f['category'] for f in self._session_feedback if f.get('category')
            )),
        }
