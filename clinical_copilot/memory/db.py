"""SQLite database for memory persistence."""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Any
from contextlib import contextmanager

from ..config import settings


class Database:
    """SQLite database for ClinicalCopilot memory."""

    SCHEMA = """
    -- Patient encounters
    CREATE TABLE IF NOT EXISTS encounters (
        id TEXT PRIMARY KEY,
        patient_id TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        app_name TEXT,
        screen_context TEXT,
        analysis_summary TEXT,
        alerts_json TEXT,
        tags TEXT,
        specialty_mode TEXT
    );

    -- User preferences (learned over time)
    CREATE TABLE IF NOT EXISTS preferences (
        key TEXT PRIMARY KEY,
        value TEXT,
        learned_from TEXT,
        confidence REAL DEFAULT 0.5,
        update_count INTEGER DEFAULT 1,
        last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    -- Clinical patterns (recognized patterns)
    CREATE TABLE IF NOT EXISTS patterns (
        id TEXT PRIMARY KEY,
        pattern_type TEXT,
        description TEXT,
        trigger_conditions TEXT,
        frequency INTEGER DEFAULT 1,
        last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
        confidence REAL DEFAULT 0.5
    );

    -- Alert history
    CREATE TABLE IF NOT EXISTS alert_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        level TEXT,
        message TEXT,
        source_app TEXT,
        was_helpful INTEGER DEFAULT NULL,
        user_action TEXT
    );

    -- Session log
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        start_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        end_time DATETIME,
        specialty_mode TEXT,
        encounter_count INTEGER DEFAULT 0,
        alert_count INTEGER DEFAULT 0
    );

    -- Indexes for performance
    CREATE INDEX IF NOT EXISTS idx_encounters_timestamp ON encounters(timestamp);
    CREATE INDEX IF NOT EXISTS idx_encounters_patient ON encounters(patient_id);
    CREATE INDEX IF NOT EXISTS idx_patterns_type ON patterns(pattern_type);
    CREATE INDEX IF NOT EXISTS idx_alert_history_timestamp ON alert_history(timestamp);
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.memory.db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with self.connection() as conn:
            conn.executescript(self.SCHEMA)

    @contextmanager
    def connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # Encounter methods
    def save_encounter(
        self,
        encounter_id: str,
        patient_id: Optional[str],
        app_name: str,
        screen_context: str,
        analysis_summary: str,
        alerts: list[dict],
        tags: Optional[list[str]] = None,
        specialty_mode: Optional[str] = None
    ):
        """Save a clinical encounter."""
        with self.connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO encounters
                (id, patient_id, app_name, screen_context, analysis_summary,
                 alerts_json, tags, specialty_mode, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                encounter_id,
                patient_id,
                app_name,
                screen_context,
                analysis_summary,
                json.dumps(alerts),
                json.dumps(tags or []),
                specialty_mode or settings.specialty_mode,
                datetime.now().isoformat(),
            ))

    def get_recent_encounters(
        self,
        hours: int = 24,
        limit: int = 50
    ) -> list[dict]:
        """Get recent encounters."""
        with self.connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM encounters
                WHERE timestamp > datetime('now', ?)
                ORDER BY timestamp DESC
                LIMIT ?
            """, (f'-{hours} hours', limit))

            return [dict(row) for row in cursor.fetchall()]

    def search_encounters(
        self,
        query: str,
        limit: int = 20
    ) -> list[dict]:
        """Search encounters by text."""
        with self.connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM encounters
                WHERE screen_context LIKE ? OR analysis_summary LIKE ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (f'%{query}%', f'%{query}%', limit))

            return [dict(row) for row in cursor.fetchall()]

    # Preference methods
    def get_preference(self, key: str) -> Optional[dict]:
        """Get a user preference."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM preferences WHERE key = ?",
                (key,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def set_preference(
        self,
        key: str,
        value: Any,
        learned_from: str = "manual",
        confidence: float = 0.8
    ):
        """Set a user preference."""
        value_str = json.dumps(value) if not isinstance(value, str) else value

        with self.connection() as conn:
            # Check if exists
            existing = self.get_preference(key)

            if existing:
                # Update with increased confidence
                new_confidence = min(0.99, existing['confidence'] + 0.05)
                conn.execute("""
                    UPDATE preferences
                    SET value = ?, confidence = ?, update_count = update_count + 1,
                        last_updated = ?
                    WHERE key = ?
                """, (value_str, new_confidence, datetime.now().isoformat(), key))
            else:
                conn.execute("""
                    INSERT INTO preferences (key, value, learned_from, confidence)
                    VALUES (?, ?, ?, ?)
                """, (key, value_str, learned_from, confidence))

    def get_all_preferences(self) -> dict[str, Any]:
        """Get all preferences."""
        with self.connection() as conn:
            cursor = conn.execute("SELECT key, value FROM preferences")
            prefs = {}
            for row in cursor.fetchall():
                try:
                    prefs[row['key']] = json.loads(row['value'])
                except json.JSONDecodeError:
                    prefs[row['key']] = row['value']
            return prefs

    # Pattern methods
    def record_pattern(
        self,
        pattern_id: str,
        pattern_type: str,
        description: str,
        trigger_conditions: Optional[dict] = None
    ):
        """Record or update a clinical pattern."""
        with self.connection() as conn:
            existing = conn.execute(
                "SELECT * FROM patterns WHERE id = ?",
                (pattern_id,)
            ).fetchone()

            if existing:
                conn.execute("""
                    UPDATE patterns
                    SET frequency = frequency + 1,
                        last_seen = ?,
                        confidence = MIN(0.99, confidence + 0.02)
                    WHERE id = ?
                """, (datetime.now().isoformat(), pattern_id))
            else:
                conn.execute("""
                    INSERT INTO patterns
                    (id, pattern_type, description, trigger_conditions)
                    VALUES (?, ?, ?, ?)
                """, (
                    pattern_id,
                    pattern_type,
                    description,
                    json.dumps(trigger_conditions or {}),
                ))

    def get_patterns_by_type(self, pattern_type: str) -> list[dict]:
        """Get patterns of a specific type."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM patterns WHERE pattern_type = ? ORDER BY frequency DESC",
                (pattern_type,)
            )
            return [dict(row) for row in cursor.fetchall()]

    # Alert history methods
    def record_alert(
        self,
        level: str,
        message: str,
        source_app: str
    ) -> int:
        """Record an alert shown to user."""
        with self.connection() as conn:
            cursor = conn.execute("""
                INSERT INTO alert_history (level, message, source_app)
                VALUES (?, ?, ?)
            """, (level, message, source_app))
            return cursor.lastrowid

    def mark_alert_feedback(
        self,
        alert_id: int,
        was_helpful: bool,
        user_action: Optional[str] = None
    ):
        """Record user feedback on an alert."""
        with self.connection() as conn:
            conn.execute("""
                UPDATE alert_history
                SET was_helpful = ?, user_action = ?
                WHERE id = ?
            """, (1 if was_helpful else 0, user_action, alert_id))

    def get_alert_stats(self) -> dict:
        """Get alert statistics."""
        with self.connection() as conn:
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN was_helpful = 1 THEN 1 ELSE 0 END) as helpful,
                    SUM(CASE WHEN was_helpful = 0 THEN 1 ELSE 0 END) as not_helpful
                FROM alert_history
            """)
            row = cursor.fetchone()
            return dict(row) if row else {}

    # Session methods
    def start_session(self, specialty_mode: str) -> int:
        """Start a new session."""
        with self.connection() as conn:
            cursor = conn.execute("""
                INSERT INTO sessions (specialty_mode)
                VALUES (?)
            """, (specialty_mode,))
            return cursor.lastrowid

    def end_session(
        self,
        session_id: int,
        encounter_count: int,
        alert_count: int
    ):
        """End a session."""
        with self.connection() as conn:
            conn.execute("""
                UPDATE sessions
                SET end_time = ?, encounter_count = ?, alert_count = ?
                WHERE id = ?
            """, (datetime.now().isoformat(), encounter_count, alert_count, session_id))

    # Stats
    def get_stats(self) -> dict:
        """Get overall database statistics."""
        with self.connection() as conn:
            stats = {}

            for table in ['encounters', 'preferences', 'patterns', 'alert_history']:
                cursor = conn.execute(f"SELECT COUNT(*) as count FROM {table}")
                stats[f"{table}_count"] = cursor.fetchone()['count']

            return stats
