"""Privacy filter to exclude personal apps from monitoring."""

import json
from pathlib import Path
from typing import Optional

from ..config import settings
from .screenpipe import ScreenContent


class PrivacyFilter:
    """Filter out personal/non-clinical content."""

    # Default excluded apps
    DEFAULT_EXCLUDED = [
        # Banking
        "Chase", "Wells Fargo", "Bank of America", "Citi", "Capital One",
        "Venmo", "PayPal", "Cash App", "Zelle",
        # Social Media
        "Facebook", "Twitter", "Instagram", "TikTok", "Snapchat",
        "LinkedIn", "Reddit", "Discord",
        # Personal Communication
        "Messages", "FaceTime", "WhatsApp", "Telegram", "Signal",
        # Personal Email (when not work)
        "Gmail", "Yahoo Mail", "Outlook Personal",
        # Password Managers
        "1Password", "Bitwarden", "LastPass", "Dashlane",
        # Entertainment
        "Netflix", "YouTube", "Spotify", "Apple Music", "Hulu",
        # Shopping
        "Amazon", "eBay", "Etsy",
    ]

    # Clinical apps to always include
    CLINICAL_APPS = [
        "Epic", "Cerner", "MEDITECH", "Allscripts", "athenahealth",
        "eClinicalWorks", "NextGen", "DrChrono", "Practice Fusion",
        "Clinical Insight", "Clinical Reasoning",
        # Research/Reference
        "UpToDate", "PubMed", "Epocrates", "Medscape",
        "DynaMed", "ClinicalKey",
    ]

    def __init__(self, custom_excluded: Optional[list[str]] = None):
        """Initialize privacy filter."""
        self.excluded_apps = set(settings.privacy.excluded_apps)
        if custom_excluded:
            self.excluded_apps.update(custom_excluded)

        self.clinical_only = settings.privacy.clinical_only_mode
        self._load_custom_filters()

    def _load_custom_filters(self):
        """Load custom filters from data file if exists."""
        filter_file = settings.data_dir / "excluded_apps.json"
        if filter_file.exists():
            with open(filter_file) as f:
                data = json.load(f)
                self.excluded_apps.update(data.get("excluded", []))

    def save_filters(self):
        """Save current filters to file."""
        filter_file = settings.data_dir / "excluded_apps.json"
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        with open(filter_file, "w") as f:
            json.dump({"excluded": list(self.excluded_apps)}, f, indent=2)

    def add_excluded(self, app_name: str):
        """Add an app to the exclusion list."""
        self.excluded_apps.add(app_name)
        self.save_filters()

    def remove_excluded(self, app_name: str):
        """Remove an app from the exclusion list."""
        self.excluded_apps.discard(app_name)
        self.save_filters()

    def is_clinical_app(self, app_name: str) -> bool:
        """Check if app is a known clinical application."""
        app_lower = app_name.lower()
        return any(
            clinical.lower() in app_lower
            for clinical in self.CLINICAL_APPS
        )

    def is_excluded(self, app_name: str) -> bool:
        """Check if an app should be excluded from monitoring."""
        app_lower = app_name.lower()

        # Always include clinical apps
        if self.is_clinical_app(app_name):
            return False

        # Check exclusion list
        for excluded in self.excluded_apps:
            if excluded.lower() in app_lower:
                return True

        # In clinical-only mode, exclude everything non-clinical
        if self.clinical_only and not self.is_clinical_app(app_name):
            return True

        return False

    def filter_content(
        self,
        content: ScreenContent
    ) -> Optional[ScreenContent]:
        """Filter screen content based on privacy rules.

        Returns None if content should be excluded, otherwise returns content.
        """
        if self.is_excluded(content.app_name):
            return None
        return content

    def filter_batch(
        self,
        contents: list[ScreenContent]
    ) -> list[ScreenContent]:
        """Filter a batch of screen contents."""
        return [
            c for c in contents
            if not self.is_excluded(c.app_name)
        ]

    def get_status(self) -> dict:
        """Get current privacy filter status."""
        return {
            "excluded_count": len(self.excluded_apps),
            "excluded_apps": sorted(self.excluded_apps),
            "clinical_only_mode": self.clinical_only,
            "clinical_apps": self.CLINICAL_APPS,
        }
