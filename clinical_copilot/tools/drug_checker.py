"""Drug interaction checker using local database."""

import sqlite3
import re
from pathlib import Path
from typing import Optional
from pydantic import BaseModel
from enum import Enum

from ..config import settings


class InteractionSeverity(str, Enum):
    CONTRAINDICATED = "contraindicated"
    MAJOR = "major"
    MODERATE = "moderate"
    MINOR = "minor"


class DrugInteraction(BaseModel):
    """A drug-drug interaction."""
    drug1: str
    drug2: str
    severity: InteractionSeverity
    description: str
    mechanism: Optional[str] = None
    recommendation: Optional[str] = None


class DrugInfo(BaseModel):
    """Information about a drug."""
    name: str
    generic_name: str
    drug_class: str
    common_interactions: list[str]


class DrugChecker:
    """Check for drug interactions using local database."""

    # Common high-risk interaction pairs
    # This is a simplified set - real implementation would use a full database
    KNOWN_INTERACTIONS = {
        # Anticoagulants
        ("warfarin", "aspirin"): {
            "severity": InteractionSeverity.MAJOR,
            "description": "Increased bleeding risk",
            "recommendation": "Monitor closely if combination required"
        },
        ("warfarin", "nsaid"): {
            "severity": InteractionSeverity.MAJOR,
            "description": "Increased bleeding risk and potential INR elevation",
            "recommendation": "Avoid NSAIDs if possible; use acetaminophen"
        },
        ("warfarin", "fluconazole"): {
            "severity": InteractionSeverity.MAJOR,
            "description": "CYP2C9 inhibition increases warfarin levels",
            "recommendation": "Reduce warfarin dose and monitor INR closely"
        },

        # QT prolongation
        ("amiodarone", "azithromycin"): {
            "severity": InteractionSeverity.MAJOR,
            "description": "Additive QT prolongation risk",
            "recommendation": "Avoid combination; use alternative antibiotic"
        },
        ("methadone", "ondansetron"): {
            "severity": InteractionSeverity.MAJOR,
            "description": "Additive QT prolongation risk",
            "recommendation": "Monitor QTc; consider alternative antiemetic"
        },

        # Serotonin syndrome
        ("ssri", "tramadol"): {
            "severity": InteractionSeverity.MAJOR,
            "description": "Risk of serotonin syndrome",
            "recommendation": "Use with caution; monitor for symptoms"
        },
        ("ssri", "maoi"): {
            "severity": InteractionSeverity.CONTRAINDICATED,
            "description": "High risk of serotonin syndrome",
            "recommendation": "Contraindicated - do not combine"
        },

        # Potassium
        ("lisinopril", "spironolactone"): {
            "severity": InteractionSeverity.MAJOR,
            "description": "Risk of severe hyperkalemia",
            "recommendation": "Monitor potassium closely; avoid in renal impairment"
        },
        ("lisinopril", "potassium"): {
            "severity": InteractionSeverity.MODERATE,
            "description": "Risk of hyperkalemia",
            "recommendation": "Monitor potassium levels"
        },

        # Metformin
        ("metformin", "contrast"): {
            "severity": InteractionSeverity.MAJOR,
            "description": "Risk of lactic acidosis with contrast",
            "recommendation": "Hold metformin 48h before/after contrast"
        },

        # Statins
        ("simvastatin", "amiodarone"): {
            "severity": InteractionSeverity.MAJOR,
            "description": "Increased statin levels - myopathy risk",
            "recommendation": "Max simvastatin 20mg or use alternative statin"
        },
        ("simvastatin", "amlodipine"): {
            "severity": InteractionSeverity.MODERATE,
            "description": "Increased statin levels",
            "recommendation": "Max simvastatin 20mg"
        },

        # Digoxin
        ("digoxin", "amiodarone"): {
            "severity": InteractionSeverity.MAJOR,
            "description": "Amiodarone increases digoxin levels",
            "recommendation": "Reduce digoxin dose by 50%"
        },
        ("digoxin", "verapamil"): {
            "severity": InteractionSeverity.MAJOR,
            "description": "Increased digoxin levels and AV block risk",
            "recommendation": "Monitor digoxin levels and HR"
        },
    }

    # Drug class mappings
    DRUG_CLASSES = {
        "nsaid": ["ibuprofen", "naproxen", "meloxicam", "diclofenac", "ketorolac", "indomethacin"],
        "ssri": ["sertraline", "fluoxetine", "paroxetine", "citalopram", "escitalopram"],
        "maoi": ["phenelzine", "tranylcypromine", "selegiline", "isocarboxazid"],
        "ace_inhibitor": ["lisinopril", "enalapril", "ramipril", "benazepril", "captopril"],
        "arb": ["losartan", "valsartan", "irbesartan", "olmesartan", "candesartan"],
        "statin": ["atorvastatin", "simvastatin", "rosuvastatin", "pravastatin"],
        "anticoagulant": ["warfarin", "apixaban", "rivaroxaban", "dabigatran", "edoxaban"],
    }

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.data_dir / "drug_interactions.db"
        self._init_db()

    def _init_db(self):
        """Initialize drug database if needed."""
        if self.db_path.exists():
            return

        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Create tables
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS interactions (
                drug1 TEXT,
                drug2 TEXT,
                severity TEXT,
                description TEXT,
                mechanism TEXT,
                recommendation TEXT,
                PRIMARY KEY (drug1, drug2)
            );

            CREATE INDEX IF NOT EXISTS idx_drug1 ON interactions(drug1);
            CREATE INDEX IF NOT EXISTS idx_drug2 ON interactions(drug2);
        """)

        # Populate with known interactions
        for (drug1, drug2), info in self.KNOWN_INTERACTIONS.items():
            cursor.execute("""
                INSERT OR REPLACE INTO interactions
                (drug1, drug2, severity, description, recommendation)
                VALUES (?, ?, ?, ?, ?)
            """, (
                drug1, drug2,
                info["severity"].value,
                info["description"],
                info.get("recommendation", "")
            ))

        conn.commit()
        conn.close()

    def _normalize_drug(self, drug_name: str) -> str:
        """Normalize drug name for matching."""
        return drug_name.lower().strip()

    def _get_drug_class(self, drug_name: str) -> Optional[str]:
        """Get the class of a drug."""
        normalized = self._normalize_drug(drug_name)
        for drug_class, members in self.DRUG_CLASSES.items():
            if normalized in members:
                return drug_class
        return None

    def check_interaction(
        self,
        drug1: str,
        drug2: str
    ) -> Optional[DrugInteraction]:
        """Check for interaction between two drugs."""
        d1 = self._normalize_drug(drug1)
        d2 = self._normalize_drug(drug2)

        # Check direct interaction
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM interactions
            WHERE (drug1 = ? AND drug2 = ?) OR (drug1 = ? AND drug2 = ?)
        """, (d1, d2, d2, d1))

        row = cursor.fetchone()
        conn.close()

        if row:
            return DrugInteraction(
                drug1=drug1,
                drug2=drug2,
                severity=InteractionSeverity(row[2]),
                description=row[3],
                mechanism=row[4],
                recommendation=row[5],
            )

        # Check class-based interaction
        class1 = self._get_drug_class(d1)
        class2 = self._get_drug_class(d2)

        if class1 and class2:
            key = (class1, class2)
            if key in self.KNOWN_INTERACTIONS:
                info = self.KNOWN_INTERACTIONS[key]
                return DrugInteraction(
                    drug1=drug1,
                    drug2=drug2,
                    severity=info["severity"],
                    description=info["description"],
                    recommendation=info.get("recommendation"),
                )

        # Check if one is a class name
        for (k1, k2), info in self.KNOWN_INTERACTIONS.items():
            if (d1 == k1 or class1 == k1) and (d2 == k2 or class2 == k2):
                return DrugInteraction(
                    drug1=drug1,
                    drug2=drug2,
                    severity=info["severity"],
                    description=info["description"],
                    recommendation=info.get("recommendation"),
                )
            if (d1 == k2 or class1 == k2) and (d2 == k1 or class2 == k1):
                return DrugInteraction(
                    drug1=drug1,
                    drug2=drug2,
                    severity=info["severity"],
                    description=info["description"],
                    recommendation=info.get("recommendation"),
                )

        return None

    def check_list(
        self,
        medications: list[str]
    ) -> list[DrugInteraction]:
        """Check a medication list for all interactions."""
        interactions = []

        for i, drug1 in enumerate(medications):
            for drug2 in medications[i + 1:]:
                interaction = self.check_interaction(drug1, drug2)
                if interaction:
                    interactions.append(interaction)

        # Sort by severity
        severity_order = {
            InteractionSeverity.CONTRAINDICATED: 0,
            InteractionSeverity.MAJOR: 1,
            InteractionSeverity.MODERATE: 2,
            InteractionSeverity.MINOR: 3,
        }
        interactions.sort(key=lambda x: severity_order[x.severity])

        return interactions

    def extract_medications(self, text: str) -> list[str]:
        """Extract medication names from text."""
        medications = []

        # Combine all known drugs
        all_drugs = set()
        for members in self.DRUG_CLASSES.values():
            all_drugs.update(members)

        # Add specific drugs from interactions
        for (d1, d2) in self.KNOWN_INTERACTIONS.keys():
            all_drugs.add(d1)
            all_drugs.add(d2)

        # Additional common medications
        all_drugs.update([
            "metformin", "amlodipine", "metoprolol", "omeprazole",
            "levothyroxine", "gabapentin", "prednisone", "furosemide",
            "hydrochlorothiazide", "losartan", "albuterol", "insulin",
            "acetaminophen", "aspirin", "amoxicillin", "azithromycin",
        ])

        text_lower = text.lower()
        for drug in all_drugs:
            if re.search(rf'\b{drug}\b', text_lower):
                medications.append(drug)

        return list(set(medications))

    def analyze_screen_for_interactions(
        self,
        text: str
    ) -> list[DrugInteraction]:
        """Analyze screen text for drug interactions."""
        medications = self.extract_medications(text)
        return self.check_list(medications)
