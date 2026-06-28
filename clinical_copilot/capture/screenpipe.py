"""Screenpipe integration for screen capture and monitoring."""

import httpx
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel

from ..config import settings


class ScreenContent(BaseModel):
    """Captured screen content."""
    timestamp: datetime
    app_name: str
    window_title: str
    text_content: str
    ocr_text: Optional[str] = None
    frame_path: Optional[str] = None


class AudioContent(BaseModel):
    """Captured audio content."""
    timestamp: datetime
    transcription: str
    duration_seconds: float
    device: str


class ScreenpipeClient:
    """Client for Screenpipe REST API."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or settings.screenpipe.base_url
        self.timeout = settings.screenpipe.timeout
        self._client = httpx.Client(timeout=self.timeout)

    def health_check(self) -> bool:
        """Check if Screenpipe is running."""
        try:
            response = self._client.get(f"{self.base_url}/health")
            return response.status_code == 200
        except httpx.RequestError:
            return False

    def get_recent_screen(
        self,
        minutes: int = 1,
        app_filter: Optional[str] = None
    ) -> list[ScreenContent]:
        """Get recent screen captures."""
        # Use OCR content type and get more results to filter
        try:
            response = self._client.get(
                f"{self.base_url}/search",
                params={"content_type": "ocr", "limit": 10}
            )
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("data", []):
                if item.get("type") == "OCR":
                    content = item.get("content", {})
                    # Parse timestamp, handling Z suffix
                    ts_str = content.get("timestamp", "")
                    try:
                        if ts_str.endswith("Z"):
                            ts_str = ts_str[:-1]  # Remove Z suffix
                        timestamp = datetime.fromisoformat(ts_str) if ts_str else datetime.now()
                    except:
                        timestamp = datetime.now()

                    results.append(ScreenContent(
                        timestamp=timestamp,
                        app_name=content.get("app_name", "Unknown"),
                        window_title=content.get("window_name", ""),
                        text_content=content.get("text", ""),
                        ocr_text=content.get("text", ""),
                        frame_path=content.get("frame", None),
                    ))
            return results
        except httpx.RequestError as e:
            print(f"Screenpipe request error: {e}")
            return []

    def get_recent_audio(
        self,
        minutes: int = 5
    ) -> list[AudioContent]:
        """Get recent audio transcriptions."""
        params = {
            "content_type": "audio",
            "limit": 10,
            "start_time": (datetime.now() - timedelta(minutes=minutes)).isoformat(),
        }

        try:
            response = self._client.get(
                f"{self.base_url}/search",
                params=params
            )
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("data", []):
                if item.get("type") == "Audio":
                    content = item.get("content", {})
                    results.append(AudioContent(
                        timestamp=datetime.fromisoformat(
                            content.get("timestamp", datetime.now().isoformat())
                        ),
                        transcription=content.get("transcription", ""),
                        duration_seconds=content.get("duration", 0.0),
                        device=content.get("device_name", "Unknown"),
                    ))
            return results
        except httpx.RequestError as e:
            print(f"Screenpipe audio request error: {e}")
            return []

    def get_current_context(self) -> Optional[ScreenContent]:
        """Get the most recent screen content, prioritizing clinical apps."""
        results = self.get_recent_screen(minutes=1)

        # Skip Terminal/IDE to avoid capturing ourselves
        skip_apps = {"Terminal", "iTerm2", "Code", "VS Code", "Cursor", "Control Center", "Dock"}

        # Prefer browser/clinical apps
        for result in results:
            if result.app_name not in skip_apps and len(result.text_content) > 50:
                return result

        # Fallback to any content with text
        for result in results:
            if len(result.text_content) > 50:
                return result

        return results[0] if results else None

    def search(
        self,
        query: str,
        content_type: str = "all",
        limit: int = 20,
        hours_back: int = 24
    ) -> list[dict]:
        """Search through captured content."""
        params = {
            "q": query,
            "content_type": content_type,
            "limit": limit,
            "start_time": (datetime.now() - timedelta(hours=hours_back)).isoformat(),
        }

        try:
            response = self._client.get(
                f"{self.base_url}/search",
                params=params
            )
            response.raise_for_status()
            return response.json().get("data", [])
        except httpx.RequestError as e:
            print(f"Screenpipe search error: {e}")
            return []

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
