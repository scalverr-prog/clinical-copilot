"""Client for Clinical Insight API."""

import httpx
from typing import Optional
from pydantic import BaseModel

from ..config import settings


class ClinicalInsightResponse(BaseModel):
    """Response from Clinical Insight API."""
    analysis: str
    gaps: list[str]
    decision_questions: list[str]
    red_flags: list[str]
    confidence: float


class ClinicalInsightClient:
    """Client for Clinical Insight App API."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or settings.clinical_insight.base_url
        self.timeout = settings.clinical_insight.timeout
        self._client = httpx.Client(timeout=self.timeout)

    def health_check(self) -> bool:
        """Check if Clinical Insight is available."""
        try:
            response = self._client.get(f"{self.base_url}/health")
            return response.status_code == 200
        except httpx.RequestError:
            return False

    def analyze_case(
        self,
        presentation: str,
        context: Optional[str] = None
    ) -> ClinicalInsightResponse:
        """Send case to Clinical Insight for analysis."""
        payload = {
            "presentation": presentation,
            "context": context or "",
        }

        try:
            response = self._client.post(
                f"{self.base_url}/api/reasoning/analyze-freeform",
                json=payload
            )
            response.raise_for_status()
            data = response.json()

            return ClinicalInsightResponse(
                analysis=data.get("analysis", ""),
                gaps=data.get("gaps", []),
                decision_questions=data.get("decision_questions", []),
                red_flags=data.get("red_flags", []),
                confidence=data.get("confidence", 0.7),
            )
        except httpx.RequestError as e:
            raise RuntimeError(f"Clinical Insight request failed: {e}")

    def chat(
        self,
        message: str,
        conversation_id: Optional[str] = None
    ) -> dict:
        """Send a chat message to Clinical Insight."""
        payload = {
            "message": message,
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id

        try:
            response = self._client.post(
                f"{self.base_url}/api/chat/message",
                json=payload
            )
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            raise RuntimeError(f"Clinical Insight chat failed: {e}")

    def get_test_cases(self) -> list[dict]:
        """Get available test cases."""
        try:
            response = self._client.get(f"{self.base_url}/api/test-cases")
            response.raise_for_status()
            return response.json()
        except httpx.RequestError:
            return []

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class ClinicalReasoningClient:
    """Client for Clinical Reasoning Trainer."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or settings.clinical_reasoning.base_url
        self.timeout = settings.clinical_reasoning.timeout
        self._client = httpx.Client(timeout=self.timeout)

    def health_check(self) -> bool:
        """Check if service is available."""
        try:
            response = self._client.get(self.base_url)
            return response.status_code == 200
        except httpx.RequestError:
            return False

    def analyze(self, case_text: str) -> dict:
        """Analyze a case using the reasoning trainer."""
        try:
            response = self._client.post(
                f"{self.base_url}/api/analyze",
                json={"text": case_text}
            )
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            raise RuntimeError(f"Clinical Reasoning request failed: {e}")

    def close(self):
        """Close the HTTP client."""
        self._client.close()
