from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import json
from pathlib import Path

from app.api.reasoning import router as reasoning_router
from app.api.chat import router as chat_router
from app.api.rag import router as rag_router
from app.config import settings

app = FastAPI(
    title=settings.app_name,
    description="""
    Clinical Insight Engine - An intelligent clinical reasoning support system.

    This system analyzes clinical presentations to:
    - Identify critical gaps in available information
    - Surface pattern breaks and red flags
    - Generate decision questions that would change clinical reasoning
    - Provide transparent chain-of-thought reasoning

    Built to support, not replace, clinical judgment.
    """,
    version="0.1.0",
)

# CORS for frontend and local portals
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8080",
        "null",  # Allow file:// protocol for local HTML
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(reasoning_router)
app.include_router(chat_router)
app.include_router(rag_router)


@app.get("/")
async def root():
    return {
        "name": settings.app_name,
        "version": "0.1.0",
        "status": "running",
        "endpoints": {
            "analyze": "/api/reasoning/analyze",
            "analyze_freeform": "/api/reasoning/analyze-freeform",
            "test_case": "/api/reasoning/test-case",
            "rag_store": "/api/rag/store",
            "rag_search": "/api/rag/search/cases",
            "rag_stats": "/api/rag/stats",
            "docs": "/docs",
        },
    }


@app.get("/api/test-cases")
async def get_test_cases():
    """Return built-in test cases for evaluation"""
    test_cases_file = Path(__file__).parent.parent.parent / "test_cases" / "cases.json"
    if test_cases_file.exists():
        with open(test_cases_file) as f:
            return json.load(f)
    return {"cases": []}


@app.get("/health")
async def health_check():
    # Show model name for ollama
    if settings.llm_provider == "ollama":
        model = settings.ollama_model
    else:
        model = settings.llm_provider
    return {"status": "healthy", "llm_provider": model}
