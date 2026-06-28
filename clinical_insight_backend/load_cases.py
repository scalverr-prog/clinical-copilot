#!/usr/bin/env python3
"""Load evidence-based cases from clinical-reasoning-trainer into RAG database."""

import re
import json
from pathlib import Path
from app.services.case_rag import ClinicalCaseRAG


def parse_typescript_cases(ts_file: Path) -> list[dict]:
    """Parse TypeScript cases file to extract case data."""
    content = ts_file.read_text()

    cases = []

    # Find all case objects in the array
    # Pattern to match each case object
    case_pattern = r'\{\s*name:\s*"([^"]+)".*?mrn:\s*"([^"]+)".*?age:\s*(\d+).*?chief_complaint:\s*"([^"]+)".*?diagnosis:\s*"([^"]+)".*?recent_notes:\s*"([^"]+)".*?labs:\s*"([^"]*)"'

    # Use DOTALL to match across lines
    matches = re.findall(case_pattern, content, re.DOTALL)

    for match in matches:
        name, mrn, age, chief_complaint, diagnosis, recent_notes, labs = match

        # Clean up escaped characters
        recent_notes = recent_notes.replace('\\n', '\n').replace('\\"', '"')

        # Build presentation text
        presentation = f"""Patient: {name} (MRN: {mrn})
Age: {age}

Chief Complaint: {chief_complaint}

Clinical Notes:
{recent_notes}

Labs: {labs}
"""

        cases.append({
            "presentation": presentation,
            "diagnosis": diagnosis,
            "name": name,
            "mrn": mrn,
        })

    return cases


def load_cases_to_rag():
    """Load all cases into RAG database."""
    ts_file = Path("/Users/scalver/clinical-reasoning-trainer/src/data/cases.ts")

    if not ts_file.exists():
        print(f"Error: Cases file not found at {ts_file}")
        return

    print(f"Parsing cases from {ts_file}...")
    cases = parse_typescript_cases(ts_file)
    print(f"Found {len(cases)} cases")

    # Initialize RAG
    rag = ClinicalCaseRAG()

    # Check current stats
    stats = rag.get_stats()
    print(f"Current RAG stats: {stats['total_cases']} cases")

    # Load cases
    loaded = 0
    skipped = 0

    for i, case in enumerate(cases):
        try:
            # Extract teaching points from diagnosis
            teaching_points = [f"Diagnosis: {case['diagnosis']}"]

            case_id = rag.store_case(
                presentation=case["presentation"],
                diagnosis=case["diagnosis"],
                teaching_points=teaching_points,
            )

            if case_id:
                loaded += 1
            else:
                skipped += 1

            if (i + 1) % 100 == 0:
                print(f"  Processed {i + 1}/{len(cases)}...")

        except Exception as e:
            print(f"  Error loading case {case['name']}: {e}")
            skipped += 1

    # Final stats
    final_stats = rag.get_stats()
    print(f"\nDone!")
    print(f"  Loaded: {loaded}")
    print(f"  Skipped (duplicates): {skipped}")
    print(f"  Total in RAG: {final_stats['total_cases']}")
    print(f"  Categories: {final_stats['categories']}")


if __name__ == "__main__":
    load_cases_to_rag()
