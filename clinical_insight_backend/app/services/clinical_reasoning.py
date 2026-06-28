import time
import json
import re
from typing import Optional
import httpx

from app.config import settings
from app.schemas.clinical import (
    ClinicalPresentation,
    ClinicalAnalysis,
    DecisionQuestion,
    GapItem,
    PatternBreak,
    ConfidenceLevel,
    TestCase,
    TestResult,
    WeightedFlag,
    WeightedQuestion,
    WeightedGap,
    CategoryScore,
)


# ============================================================================
# WEIGHTED SCORING CONFIGURATION
# ============================================================================

# Category weights for overall score calculation
CATEGORY_WEIGHTS = {
    "safety": 0.35,      # Drug allergies, contraindications, life-threatening
    "diagnostic": 0.20,  # Correct identification of condition
    "treatment": 0.25,   # Appropriate antibiotic selection, dosing
    "workup": 0.12,      # Labs, imaging, consultations needed
    "monitoring": 0.08,  # Follow-up, drug levels, adverse effects
}

# Severity multipliers for missed items
SEVERITY_MULTIPLIERS = {
    "critical": 3.0,    # Life-threatening if missed (e.g., anaphylaxis history)
    "high": 2.0,        # Serious harm if missed (e.g., renal dosing)
    "moderate": 1.0,    # Standard importance
    "low": 0.5,         # Nice to have
}

# Penalty definitions for dangerous omissions
PENALTY_DEFINITIONS = {
    "missed_allergy_contraindication": -0.25,  # Missed that drug is contraindicated
    "missed_cross_reactivity": -0.20,          # Missed β-lactam cross-reactivity
    "missed_renal_adjustment": -0.15,          # Missed need for renal dosing
    "missed_drug_interaction": -0.15,          # Missed QTc or other interaction
    "missed_life_threatening": -0.20,          # Missed DRESS, SJS, anaphylaxis
    "wrong_antibiotic_class": -0.20,           # Recommended contraindicated drug
    "missed_osteomyelitis_duration": -0.10,    # Didn't mention 6-week therapy
    "missed_source_control": -0.10,            # Didn't mention I&D for abscess
}

# Keywords for auto-categorization
SAFETY_KEYWORDS = [
    "anaphylaxis", "allergy", "contraindicated", "avoid", "dress", "sjs",
    "stevens-johnson", "cross-react", "β-lactam", "beta-lactam", "life-threatening",
    "severe", "hypotension", "bronchospasm", "laryngeal", "angioedema"
]

TREATMENT_KEYWORDS = [
    "antibiotic", "clindamycin", "vancomycin", "ciprofloxacin", "aztreonam",
    "doxycycline", "linezolid", "ceftazidime", "levofloxacin", "therapy",
    "coverage", "dose", "dosing", "mg", "iv", "oral", "duration", "weeks"
]

DIAGNOSTIC_KEYWORDS = [
    "osteomyelitis", "abscess", "infection", "mssa", "mrsa", "pseudomonas",
    "enterococcus", "culture", "polymicrobial", "deep tissue", "soft tissue"
]

WORKUP_KEYWORDS = [
    "abi", "mri", "ct", "x-ray", "tcpo2", "perfusion", "vascular", "labs",
    "albumin", "prealbumin", "nutrition", "debridement", "consult", "ecg"
]

MONITORING_KEYWORDS = [
    "trough", "level", "monitor", "weekly", "follow-up", "qtc", "c. diff",
    "clostridium", "renal function", "creatinine", "bmp"
]
from app.prompts.clinical_insight import (
    CLINICAL_INSIGHT_SYSTEM_PROMPT,
    GAP_ANALYSIS_PROMPT,
    DECISION_QUESTIONS_PROMPT,
    PATTERN_CHECK_PROMPT,
)
from app.services.case_rag import get_case_rag


class ClinicalReasoningEngine:
    """Core engine for clinical reasoning and gap analysis"""

    def __init__(self):
        self.case_rag = None

        # Initialize RAG store (lazy loading)
        try:
            self.case_rag = get_case_rag()
        except Exception:
            self.case_rag = None

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Call the configured LLM - defaults to local Ollama"""
        if settings.llm_provider == "ollama":
            # Use local Ollama
            url = f"{settings.ollama_base_url}/api/generate"
            payload = {
                "model": settings.ollama_model,
                "prompt": f"{system_prompt}\n\n{user_prompt}",
                "stream": False,
            }
            with httpx.Client(timeout=120.0) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
                return response.json().get("response", "")

        elif settings.llm_provider == "anthropic" and settings.anthropic_api_key:
            import anthropic
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            response = client.messages.create(
                model=settings.model_name,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return response.content[0].text

        elif settings.llm_provider == "openai" and settings.openai_api_key:
            import openai
            client = openai.OpenAI(api_key=settings.openai_api_key)
            response = client.chat.completions.create(
                model=settings.model_name,
                max_tokens=4096,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return response.choices[0].message.content

        else:
            raise ValueError(f"No valid LLM configured. Provider: {settings.llm_provider}")

    def analyze_presentation(
        self, presentation: ClinicalPresentation | str, proposed_plan: str = None
    ) -> ClinicalAnalysis:
        """
        Main entry point: Analyze a clinical presentation against a proposed plan.

        The engine will:
        1. Read all available data
        2. Answer its own questions using that data
        3. Only surface gaps that are genuinely unanswered AND dangerous/management-changing
        4. Show reasoning chain for each flag
        5. Look for pattern breaks where data tells a different story
        """
        start_time = time.time()

        # Convert to narrative if structured input
        if isinstance(presentation, ClinicalPresentation):
            narrative = presentation.to_narrative()
        else:
            narrative = presentation

        # Get RAG context from similar past cases
        rag_context = ""
        if self.case_rag:
            try:
                rag_context = self.case_rag.get_context_for_analysis(narrative)
            except Exception:
                rag_context = ""

        # Build the user prompt based on whether we have a proposed plan
        if proposed_plan:
            user_prompt = f"""Review this clinical case and the proposed treatment plan.

## CLINICAL DATA
{narrative}

## PROPOSED PLAN
{proposed_plan}

## YOUR TASK

1. First, read ALL the data above. Answer your own questions:
   - Does the treatment match the culture/susceptibilities?
   - Does it respect documented allergies?
   - Is dosing appropriate for organ function (check GFR/Cr)?
   - Is duration appropriate for the diagnosis?
   - If abscess/collection present, is source control addressed?

2. For each question above: if the data provides a clear answer, note it and move on.

3. Only flag items where:
   - The data does NOT answer the question, AND
   - Missing this could cause harm OR would change management

4. Look for PATTERN BREAKS - where the data tells a different story than the plan assumes:
   - Expected findings that are absent
   - Unexpected findings that are present
   - Data that could be masked (Tylenol → fever, beta-blockers → tachycardia)
   - Connections that suggest a different diagnosis

5. For each flag, show your reasoning chain:
   - What data points you noticed
   - How they connect
   - Why it matters

If everything checks out - say so briefly and stop. Do not manufacture concerns."""
        else:
            user_prompt = f"""Review this clinical presentation.

## CLINICAL DATA
{narrative}

## YOUR TASK

1. Read ALL the data. Look for:
   - Findings that don't fit the stated diagnosis
   - Data that might be masked (recent Tylenol, beta-blockers, steroids)
   - Connections between findings that tell a different story
   - Expected findings that are absent

2. Only flag items that are:
   - Dangerous if missed, OR
   - Would change management

3. For each flag, show your reasoning:
   - What you noticed
   - How the pieces connect
   - Why it matters

If the presentation is straightforward with no significant pattern breaks - say so and stop."""

        # Add RAG context if available
        if rag_context:
            user_prompt += f"""

---
## CONTEXT FROM SIMILAR PAST CASES
{rag_context}

Use the above context to inform your analysis. If similar cases had important flags or teaching points, consider whether they apply here.
---"""

        raw_response = self._call_llm(CLINICAL_INSIGHT_SYSTEM_PROMPT, user_prompt)

        # Parse the response into structured format
        analysis = self._parse_analysis(raw_response)
        analysis.raw_llm_response = raw_response
        analysis.processing_time_ms = int((time.time() - start_time) * 1000)

        # Store the case in RAG for future learning
        if self.case_rag:
            try:
                self.case_rag.store_from_analysis(
                    presentation=narrative,
                    analysis={
                        "critical_flags": analysis.critical_flags,
                        "recommended_next_steps": analysis.recommended_next_steps,
                        "pattern_breaks": [
                            {"observation": pb.observation} if hasattr(pb, 'observation') else str(pb)
                            for pb in analysis.pattern_breaks
                        ],
                    }
                )
            except Exception:
                pass  # Don't fail the analysis if storage fails

        return analysis

    def _parse_analysis(self, raw_response: str) -> ClinicalAnalysis:
        """Parse LLM response into structured ClinicalAnalysis

        Handles both old format (### sections) and new format (What I noticed / How these connect)
        """
        analysis = ClinicalAnalysis(
            critical_flags=[],
            clinical_summary="",
            reasoning_process="",
            pattern_breaks=[],
            missing_information=[],
            decision_questions=[],
            confidence_level=ConfidenceLevel.MODERATE,
            working_assessment="",
            key_assumptions=[],
            recommended_next_steps=[],
        )

        # Check for new reasoning chain format
        if "**What I noticed:**" in raw_response or "**How these connect:**" in raw_response:
            # New format - extract reasoning chains as flags with context
            analysis.reasoning_process = raw_response

            # Extract individual insight blocks
            insight_pattern = r"\*\*What I noticed:\*\*\s*(.*?)\*\*How these connect:\*\*\s*(.*?)\*\*Why this matters:\*\*\s*(.*?)(?=\*\*What I noticed:\*\*|\*\*What the data doesn't answer:\*\*|\Z)"
            insights = re.findall(insight_pattern, raw_response, re.DOTALL | re.IGNORECASE)

            for noticed, connects, matters in insights:
                # Create a comprehensive flag from the insight
                flag_text = f"{matters.strip()}"
                if flag_text:
                    analysis.critical_flags.append(flag_text)
                    # Also add as pattern break with full context
                    analysis.pattern_breaks.append(
                        PatternBreak(
                            observation=noticed.strip(),
                            expected_pattern=connects.strip(),
                            possible_explanations=[matters.strip()],
                            concern_level="High" if any(kw in matters.lower() for kw in ["harm", "dangerous", "critical", "miss"]) else "Medium",
                        )
                    )

            # Extract gaps (what data doesn't answer)
            gaps_pattern = r"\*\*What the data doesn't answer:\*\*\s*(.*?)(?=\*\*|\Z)"
            gaps_match = re.search(gaps_pattern, raw_response, re.DOTALL | re.IGNORECASE)
            if gaps_match:
                gap_text = gaps_match.group(1).strip()
                gaps = [line.strip().lstrip("-•*").strip() for line in gap_text.split("\n") if line.strip()]
                for gap in gaps:
                    if gap:
                        analysis.missing_information.append(
                            GapItem(category="Unanswered", item=gap, clinical_significance="", urgency="Important")
                        )

            # Set summary from first few sentences if available
            first_para = raw_response.split("\n\n")[0] if "\n\n" in raw_response else raw_response[:200]
            if not first_para.startswith("**"):
                analysis.clinical_summary = first_para.strip()

            return analysis

        # Fall back to old format parsing
        sections = {
            "critical_flags": r"###?\s*⚠️?\s*CRITICAL FLAGS.*?\n(.*?)(?=###|\Z)",
            "clinical_summary": r"###?\s*Clinical Summary\n(.*?)(?=###|\Z)",
            "reasoning": r"###?\s*Visible Reasoning Process\n(.*?)(?=###|\Z)",
            "pattern_breaks": r"###?\s*Key Pattern Breaks\n(.*?)(?=###|\Z)",
            "missing_info": r"###?\s*Critical Missing Information\n(.*?)(?=###|\Z)",
            "decision_questions": r"###?\s*Decision Questions\n(.*?)(?=###|\Z)",
            "assessment": r"###?\s*Provisional Assessment\n(.*?)(?=###|\Z)",
            "next_steps": r"###?\s*Recommended Next Steps\n(.*?)(?=###|\Z)",
        }

        for key, pattern in sections.items():
            match = re.search(pattern, raw_response, re.DOTALL | re.IGNORECASE)
            if match:
                content = match.group(1).strip()

                if key == "critical_flags":
                    # Parse as list
                    flags = [
                        line.strip().lstrip("-•*").strip()
                        for line in content.split("\n")
                        if line.strip() and not line.strip().startswith("#")
                    ]
                    analysis.critical_flags = [f for f in flags if f]

                elif key == "clinical_summary":
                    analysis.clinical_summary = content

                elif key == "reasoning":
                    analysis.reasoning_process = content

                elif key == "pattern_breaks":
                    # Simplified - just capture the text
                    breaks = [
                        line.strip().lstrip("-•*").strip()
                        for line in content.split("\n")
                        if line.strip() and not line.strip().startswith("#")
                    ]
                    for b in breaks:
                        if b:
                            analysis.pattern_breaks.append(
                                PatternBreak(
                                    observation=b,
                                    expected_pattern="",
                                    possible_explanations=[],
                                    concern_level="Medium",
                                )
                            )

                elif key == "missing_info":
                    items = [
                        line.strip().lstrip("-•*1234567890.").strip()
                        for line in content.split("\n")
                        if line.strip() and not line.strip().startswith("#")
                    ]
                    for item in items:
                        if item:
                            analysis.missing_information.append(
                                GapItem(
                                    category="Unknown",
                                    item=item,
                                    clinical_significance="",
                                    urgency="Important",
                                )
                            )

                elif key == "decision_questions":
                    questions = [
                        line.strip().lstrip("-•*1234567890.").strip()
                        for line in content.split("\n")
                        if line.strip()
                        and not line.strip().startswith("#")
                        and "?" in line
                    ]
                    for i, q in enumerate(questions[:5]):
                        if q:
                            analysis.decision_questions.append(
                                DecisionQuestion(
                                    question=q,
                                    why_it_matters="",
                                    concern_if_positive="",
                                    priority=i + 1,
                                )
                            )

                elif key == "assessment":
                    analysis.working_assessment = content
                    # Try to extract confidence level
                    if "high" in content.lower():
                        analysis.confidence_level = ConfidenceLevel.HIGH
                    elif "low" in content.lower():
                        analysis.confidence_level = ConfidenceLevel.LOW
                    else:
                        analysis.confidence_level = ConfidenceLevel.MODERATE

                elif key == "next_steps":
                    steps = [
                        line.strip().lstrip("-•*1234567890.").strip()
                        for line in content.split("\n")
                        if line.strip() and not line.strip().startswith("#")
                    ]
                    analysis.recommended_next_steps = [s for s in steps if s]

        return analysis

    def evaluate_test_case(self, test_case: TestCase) -> TestResult:
        """Run a test case and score the results with weighted metrics"""
        # Get the proposed plan if available (from recommended_plan field)
        proposed_plan = getattr(test_case, 'recommended_plan', None)

        # Get analysis - pass the proposed plan if available
        analysis = self.analyze_presentation(test_case.presentation, proposed_plan)

        # Build weighted flags from simple list if not provided
        weighted_flags = test_case.weighted_flags or self._auto_weight_flags(
            test_case.expected_critical_flags
        )
        weighted_questions = test_case.weighted_questions or self._auto_weight_questions(
            test_case.expected_decision_questions
        )
        weighted_gaps = test_case.weighted_gaps or self._auto_weight_gaps(
            test_case.expected_gaps
        )

        # Score critical flags with weights
        flags_found = []
        flags_missed = []
        flag_scores_by_category = {}

        for wf in weighted_flags:
            found = any(
                self._fuzzy_match(wf.text, identified)
                for identified in analysis.critical_flags
            )
            category = wf.category
            if category not in flag_scores_by_category:
                flag_scores_by_category[category] = {"found": 0, "total": 0, "weight": 0, "missed": []}

            flag_scores_by_category[category]["total"] += wf.weight
            if found:
                flags_found.append(wf.text)
                flag_scores_by_category[category]["found"] += wf.weight
            else:
                flags_missed.append(wf.text)
                flag_scores_by_category[category]["missed"].append(wf.text)

        # Score decision questions with weights
        asked_questions = [q.question for q in analysis.decision_questions]
        questions_found = []
        questions_missed = []
        question_scores_by_category = {}

        for wq in weighted_questions:
            found = any(
                self._fuzzy_match(wq.text, asked) for asked in asked_questions
            )
            category = wq.category
            if category not in question_scores_by_category:
                question_scores_by_category[category] = {"found": 0, "total": 0, "weight": 0, "missed": []}

            question_scores_by_category[category]["total"] += wq.weight
            if found:
                questions_found.append(wq.text)
                question_scores_by_category[category]["found"] += wq.weight
            else:
                questions_missed.append(wq.text)
                question_scores_by_category[category]["missed"].append(wq.text)

        # Score gaps with weights
        identified_gaps = [g.item for g in analysis.missing_information]
        gaps_found = []
        gaps_missed = []
        gap_scores_by_category = {}

        for wg in weighted_gaps:
            found = any(
                self._fuzzy_match(wg.text, identified)
                for identified in identified_gaps
            )
            category = wg.category
            if category not in gap_scores_by_category:
                gap_scores_by_category[category] = {"found": 0, "total": 0, "weight": 0, "missed": []}

            gap_scores_by_category[category]["total"] += wg.weight
            if found:
                gaps_found.append(wg.text)
                gap_scores_by_category[category]["found"] += wg.weight
            else:
                gaps_missed.append(wg.text)
                gap_scores_by_category[category]["missed"].append(wg.text)

        # Calculate category scores
        category_breakdown = []
        category_scores = {"safety": 0, "diagnostic": 0, "treatment": 0, "workup": 0, "monitoring": 0}

        # Combine all category data
        all_categories = set(
            list(flag_scores_by_category.keys()) +
            list(question_scores_by_category.keys()) +
            list(gap_scores_by_category.keys())
        )

        for cat in all_categories:
            total_found = 0
            total_expected = 0
            missed_items = []

            if cat in flag_scores_by_category:
                total_found += flag_scores_by_category[cat]["found"]
                total_expected += flag_scores_by_category[cat]["total"]
                missed_items.extend(flag_scores_by_category[cat]["missed"])
            if cat in question_scores_by_category:
                total_found += question_scores_by_category[cat]["found"]
                total_expected += question_scores_by_category[cat]["total"]
                missed_items.extend(question_scores_by_category[cat]["missed"])
            if cat in gap_scores_by_category:
                total_found += gap_scores_by_category[cat]["found"]
                total_expected += gap_scores_by_category[cat]["total"]
                missed_items.extend(gap_scores_by_category[cat]["missed"])

            cat_score = total_found / total_expected if total_expected > 0 else 1.0
            cat_weight = CATEGORY_WEIGHTS.get(cat, 0.1)

            category_breakdown.append(CategoryScore(
                category=cat,
                score=cat_score,
                weight=cat_weight,
                weighted_score=cat_score * cat_weight,
                items_found=int(total_found),
                items_expected=int(total_expected),
                items_missed=missed_items
            ))

            if cat in category_scores:
                category_scores[cat] = cat_score

        # Apply penalties for dangerous omissions
        penalties = []
        penalty_total = 0.0

        # Check for specific dangerous patterns in missed items
        all_missed = flags_missed + questions_missed + gaps_missed
        all_missed_lower = " ".join(all_missed).lower()
        response_lower = (analysis.raw_llm_response or "").lower()

        # Penalty: Missed allergy contraindication
        if any(kw in all_missed_lower for kw in ["contraindicated", "all β-lactam", "all beta-lactam"]):
            if "contraindicated" not in response_lower:
                penalties.append("Missed explicit contraindication statement")
                penalty_total += PENALTY_DEFINITIONS["missed_allergy_contraindication"]

        # Penalty: Missed cross-reactivity
        if "cross-react" in all_missed_lower or "cross react" in all_missed_lower:
            if "cross" not in response_lower:
                penalties.append("Missed β-lactam cross-reactivity")
                penalty_total += PENALTY_DEFINITIONS["missed_cross_reactivity"]

        # Penalty: Missed renal adjustment
        if any(kw in all_missed_lower for kw in ["renal", "gfr", "dose adjust", "ckd"]):
            if "renal" not in response_lower and "gfr" not in response_lower:
                penalties.append("Missed renal dose adjustment consideration")
                penalty_total += PENALTY_DEFINITIONS["missed_renal_adjustment"]

        # Penalty: Missed drug interaction (QTc)
        if "qtc" in all_missed_lower or "qt prolongation" in all_missed_lower:
            if "qtc" not in response_lower and "qt" not in response_lower:
                penalties.append("Missed QTc prolongation risk")
                penalty_total += PENALTY_DEFINITIONS["missed_drug_interaction"]

        # Penalty: Missed life-threatening reaction type
        if any(kw in all_missed_lower for kw in ["dress", "sjs", "stevens-johnson", "life-threatening"]):
            if not any(kw in response_lower for kw in ["dress", "sjs", "stevens", "life-threatening", "severe"]):
                penalties.append("Missed life-threatening reaction severity")
                penalty_total += PENALTY_DEFINITIONS["missed_life_threatening"]

        # Penalty: Missed 6-week duration for osteomyelitis
        if "osteomyelitis" in all_missed_lower and "6 week" in all_missed_lower:
            if "6 week" not in response_lower and "six week" not in response_lower:
                penalties.append("Missed 6-week osteomyelitis treatment duration")
                penalty_total += PENALTY_DEFINITIONS["missed_osteomyelitis_duration"]

        # Calculate basic scores (backward compatible)
        flag_score = len(flags_found) / len(weighted_flags) if weighted_flags else 1.0
        question_score = len(questions_found) / len(weighted_questions) if weighted_questions else 1.0
        gap_score = len(gaps_found) / len(weighted_gaps) if weighted_gaps else 1.0

        # Calculate weighted overall score
        weighted_category_score = sum(cs.weighted_score for cs in category_breakdown)
        total_weight = sum(cs.weight for cs in category_breakdown)
        normalized_weighted_score = weighted_category_score / total_weight if total_weight > 0 else 0

        # Apply penalties (can't go below 0)
        final_weighted_score = max(0, normalized_weighted_score + penalty_total)

        # Legacy overall score for backward compatibility
        overall_score = (flag_score * 0.4) + (question_score * 0.35) + (gap_score * 0.25)

        return TestResult(
            case_id=test_case.id,
            case_name=test_case.name,
            critical_flags_identified=flags_found,
            critical_flags_missed=flags_missed,
            decision_questions_asked=asked_questions,
            key_questions_missed=questions_missed,
            gaps_identified=identified_gaps,
            key_gaps_missed=gaps_missed,
            critical_flag_score=flag_score,
            question_score=question_score,
            gap_score=gap_score,
            overall_score=overall_score,
            # New weighted scoring
            weighted_scores={
                "safety": category_scores.get("safety", 0),
                "diagnostic": category_scores.get("diagnostic", 0),
                "treatment": category_scores.get("treatment", 0),
                "workup": category_scores.get("workup", 0),
                "monitoring": category_scores.get("monitoring", 0),
            },
            category_breakdown=category_breakdown,
            safety_score=category_scores.get("safety"),
            diagnostic_score=category_scores.get("diagnostic"),
            treatment_score=category_scores.get("treatment"),
            workup_score=category_scores.get("workup"),
            penalties=penalties,
            penalty_total=penalty_total,
            final_weighted_score=final_weighted_score,
            analysis=analysis,
        )

    def _auto_weight_flags(self, flags: list[str]) -> list[WeightedFlag]:
        """Auto-categorize and weight flags based on content"""
        weighted = []
        for flag in flags:
            flag_lower = flag.lower()

            # Determine category
            if any(kw in flag_lower for kw in SAFETY_KEYWORDS):
                category = "safety"
                # Higher weight for life-threatening
                if any(kw in flag_lower for kw in ["anaphylaxis", "dress", "sjs", "life-threatening", "contraindicated"]):
                    severity = "critical"
                    weight = SEVERITY_MULTIPLIERS["critical"]
                else:
                    severity = "high"
                    weight = SEVERITY_MULTIPLIERS["high"]
            elif any(kw in flag_lower for kw in TREATMENT_KEYWORDS):
                category = "treatment"
                severity = "high" if "dose" in flag_lower or "6 week" in flag_lower else "moderate"
                weight = SEVERITY_MULTIPLIERS[severity]
            elif any(kw in flag_lower for kw in DIAGNOSTIC_KEYWORDS):
                category = "diagnostic"
                severity = "moderate"
                weight = SEVERITY_MULTIPLIERS["moderate"]
            elif any(kw in flag_lower for kw in WORKUP_KEYWORDS):
                category = "workup"
                severity = "moderate"
                weight = SEVERITY_MULTIPLIERS["moderate"]
            elif any(kw in flag_lower for kw in MONITORING_KEYWORDS):
                category = "monitoring"
                severity = "low"
                weight = SEVERITY_MULTIPLIERS["low"]
            else:
                category = "diagnostic"
                severity = "moderate"
                weight = SEVERITY_MULTIPLIERS["moderate"]

            weighted.append(WeightedFlag(
                text=flag,
                category=category,
                severity=severity,
                weight=weight
            ))

        return weighted

    def _auto_weight_questions(self, questions: list[str]) -> list[WeightedQuestion]:
        """Auto-categorize and weight questions based on content"""
        weighted = []
        for q in questions:
            q_lower = q.lower()

            if any(kw in q_lower for kw in SAFETY_KEYWORDS):
                category = "safety"
                weight = 2.0
            elif any(kw in q_lower for kw in TREATMENT_KEYWORDS):
                category = "treatment"
                weight = 1.5
            elif any(kw in q_lower for kw in WORKUP_KEYWORDS):
                category = "workup"
                weight = 1.0
            else:
                category = "diagnostic"
                weight = 1.0

            weighted.append(WeightedQuestion(text=q, category=category, weight=weight))

        return weighted

    def _auto_weight_gaps(self, gaps: list[str]) -> list[WeightedGap]:
        """Auto-categorize and weight gaps based on content"""
        weighted = []
        for gap in gaps:
            gap_lower = gap.lower()

            if any(kw in gap_lower for kw in ["antibiotic", "therapy", "started", "initiated"]):
                category = "treatment"
                weight = 2.0
            elif any(kw in gap_lower for kw in WORKUP_KEYWORDS):
                category = "workup"
                weight = 1.0
            elif any(kw in gap_lower for kw in MONITORING_KEYWORDS):
                category = "monitoring"
                weight = 0.8
            else:
                category = "workup"
                weight = 1.0

            weighted.append(WeightedGap(text=gap, category=category, weight=weight))

        return weighted

    def _fuzzy_match(self, expected: str, actual: str) -> bool:
        """Check if actual contains key terms from expected - more lenient matching"""
        expected_lower = expected.lower()
        actual_lower = actual.lower()

        # Direct substring match
        if expected_lower in actual_lower or actual_lower in expected_lower:
            return True

        # Extract key clinical terms (more than just word length)
        clinical_terms = [
            "dress", "sjs", "anaphylaxis", "allergy", "contraindicated", "β-lactam",
            "beta-lactam", "osteomyelitis", "pseudomonas", "enterococcus", "mrsa", "mssa",
            "vancomycin", "clindamycin", "ciprofloxacin", "aztreonam", "dual", "coverage",
            "renal", "gfr", "ckd", "dose", "adjust", "6-week", "six week", "debridement",
            "abi", "perfusion", "culture", "bone", "qtc", "cross-react", "polymicrobial"
        ]

        # Check for key clinical term matches
        expected_clinical = [t for t in clinical_terms if t in expected_lower]
        if expected_clinical:
            matches = sum(1 for t in expected_clinical if t in actual_lower)
            if matches >= 1 and matches >= len(expected_clinical) * 0.3:
                return True

        # Key term matching - if >30% of significant words match (lowered from 50%)
        expected_words = set(
            w for w in expected_lower.split() if len(w) > 3
        )
        actual_words = set(w for w in actual_lower.split() if len(w) > 3)

        if not expected_words:
            return False

        overlap = len(expected_words & actual_words)
        # More lenient: 30% overlap OR at least 2 words matching
        return overlap / len(expected_words) > 0.3 or overlap >= 2


# Singleton instance
reasoning_engine = ClinicalReasoningEngine()
