"""Clinical Case RAG Store - Vector database for clinical case learning."""

import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
import chromadb
from chromadb.config import Settings
from pydantic import BaseModel


def get_bundled_db_path() -> Path:
    """Get path to bundled database included with package."""
    # Check relative to this file (in installed package)
    module_dir = Path(__file__).parent.parent.parent  # backend/
    bundled = module_dir / "data" / "case_db"
    if bundled.exists():
        return bundled
    return None


def install_bundled_database(target_dir: Path) -> bool:
    """Copy bundled database to user's local directory."""
    bundled = get_bundled_db_path()
    if not bundled:
        return False

    try:
        if target_dir.exists():
            # Check if it's empty or just created
            if not any(target_dir.iterdir()):
                shutil.rmtree(target_dir)
            else:
                return True  # Already has data

        shutil.copytree(bundled, target_dir)
        print(f"Installed {sum(1 for _ in bundled.rglob('*'))} evidence-based cases from bundled database")
        return True
    except Exception as e:
        print(f"Warning: Could not install bundled database: {e}")
        return False


class StoredCase(BaseModel):
    """A stored clinical case with analysis."""
    case_id: str
    presentation: str
    diagnosis: Optional[str] = None
    critical_flags: list[str] = []
    teaching_points: list[str] = []
    outcome: Optional[str] = None
    timestamp: str
    category: Optional[str] = None  # e.g., "infectious", "cardiac", "endocrine"


class SimilarCase(BaseModel):
    """A similar case retrieved from the RAG store."""
    case_id: str
    presentation_summary: str
    diagnosis: Optional[str]
    relevance: float
    teaching_points: list[str]
    critical_flags: list[str]


class ClinicalCaseRAG:
    """RAG store for clinical cases with semantic search."""

    # Clinical categories for organization
    CATEGORIES = [
        "infectious", "cardiac", "pulmonary", "endocrine", "renal",
        "neurologic", "hematologic", "oncologic", "rheumatologic",
        "gastrointestinal", "dermatologic", "psychiatric", "surgical",
        "toxicologic", "trauma", "obstetric", "pediatric", "geriatric"
    ]

    def __init__(self, persist_dir: Optional[Path] = None):
        self.persist_dir = persist_dir or Path.home() / ".clinical-insight" / "case_db"

        # Auto-install bundled database on first run
        if not self.persist_dir.exists() or not any(self.persist_dir.iterdir()):
            self.persist_dir.mkdir(parents=True, exist_ok=True)
            install_bundled_database(self.persist_dir)
        else:
            self.persist_dir.mkdir(parents=True, exist_ok=True)

        # Initialize ChromaDB with persistence
        self.client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False)
        )

        # Main case collection
        self.cases = self.client.get_or_create_collection(
            name="clinical_cases",
            metadata={"description": "Clinical cases with presentations and diagnoses"}
        )

        # Teaching points collection for quick retrieval
        self.teachings = self.client.get_or_create_collection(
            name="teaching_points",
            metadata={"description": "Clinical teaching points and pearls"}
        )

        # Critical flags collection for pattern matching
        self.flags = self.client.get_or_create_collection(
            name="critical_flags",
            metadata={"description": "Critical flags and safety concerns"}
        )

    def _generate_id(self, content: str) -> str:
        """Generate unique ID from content."""
        return hashlib.md5(f"{content[:200]}{datetime.now().isoformat()}".encode()).hexdigest()

    def _detect_category(self, presentation: str) -> str:
        """Auto-detect clinical category from presentation."""
        presentation_lower = presentation.lower()

        category_keywords = {
            "infectious": ["infection", "fever", "sepsis", "antibiotic", "culture", "abscess", "cellulitis"],
            "cardiac": ["chest pain", "mi", "stemi", "nstemi", "heart failure", "chf", "afib", "arrhythmia", "cardiac"],
            "pulmonary": ["dyspnea", "copd", "asthma", "pneumonia", "pe", "pulmonary", "respiratory"],
            "endocrine": ["diabetes", "dka", "hhs", "thyroid", "adrenal", "glucose", "a1c", "insulin"],
            "renal": ["aki", "ckd", "creatinine", "dialysis", "kidney", "gfr", "proteinuria"],
            "neurologic": ["stroke", "cva", "seizure", "altered mental", "headache", "neuro"],
            "hematologic": ["anemia", "thrombocytopenia", "bleeding", "coagulopathy", "dvt", "pe"],
            "gastrointestinal": ["gi bleed", "abdominal pain", "nausea", "vomiting", "diarrhea", "liver"],
        }

        for category, keywords in category_keywords.items():
            if any(kw in presentation_lower for kw in keywords):
                return category

        return "general"

    def store_case(
        self,
        presentation: str,
        diagnosis: Optional[str] = None,
        critical_flags: list[str] = None,
        teaching_points: list[str] = None,
        outcome: Optional[str] = None,
        category: Optional[str] = None
    ) -> str:
        """Store a clinical case in the RAG database."""
        if not presentation or len(presentation.strip()) < 50:
            return None

        case_id = self._generate_id(presentation)
        timestamp = datetime.now().isoformat()
        detected_category = category or self._detect_category(presentation)

        # Build case metadata
        metadata = {
            "timestamp": timestamp,
            "category": detected_category,
            "has_diagnosis": bool(diagnosis),
            "flag_count": len(critical_flags) if critical_flags else 0,
            "teaching_count": len(teaching_points) if teaching_points else 0,
        }
        if diagnosis:
            metadata["diagnosis"] = diagnosis[:200]  # ChromaDB has metadata size limits
        if outcome:
            metadata["outcome"] = outcome[:200]

        # Store the main case
        self.cases.add(
            documents=[presentation],
            metadatas=[metadata],
            ids=[case_id]
        )

        # Store teaching points separately for better retrieval
        if teaching_points:
            for i, point in enumerate(teaching_points):
                teaching_id = f"{case_id}_t{i}"
                self.teachings.add(
                    documents=[point],
                    metadatas={
                        "case_id": case_id,
                        "category": detected_category,
                        "diagnosis": diagnosis or "",
                        "timestamp": timestamp
                    },
                    ids=[teaching_id]
                )

        # Store critical flags separately
        if critical_flags:
            for i, flag in enumerate(critical_flags):
                flag_id = f"{case_id}_f{i}"
                self.flags.add(
                    documents=[flag],
                    metadatas={
                        "case_id": case_id,
                        "category": detected_category,
                        "diagnosis": diagnosis or "",
                        "timestamp": timestamp
                    },
                    ids=[flag_id]
                )

        return case_id

    def find_similar_cases(
        self,
        presentation: str,
        n_results: int = 5,
        category: Optional[str] = None,
        min_relevance: float = 0.3
    ) -> list[SimilarCase]:
        """Find similar cases to the given presentation."""
        where_filter = None
        if category:
            where_filter = {"category": category}

        results = self.cases.query(
            query_texts=[presentation],
            n_results=n_results,
            where=where_filter
        )

        similar_cases = []
        if results and results['documents']:
            for i, doc in enumerate(results['documents'][0]):
                metadata = results['metadatas'][0][i] if results['metadatas'] else {}
                distance = results['distances'][0][i] if results.get('distances') else 0
                relevance = 1 - distance

                if relevance < min_relevance:
                    continue

                # Get associated teaching points and flags
                case_id = results['ids'][0][i]
                teaching_points = self._get_case_teachings(case_id)
                critical_flags = self._get_case_flags(case_id)

                similar_cases.append(SimilarCase(
                    case_id=case_id,
                    presentation_summary=doc[:300] + "..." if len(doc) > 300 else doc,
                    diagnosis=metadata.get("diagnosis"),
                    relevance=relevance,
                    teaching_points=teaching_points,
                    critical_flags=critical_flags
                ))

        return similar_cases

    def _get_case_teachings(self, case_id: str) -> list[str]:
        """Get teaching points for a specific case."""
        results = self.teachings.get(
            where={"case_id": case_id},
            limit=10
        )
        return results['documents'] if results and results['documents'] else []

    def _get_case_flags(self, case_id: str) -> list[str]:
        """Get critical flags for a specific case."""
        results = self.flags.get(
            where={"case_id": case_id},
            limit=10
        )
        return results['documents'] if results and results['documents'] else []

    def search_teaching_points(
        self,
        query: str,
        n_results: int = 10,
        category: Optional[str] = None
    ) -> list[dict]:
        """Search for relevant teaching points."""
        where_filter = None
        if category:
            where_filter = {"category": category}

        results = self.teachings.query(
            query_texts=[query],
            n_results=n_results,
            where=where_filter
        )

        points = []
        if results and results['documents']:
            for i, doc in enumerate(results['documents'][0]):
                metadata = results['metadatas'][0][i] if results['metadatas'] else {}
                distance = results['distances'][0][i] if results.get('distances') else 0

                points.append({
                    "teaching_point": doc,
                    "diagnosis": metadata.get("diagnosis", ""),
                    "category": metadata.get("category", ""),
                    "relevance": 1 - distance
                })

        return points

    def search_critical_flags(
        self,
        query: str,
        n_results: int = 10
    ) -> list[dict]:
        """Search for relevant critical flags from past cases."""
        results = self.flags.query(
            query_texts=[query],
            n_results=n_results
        )

        flags = []
        if results and results['documents']:
            for i, doc in enumerate(results['documents'][0]):
                metadata = results['metadatas'][0][i] if results['metadatas'] else {}
                distance = results['distances'][0][i] if results.get('distances') else 0

                flags.append({
                    "flag": doc,
                    "from_diagnosis": metadata.get("diagnosis", ""),
                    "category": metadata.get("category", ""),
                    "relevance": 1 - distance
                })

        return flags

    def get_context_for_analysis(
        self,
        presentation: str,
        max_context_items: int = 3
    ) -> str:
        """Build context string from similar cases for LLM analysis."""
        similar = self.find_similar_cases(presentation, n_results=3)
        teachings = self.search_teaching_points(presentation, n_results=5)

        if not similar and not teachings:
            return ""

        context_parts = []

        if similar:
            context_parts.append("## Similar Past Cases")
            for case in similar[:max_context_items]:
                context_parts.append(f"\n**Case (relevance: {case.relevance:.0%}):**")
                if case.diagnosis:
                    context_parts.append(f"Diagnosis: {case.diagnosis}")
                if case.critical_flags:
                    context_parts.append(f"Key flags: {', '.join(case.critical_flags[:3])}")
                if case.teaching_points:
                    context_parts.append(f"Teaching: {case.teaching_points[0]}")

        if teachings:
            unique_teachings = []
            seen = set()
            for t in teachings:
                if t["teaching_point"] not in seen:
                    unique_teachings.append(t)
                    seen.add(t["teaching_point"])

            if unique_teachings:
                context_parts.append("\n## Relevant Teaching Points")
                for t in unique_teachings[:5]:
                    context_parts.append(f"- {t['teaching_point']}")

        return "\n".join(context_parts)

    def get_stats(self) -> dict:
        """Get statistics about stored cases."""
        # Get category distribution
        all_cases = self.cases.get(limit=1000)
        categories = {}
        diagnoses = set()

        if all_cases and all_cases['metadatas']:
            for meta in all_cases['metadatas']:
                cat = meta.get('category', 'unknown')
                categories[cat] = categories.get(cat, 0) + 1
                if meta.get('diagnosis'):
                    diagnoses.add(meta['diagnosis'])

        return {
            "total_cases": self.cases.count(),
            "total_teaching_points": self.teachings.count(),
            "total_critical_flags": self.flags.count(),
            "categories": categories,
            "unique_diagnoses": len(diagnoses),
            "persist_dir": str(self.persist_dir)
        }

    def store_from_analysis(
        self,
        presentation: str,
        analysis: dict,
        actual_diagnosis: Optional[str] = None
    ) -> str:
        """Store a case from an analysis result."""
        critical_flags = analysis.get("critical_flags", [])
        teaching_points = []

        # Extract teaching points from analysis
        if analysis.get("recommended_next_steps"):
            teaching_points.extend(analysis["recommended_next_steps"][:3])
        if analysis.get("pattern_breaks"):
            for pb in analysis["pattern_breaks"][:2]:
                if isinstance(pb, dict):
                    teaching_points.append(pb.get("observation", ""))
                else:
                    teaching_points.append(str(pb))

        return self.store_case(
            presentation=presentation,
            diagnosis=actual_diagnosis,
            critical_flags=critical_flags,
            teaching_points=teaching_points,
            outcome=None
        )


# Singleton instance
_case_rag_instance = None


def get_case_rag() -> ClinicalCaseRAG:
    """Get the case RAG singleton instance."""
    global _case_rag_instance
    if _case_rag_instance is None:
        _case_rag_instance = ClinicalCaseRAG()
    return _case_rag_instance
