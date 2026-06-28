"""RAG Repository for Clinical Copilot - Local persistent storage with semantic search."""

import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import chromadb
from chromadb.config import Settings


class ClinicalRAG:
    """Local RAG repository for clinical data storage and retrieval."""

    def __init__(self, persist_dir: Optional[Path] = None):
        self.persist_dir = persist_dir or Path.home() / ".clinical-copilot" / "rag_db"
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        # Initialize ChromaDB with persistence
        self.client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False)
        )

        # Collections for different data types
        self.encounters = self.client.get_or_create_collection(
            name="clinical_encounters",
            metadata={"description": "Clinical encounters and screen captures"}
        )

        self.notes = self.client.get_or_create_collection(
            name="clinical_notes",
            metadata={"description": "Clinical notes and assessments"}
        )

        self.labs = self.client.get_or_create_collection(
            name="lab_results",
            metadata={"description": "Laboratory results"}
        )

        self.medications = self.client.get_or_create_collection(
            name="medications",
            metadata={"description": "Medication orders and history"}
        )

    def _generate_id(self, content: str, timestamp: str) -> str:
        """Generate unique ID for content."""
        return hashlib.md5(f"{content[:100]}{timestamp}".encode()).hexdigest()

    def _categorize_content(self, content: str) -> str:
        """Categorize content type based on keywords."""
        content_lower = content.lower()

        if any(kw in content_lower for kw in ['lab', 'result', 'wbc', 'hgb', 'plt', 'bmp', 'cmp', 'cbc']):
            return 'lab'
        elif any(kw in content_lower for kw in ['medication', 'rx', 'dose', 'mg', 'tablet', 'capsule', 'prn']):
            return 'medication'
        elif any(kw in content_lower for kw in ['assessment', 'plan', 'note', 'progress', 'hpi', 'subjective']):
            return 'note'
        else:
            return 'encounter'

    def store(
        self,
        content: str,
        patient_id: Optional[str] = None,
        source: str = "screen",
        category: Optional[str] = None,
        metadata: Optional[dict] = None
    ) -> str:
        """Store clinical content in the RAG repository."""
        if not content or len(content.strip()) < 20:
            return None

        timestamp = datetime.now().isoformat()
        doc_id = self._generate_id(content, timestamp)

        # Auto-categorize if not specified
        if category is None:
            category = self._categorize_content(content)

        # Build metadata
        doc_metadata = {
            "timestamp": timestamp,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": datetime.now().strftime("%H:%M:%S"),
            "patient_id": patient_id or "unknown",
            "source": source,
            "category": category,
            "content_length": len(content)
        }
        if metadata:
            doc_metadata.update(metadata)

        # Select collection based on category
        collection = {
            'lab': self.labs,
            'medication': self.medications,
            'note': self.notes,
            'encounter': self.encounters
        }.get(category, self.encounters)

        # Check for duplicates (same content within last hour)
        existing = collection.get(
            where={"patient_id": patient_id or "unknown"},
            limit=10
        )
        if existing and existing['documents']:
            for doc in existing['documents']:
                if doc[:200] == content[:200]:
                    return None  # Skip duplicate

        # Store in collection
        collection.add(
            documents=[content],
            metadatas=[doc_metadata],
            ids=[doc_id]
        )

        return doc_id

    def query(
        self,
        query_text: str,
        patient_id: Optional[str] = None,
        category: Optional[str] = None,
        n_results: int = 10,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> list[dict]:
        """Query the RAG repository with semantic search."""
        results = []

        # Build where filter
        where_filter = {}
        if patient_id:
            where_filter["patient_id"] = patient_id

        # Select collections to search
        if category:
            collections = [{
                'lab': self.labs,
                'medication': self.medications,
                'note': self.notes,
                'encounter': self.encounters
            }.get(category, self.encounters)]
        else:
            collections = [self.encounters, self.notes, self.labs, self.medications]

        # Search each collection
        for collection in collections:
            try:
                search_results = collection.query(
                    query_texts=[query_text],
                    n_results=n_results,
                    where=where_filter if where_filter else None
                )

                if search_results and search_results['documents']:
                    for i, doc in enumerate(search_results['documents'][0]):
                        meta = search_results['metadatas'][0][i] if search_results['metadatas'] else {}
                        distance = search_results['distances'][0][i] if search_results.get('distances') else 0

                        # Filter by date if specified
                        if date_from or date_to:
                            doc_date = datetime.fromisoformat(meta.get('timestamp', '2000-01-01'))
                            if date_from and doc_date < date_from:
                                continue
                            if date_to and doc_date > date_to:
                                continue

                        results.append({
                            "content": doc,
                            "metadata": meta,
                            "relevance": 1 - distance,  # Convert distance to relevance
                            "collection": collection.name
                        })
            except Exception as e:
                continue

        # Sort by relevance
        results.sort(key=lambda x: x['relevance'], reverse=True)
        return results[:n_results]

    def get_patient_timeline(
        self,
        patient_id: str,
        days: int = 7,
        limit: int = 50
    ) -> list[dict]:
        """Get chronological timeline for a patient."""
        results = []
        date_from = datetime.now() - timedelta(days=days)

        for collection in [self.encounters, self.notes, self.labs, self.medications]:
            try:
                data = collection.get(
                    where={"patient_id": patient_id},
                    limit=limit
                )

                if data and data['documents']:
                    for i, doc in enumerate(data['documents']):
                        meta = data['metadatas'][i] if data['metadatas'] else {}
                        timestamp = meta.get('timestamp', '')

                        if timestamp:
                            doc_date = datetime.fromisoformat(timestamp)
                            if doc_date >= date_from:
                                results.append({
                                    "content": doc,
                                    "metadata": meta,
                                    "timestamp": timestamp,
                                    "collection": collection.name
                                })
            except Exception as e:
                continue

        # Sort chronologically
        results.sort(key=lambda x: x['timestamp'], reverse=True)
        return results[:limit]

    def get_stats(self) -> dict:
        """Get repository statistics."""
        return {
            "encounters": self.encounters.count(),
            "notes": self.notes.count(),
            "labs": self.labs.count(),
            "medications": self.medications.count(),
            "total": (
                self.encounters.count() +
                self.notes.count() +
                self.labs.count() +
                self.medications.count()
            ),
            "persist_dir": str(self.persist_dir)
        }

    def get_recent(self, hours: int = 24, limit: int = 20) -> list[dict]:
        """Get recent entries across all collections."""
        results = []
        cutoff = datetime.now() - timedelta(hours=hours)
        cutoff_str = cutoff.isoformat()

        for collection in [self.encounters, self.notes, self.labs, self.medications]:
            try:
                data = collection.get(limit=100)

                if data and data['documents']:
                    for i, doc in enumerate(data['documents']):
                        meta = data['metadatas'][i] if data['metadatas'] else {}
                        timestamp = meta.get('timestamp', '')

                        if timestamp and timestamp >= cutoff_str:
                            results.append({
                                "content": doc[:300],
                                "metadata": meta,
                                "timestamp": timestamp,
                                "collection": collection.name
                            })
            except Exception as e:
                continue

        # Sort by timestamp descending
        results.sort(key=lambda x: x['timestamp'], reverse=True)
        return results[:limit]

    def delete_patient(self, patient_id: str) -> int:
        """Delete all data for a patient (for privacy)."""
        deleted = 0

        for collection in [self.encounters, self.notes, self.labs, self.medications]:
            try:
                data = collection.get(where={"patient_id": patient_id})
                if data and data['ids']:
                    collection.delete(ids=data['ids'])
                    deleted += len(data['ids'])
            except Exception as e:
                continue

        return deleted

    def export_patient(self, patient_id: str) -> dict:
        """Export all data for a patient."""
        export = {
            "patient_id": patient_id,
            "exported_at": datetime.now().isoformat(),
            "data": []
        }

        for collection in [self.encounters, self.notes, self.labs, self.medications]:
            try:
                data = collection.get(where={"patient_id": patient_id})
                if data and data['documents']:
                    for i, doc in enumerate(data['documents']):
                        export["data"].append({
                            "content": doc,
                            "metadata": data['metadatas'][i] if data['metadatas'] else {},
                            "collection": collection.name
                        })
            except Exception as e:
                continue

        return export


# Singleton instance
_rag_instance = None


def get_rag() -> ClinicalRAG:
    """Get the RAG singleton instance."""
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = ClinicalRAG()
    return _rag_instance
