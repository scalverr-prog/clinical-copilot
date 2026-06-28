"""Patient encounter memory and tracking."""

import hashlib
import re
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel

from .db import Database
from ..analysis.clinical_analyzer import AnalysisResult, ClinicalAlert
from ..capture.screenpipe import ScreenContent
from ..config import settings


class PatientContext(BaseModel):
    """Context about a patient from memory."""
    patient_id: Optional[str]
    encounter_count: int
    first_seen: datetime
    last_seen: datetime
    key_findings: list[str]
    active_alerts: list[str]
    tags: list[str]


class PatientMemory:
    """Manages patient encounter memory."""

    # Patterns to extract patient identifiers
    MRN_PATTERNS = [
        r"(?i)MRN[:\s#]*(\d{6,10})",
        r"(?i)Patient\s*ID[:\s#]*(\d{6,10})",
        r"(?i)Medical\s*Record[:\s#]*(\d{6,10})",
    ]

    NAME_PATTERNS = [
        r"(?i)Patient[:\s]+([A-Z][a-z]+,?\s+[A-Z][a-z]+)",
        r"(?i)Name[:\s]+([A-Z][a-z]+,?\s+[A-Z][a-z]+)",
    ]

    def __init__(self, db: Optional[Database] = None):
        self.db = db or Database()
        self._current_patient_id: Optional[str] = None
        self._working_memory: list[dict] = []
        self._max_working_memory = settings.memory.max_working_memory

    def _extract_patient_id(self, text: str) -> Optional[str]:
        """Try to extract patient identifier from text."""
        # Try MRN patterns
        for pattern in self.MRN_PATTERNS:
            match = re.search(pattern, text)
            if match:
                return f"MRN:{match.group(1)}"

        # Try name patterns (hash for privacy)
        for pattern in self.NAME_PATTERNS:
            match = re.search(pattern, text)
            if match:
                name = match.group(1).strip()
                # Hash the name for privacy
                name_hash = hashlib.sha256(name.encode()).hexdigest()[:12]
                return f"NAME:{name_hash}"

        return None

    def _generate_encounter_id(
        self,
        content: ScreenContent,
        patient_id: Optional[str]
    ) -> str:
        """Generate unique encounter ID."""
        components = [
            content.timestamp.isoformat(),
            content.app_name,
            patient_id or "unknown",
        ]
        combined = "|".join(components)
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def record_encounter(
        self,
        content: ScreenContent,
        analysis: AnalysisResult
    ) -> str:
        """Record a clinical encounter."""
        # Extract patient ID from content
        patient_id = self._extract_patient_id(content.text_content)
        if not patient_id and content.ocr_text:
            patient_id = self._extract_patient_id(content.ocr_text)

        # Generate encounter ID
        encounter_id = self._generate_encounter_id(content, patient_id)

        # Extract tags from analysis
        tags = []
        for alert in analysis.alerts:
            if alert.category:
                tags.append(alert.category)

        # Convert alerts to dict
        alerts_data = [
            {
                "level": a.level.value,
                "message": a.message,
                "category": a.category,
            }
            for a in analysis.alerts
        ]

        # Save to database
        self.db.save_encounter(
            encounter_id=encounter_id,
            patient_id=patient_id,
            app_name=content.app_name,
            screen_context=analysis.screen_context,
            analysis_summary=analysis.summary,
            alerts=alerts_data,
            tags=list(set(tags)),
        )

        # Update working memory
        self._add_to_working_memory({
            "encounter_id": encounter_id,
            "patient_id": patient_id,
            "timestamp": content.timestamp,
            "summary": analysis.summary,
            "alerts": alerts_data,
        })

        # Track current patient
        if patient_id:
            self._current_patient_id = patient_id

        return encounter_id

    def _add_to_working_memory(self, item: dict):
        """Add item to working memory with size limit."""
        self._working_memory.append(item)
        if len(self._working_memory) > self._max_working_memory:
            self._working_memory.pop(0)

    def get_patient_context(
        self,
        patient_id: Optional[str] = None
    ) -> Optional[PatientContext]:
        """Get context about a patient from memory."""
        patient_id = patient_id or self._current_patient_id
        if not patient_id:
            return None

        # Search encounters for this patient
        encounters = self.db.search_encounters(patient_id, limit=50)
        if not encounters:
            return None

        # Build context
        key_findings = []
        active_alerts = []
        all_tags = []

        for enc in encounters:
            # Parse alerts
            try:
                alerts = json.loads(enc.get('alerts_json', '[]'))
                for alert in alerts:
                    if alert.get('level') in ['alert', 'warning']:
                        active_alerts.append(alert.get('message', ''))
            except:
                pass

            # Collect tags
            try:
                tags = json.loads(enc.get('tags', '[]'))
                all_tags.extend(tags)
            except:
                pass

            # Add summary as finding
            if enc.get('analysis_summary'):
                key_findings.append(enc['analysis_summary'])

        # Parse timestamps
        timestamps = [
            datetime.fromisoformat(e['timestamp'])
            for e in encounters
            if e.get('timestamp')
        ]

        return PatientContext(
            patient_id=patient_id,
            encounter_count=len(encounters),
            first_seen=min(timestamps) if timestamps else datetime.now(),
            last_seen=max(timestamps) if timestamps else datetime.now(),
            key_findings=key_findings[:10],  # Limit
            active_alerts=list(set(active_alerts))[:5],
            tags=list(set(all_tags)),
        )

    def get_working_memory_context(self) -> str:
        """Get working memory as context string for LLM."""
        if not self._working_memory:
            return "No recent encounters in working memory."

        context_parts = ["Recent encounters in this session:"]
        for item in self._working_memory[-5:]:  # Last 5
            context_parts.append(
                f"- [{item.get('timestamp', 'unknown')}] "
                f"Patient: {item.get('patient_id', 'unknown')} - "
                f"{item.get('summary', 'No summary')}"
            )

        return "\n".join(context_parts)

    def get_recent_history(self, hours: int = 24) -> list[dict]:
        """Get recent encounter history."""
        return self.db.get_recent_encounters(hours=hours)

    def search_history(self, query: str) -> list[dict]:
        """Search encounter history."""
        return self.db.search_encounters(query)

    def clear_working_memory(self):
        """Clear working memory (e.g., at session end)."""
        self._working_memory = []
        self._current_patient_id = None


# Need json import
import json
