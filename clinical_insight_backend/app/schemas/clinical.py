from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum
from datetime import datetime


class ConfidenceLevel(str, Enum):
    HIGH = "High"
    MODERATE = "Moderate"
    LOW = "Low"


class ClinicalPresentation(BaseModel):
    """Input: A clinical vignette or case presentation"""
    chief_complaint: str = Field(..., description="Primary reason for visit")
    history_of_present_illness: str = Field(..., description="HPI narrative")
    vital_signs: Optional[str] = Field(None, description="Vitals if available")
    physical_exam: Optional[str] = Field(None, description="PE findings if available")
    medications: Optional[str] = Field(None, description="Current medications, recent medications taken")
    past_medical_history: Optional[str] = Field(None, description="PMH")
    additional_context: Optional[str] = Field(None, description="Any other relevant information")

    def to_narrative(self) -> str:
        """Convert structured input to narrative for LLM"""
        parts = [
            f"**Chief Complaint:** {self.chief_complaint}",
            f"**History of Present Illness:** {self.history_of_present_illness}",
        ]
        if self.vital_signs:
            parts.append(f"**Vital Signs:** {self.vital_signs}")
        if self.physical_exam:
            parts.append(f"**Physical Exam:** {self.physical_exam}")
        if self.medications:
            parts.append(f"**Medications:** {self.medications}")
        if self.past_medical_history:
            parts.append(f"**Past Medical History:** {self.past_medical_history}")
        if self.additional_context:
            parts.append(f"**Additional Context:** {self.additional_context}")
        return "\n\n".join(parts)


class FreeformPresentation(BaseModel):
    """Alternative input: Just paste the clinical narrative"""
    narrative: str = Field(..., description="Free-form clinical presentation")


class DecisionQuestion(BaseModel):
    """A specific question that would change clinical reasoning"""
    question: str
    why_it_matters: str
    concern_if_positive: str
    concern_if_negative: Optional[str] = None
    priority: int = Field(..., ge=1, le=5)


class GapItem(BaseModel):
    """A piece of missing information"""
    category: str  # e.g., "History", "Physical Exam", "Labs", "Social"
    item: str  # The specific missing element
    clinical_significance: str  # Why it matters
    urgency: str  # "Critical", "Important", "Helpful"


class PatternBreak(BaseModel):
    """Something that doesn't fit the expected pattern"""
    observation: str
    expected_pattern: str
    possible_explanations: List[str]
    concern_level: str  # "High", "Medium", "Low"


class ClinicalAnalysis(BaseModel):
    """The full output of the clinical reasoning engine"""
    # Critical flags first
    critical_flags: List[str] = Field(default_factory=list)

    # Summary
    clinical_summary: str

    # Reasoning
    reasoning_process: str

    # Pattern analysis
    pattern_breaks: List[PatternBreak] = Field(default_factory=list)

    # Gaps
    missing_information: List[GapItem] = Field(default_factory=list)

    # Decision questions
    decision_questions: List[DecisionQuestion] = Field(default_factory=list)

    # Assessment
    confidence_level: ConfidenceLevel
    working_assessment: str
    key_assumptions: List[str] = Field(default_factory=list)

    # Next steps
    recommended_next_steps: List[str] = Field(default_factory=list)

    # Meta
    raw_llm_response: Optional[str] = None
    processing_time_ms: Optional[int] = None


class FollowUpInput(BaseModel):
    """User provides answers to decision questions"""
    original_case_id: str
    answers: dict[str, str]  # question -> answer mapping


class WeightedFlag(BaseModel):
    """A critical flag with severity weight"""
    text: str
    category: str = "general"  # safety, diagnostic, treatment, monitoring, workup
    severity: str = "moderate"  # critical, high, moderate, low
    weight: float = 1.0  # Multiplier for scoring


class WeightedQuestion(BaseModel):
    """A decision question with importance weight"""
    text: str
    category: str = "general"  # safety, diagnostic, treatment, workup
    weight: float = 1.0


class WeightedGap(BaseModel):
    """A gap with clinical importance weight"""
    text: str
    category: str = "general"  # labs, imaging, history, exam, consult
    weight: float = 1.0


class TestCase(BaseModel):
    """A test case for evaluating the system"""
    id: str
    name: str
    presentation: ClinicalPresentation

    # Expected outputs for scoring - simple list for backward compatibility
    expected_critical_flags: List[str] = Field(default_factory=list)
    expected_decision_questions: List[str] = Field(default_factory=list)
    expected_gaps: List[str] = Field(default_factory=list)

    # NEW: Weighted expectations for sophisticated scoring
    weighted_flags: List[WeightedFlag] = Field(default_factory=list)
    weighted_questions: List[WeightedQuestion] = Field(default_factory=list)
    weighted_gaps: List[WeightedGap] = Field(default_factory=list)

    # The proposed treatment plan to evaluate
    recommended_plan: Optional[str] = None

    # The "reveal" - additional information
    additional_info: Optional[str] = None

    # Gold standard
    actual_diagnosis: Optional[str] = None
    teaching_points: List[str] = Field(default_factory=list)


class CategoryScore(BaseModel):
    """Score breakdown for a category"""
    category: str
    score: float
    weight: float
    weighted_score: float
    items_found: int
    items_expected: int
    items_missed: List[str] = Field(default_factory=list)


class TestResult(BaseModel):
    """Result of running a test case"""
    case_id: str
    case_name: str

    # Did the system identify key elements?
    critical_flags_identified: List[str]
    critical_flags_missed: List[str]

    decision_questions_asked: List[str]
    key_questions_missed: List[str]

    gaps_identified: List[str]
    key_gaps_missed: List[str]

    # Basic scores (backward compatible)
    critical_flag_score: float  # 0-1
    question_score: float  # 0-1
    gap_score: float  # 0-1
    overall_score: float  # 0-1

    # NEW: Weighted scores breakdown
    weighted_scores: Optional[dict] = Field(default_factory=dict)
    category_breakdown: List[CategoryScore] = Field(default_factory=list)
    safety_score: Optional[float] = None  # Critical safety items only
    diagnostic_score: Optional[float] = None
    treatment_score: Optional[float] = None
    workup_score: Optional[float] = None

    # Penalties applied
    penalties: List[str] = Field(default_factory=list)
    penalty_total: float = 0.0

    # Final weighted score
    final_weighted_score: Optional[float] = None

    # Full analysis
    analysis: ClinicalAnalysis
