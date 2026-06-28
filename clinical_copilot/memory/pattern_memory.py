"""Pattern recognition and memory for clinical workflows."""

import hashlib
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from .db import Database
from ..config import settings


class ClinicalPattern(BaseModel):
    """A recognized clinical pattern."""
    pattern_id: str
    pattern_type: str
    description: str
    frequency: int
    confidence: float
    last_seen: datetime
    trigger_conditions: dict


class PatternMemory:
    """Recognizes and remembers clinical patterns."""

    PATTERN_TYPES = {
        "workflow": "Recurring workflow sequences",
        "diagnostic": "Diagnostic reasoning patterns",
        "treatment": "Treatment decision patterns",
        "alert_response": "How user responds to alerts",
        "time_based": "Time-of-day patterns",
    }

    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()

    def _generate_pattern_id(
        self,
        pattern_type: str,
        description: str
    ) -> str:
        """Generate pattern ID from type and description."""
        combined = f"{pattern_type}:{description}"
        return hashlib.sha256(combined.encode()).hexdigest()[:12]

    def record_pattern(
        self,
        pattern_type: str,
        description: str,
        trigger_conditions: Optional[dict] = None
    ) -> str:
        """Record a clinical pattern observation."""
        pattern_id = self._generate_pattern_id(pattern_type, description)

        self.db.record_pattern(
            pattern_id=pattern_id,
            pattern_type=pattern_type,
            description=description,
            trigger_conditions=trigger_conditions,
        )

        return pattern_id

    def get_patterns(
        self,
        pattern_type: Optional[str] = None,
        min_frequency: int = 1,
        min_confidence: float = 0.0
    ) -> list[ClinicalPattern]:
        """Get patterns matching criteria."""
        if pattern_type:
            db_patterns = self.db.get_patterns_by_type(pattern_type)
        else:
            # Get all patterns
            db_patterns = []
            for ptype in self.PATTERN_TYPES:
                db_patterns.extend(self.db.get_patterns_by_type(ptype))

        patterns = []
        for p in db_patterns:
            if p['frequency'] >= min_frequency and p.get('confidence', 0) >= min_confidence:
                try:
                    import json
                    trigger = json.loads(p.get('trigger_conditions', '{}'))
                except:
                    trigger = {}

                patterns.append(ClinicalPattern(
                    pattern_id=p['id'],
                    pattern_type=p['pattern_type'],
                    description=p['description'],
                    frequency=p['frequency'],
                    confidence=p.get('confidence', 0.5),
                    last_seen=datetime.fromisoformat(p['last_seen']),
                    trigger_conditions=trigger,
                ))

        return sorted(patterns, key=lambda x: x.frequency, reverse=True)

    def find_matching_patterns(
        self,
        context: str,
        pattern_type: Optional[str] = None
    ) -> list[ClinicalPattern]:
        """Find patterns that match the current context."""
        all_patterns = self.get_patterns(pattern_type=pattern_type, min_frequency=2)

        matching = []
        context_lower = context.lower()

        for pattern in all_patterns:
            # Simple keyword matching
            desc_lower = pattern.description.lower()
            keywords = desc_lower.split()

            # Check if any keywords match
            matches = sum(1 for kw in keywords if kw in context_lower)
            if matches >= 2 or (len(keywords) <= 2 and matches >= 1):
                matching.append(pattern)

        return matching

    def get_workflow_suggestions(self, current_app: str) -> list[str]:
        """Get workflow suggestions based on patterns."""
        workflow_patterns = self.get_patterns(
            pattern_type="workflow",
            min_frequency=3,
            min_confidence=0.6
        )

        suggestions = []
        for pattern in workflow_patterns:
            trigger = pattern.trigger_conditions
            if trigger.get('app') == current_app or not trigger.get('app'):
                suggestions.append(pattern.description)

        return suggestions[:5]  # Top 5

    def record_workflow_transition(
        self,
        from_app: str,
        to_app: str,
        context: Optional[str] = None
    ):
        """Record a workflow transition between apps."""
        description = f"Transition: {from_app} -> {to_app}"
        self.record_pattern(
            pattern_type="workflow",
            description=description,
            trigger_conditions={
                "from_app": from_app,
                "to_app": to_app,
                "context": context,
            }
        )

    def get_pattern_summary(self) -> dict:
        """Get summary of all patterns."""
        summary = {
            "total_patterns": 0,
            "by_type": {},
        }

        for ptype in self.PATTERN_TYPES:
            patterns = self.get_patterns(pattern_type=ptype)
            summary["by_type"][ptype] = {
                "count": len(patterns),
                "top_patterns": [p.description for p in patterns[:3]],
            }
            summary["total_patterns"] += len(patterns)

        return summary
