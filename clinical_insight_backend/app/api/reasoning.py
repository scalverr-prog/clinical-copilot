from fastapi import APIRouter, HTTPException
from typing import List
from pydantic import BaseModel
import json
import os

from app.schemas.clinical import (
    ClinicalPresentation,
    FreeformPresentation,
    ClinicalAnalysis,
    TestCase,
    TestResult,
    FollowUpInput,
)
from app.services.clinical_reasoning import reasoning_engine

router = APIRouter(prefix="/api/reasoning", tags=["Clinical Reasoning"])


# Request model for running case by ID
class RunCaseByIdRequest(BaseModel):
    case_id: str


def load_test_case_by_id(case_id: str) -> TestCase:
    """Load a test case from cases.json by ID"""
    cases_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "test_cases", "cases.json")
    cases_path = os.path.normpath(cases_path)

    with open(cases_path) as f:
        data = json.load(f)

    for case_data in data.get("cases", []):
        if case_data.get("id") == case_id:
            # Build ClinicalPresentation from nested presentation data
            pres_data = case_data.get("presentation", {})
            presentation = ClinicalPresentation(
                chief_complaint=pres_data.get("chief_complaint", ""),
                history_of_present_illness=pres_data.get("history_of_present_illness", ""),
                vital_signs=pres_data.get("vital_signs"),
                physical_exam=pres_data.get("physical_exam"),
                medications=pres_data.get("medications"),
                past_medical_history=pres_data.get("past_medical_history"),
                additional_context=f"""
Allergy: {pres_data.get('allergy', 'None documented')}
Laboratory: {pres_data.get('laboratory', 'None')}
Imaging: {pres_data.get('imaging', 'None')}
Wound Culture: {pres_data.get('wound_culture', 'None')}
""" if pres_data.get('allergy') or pres_data.get('laboratory') else pres_data.get('additional_context')
            )

            return TestCase(
                id=case_data.get("id"),
                name=case_data.get("name"),
                presentation=presentation,
                expected_critical_flags=case_data.get("expected_critical_flags", []),
                expected_decision_questions=case_data.get("expected_decision_questions", []),
                expected_gaps=case_data.get("expected_gaps", []),
                recommended_plan=case_data.get("recommended_plan"),
                actual_diagnosis=case_data.get("actual_diagnosis"),
                teaching_points=case_data.get("teaching_points", []),
            )

    raise HTTPException(status_code=404, detail=f"Test case '{case_id}' not found")


@router.post("/analyze", response_model=ClinicalAnalysis)
async def analyze_presentation(presentation: ClinicalPresentation):
    """
    Analyze a structured clinical presentation.

    Runs the full clinical reasoning process:
    - Data integrity check
    - Frame check
    - Pattern break analysis
    - Gap identification
    - Decision question generation
    """
    try:
        analysis = reasoning_engine.analyze_presentation(presentation)
        return analysis
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-freeform", response_model=ClinicalAnalysis)
async def analyze_freeform(presentation: FreeformPresentation):
    """
    Analyze a free-form clinical narrative.

    Use this when you want to paste a case directly without structuring it.
    """
    try:
        analysis = reasoning_engine.analyze_presentation(presentation.narrative)
        return analysis
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-case", response_model=TestResult)
async def run_test_case(test_case: TestCase):
    """
    Run a test case and evaluate the system's performance.

    Compares the system's output against expected:
    - Critical flags
    - Decision questions
    - Gap identification

    Returns scores and detailed comparison.
    """
    try:
        result = reasoning_engine.evaluate_test_case(test_case)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/run-case", response_model=TestResult)
async def run_case_by_id(request: RunCaseByIdRequest):
    """
    Run a test case by ID from cases.json.

    Loads the case, runs analysis, and returns scored results.
    """
    try:
        test_case = load_test_case_by_id(request.case_id)
        result = reasoning_engine.evaluate_test_case(test_case)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cases")
async def list_available_cases():
    """List all available test case IDs"""
    cases_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "test_cases", "cases.json")
    cases_path = os.path.normpath(cases_path)

    with open(cases_path) as f:
        data = json.load(f)

    return [{"id": c.get("id"), "name": c.get("name")} for c in data.get("cases", [])]


@router.post("/follow-up", response_model=ClinicalAnalysis)
async def analyze_with_followup(followup: FollowUpInput):
    """
    Re-analyze with additional information provided.

    Use this to see how the analysis changes when questions are answered.
    """
    # This would need session management in production
    # For now, just return a placeholder
    raise HTTPException(
        status_code=501,
        detail="Follow-up analysis requires session management - coming soon"
    )
