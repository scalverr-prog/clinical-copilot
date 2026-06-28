"""RAG API endpoints for clinical case storage and retrieval."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from app.services.case_rag import get_case_rag, SimilarCase

router = APIRouter(prefix="/api/rag", tags=["RAG Store"])


class StoreCaseRequest(BaseModel):
    presentation: str
    diagnosis: Optional[str] = None
    critical_flags: Optional[List[str]] = None
    teaching_points: Optional[List[str]] = None
    outcome: Optional[str] = None
    category: Optional[str] = None


class SearchRequest(BaseModel):
    query: str
    n_results: int = 5
    category: Optional[str] = None


class SearchResponse(BaseModel):
    cases: List[SimilarCase]


class TeachingPointResponse(BaseModel):
    teaching_point: str
    diagnosis: str
    category: str
    relevance: float


class CriticalFlagResponse(BaseModel):
    flag: str
    from_diagnosis: str
    category: str
    relevance: float


@router.post("/store", response_model=dict)
async def store_case(request: StoreCaseRequest):
    """
    Store a clinical case in the RAG database.

    The case will be indexed for future semantic search and
    can provide context for similar cases.
    """
    try:
        case_rag = get_case_rag()
        case_id = case_rag.store_case(
            presentation=request.presentation,
            diagnosis=request.diagnosis,
            critical_flags=request.critical_flags or [],
            teaching_points=request.teaching_points or [],
            outcome=request.outcome,
            category=request.category
        )

        if case_id:
            return {"success": True, "case_id": case_id}
        else:
            return {"success": False, "error": "Case too short or duplicate"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search/cases", response_model=SearchResponse)
async def search_cases(request: SearchRequest):
    """
    Find similar clinical cases to the given presentation.

    Returns cases ranked by semantic similarity with their
    diagnoses, teaching points, and critical flags.
    """
    try:
        case_rag = get_case_rag()
        similar = case_rag.find_similar_cases(
            presentation=request.query,
            n_results=request.n_results,
            category=request.category
        )
        return SearchResponse(cases=similar)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search/teachings", response_model=List[TeachingPointResponse])
async def search_teaching_points(request: SearchRequest):
    """
    Search for relevant teaching points from past cases.
    """
    try:
        case_rag = get_case_rag()
        points = case_rag.search_teaching_points(
            query=request.query,
            n_results=request.n_results,
            category=request.category
        )
        return [TeachingPointResponse(**p) for p in points]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search/flags", response_model=List[CriticalFlagResponse])
async def search_critical_flags(request: SearchRequest):
    """
    Search for relevant critical flags from past cases.
    """
    try:
        case_rag = get_case_rag()
        flags = case_rag.search_critical_flags(
            query=request.query,
            n_results=request.n_results
        )
        return [CriticalFlagResponse(**f) for f in flags]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats", response_model=dict)
async def get_rag_stats():
    """
    Get statistics about the RAG database.

    Returns counts of cases, teaching points, and critical flags,
    as well as category distribution.
    """
    try:
        case_rag = get_case_rag()
        return case_rag.get_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/context", response_model=dict)
async def get_analysis_context(presentation: str):
    """
    Get RAG context that would be used for analyzing a presentation.

    Useful for debugging or previewing what context the system
    would use for a given case.
    """
    try:
        case_rag = get_case_rag()
        context = case_rag.get_context_for_analysis(presentation)
        return {
            "context": context,
            "has_context": bool(context)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
