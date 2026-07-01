"""Diagnostic Reasoning Engine - Systematic clinical thinking.

This engine reasons through clinical cases step-by-step rather than
pattern-matching to specific diagnoses. It works for ANY presentation.
"""

import re
import time
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum
import httpx

from app.config import settings
from app.prompts.clinical_reasoning_framework import (
    CLINICAL_REASONING_SYSTEM,
    CASE_ANALYSIS_PROMPT,
    QUICK_REASONING_PROMPT,
)


class Severity(str, Enum):
    CRITICAL = "critical"  # Immediate life threat
    HIGH = "high"          # Serious if missed
    MODERATE = "moderate"  # Important but not urgent
    LOW = "low"            # Minor concern


class FitScore(str, Enum):
    GOOD = "good"          # Diagnosis explains findings well
    PARTIAL = "partial"    # Some findings unexplained
    POOR = "poor"          # Major findings unexplained


@dataclass
class ClinicalFeature:
    """A single clinical finding with interpretation."""
    category: str  # symptom, vital, history, exam, lab
    finding: str
    value: Optional[str] = None
    interpretation: Optional[str] = None
    abnormal: bool = False


@dataclass
class DifferentialItem:
    """A diagnosis on the differential."""
    diagnosis: str
    category: str  # "common" or "dangerous"
    explains: list[str] = field(default_factory=list)
    does_not_explain: list[str] = field(default_factory=list)
    expected_but_absent: list[str] = field(default_factory=list)
    mortality_if_missed: Optional[str] = None
    time_critical: bool = False
    rule_out_with: Optional[str] = None


@dataclass
class FitAssessment:
    """How well a diagnosis fits the clinical picture."""
    diagnosis: str
    fit_score: FitScore
    explained_findings: list[str] = field(default_factory=list)
    unexplained_findings: list[str] = field(default_factory=list)
    expected_but_absent: list[str] = field(default_factory=list)
    contradicting_findings: list[str] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)


@dataclass
class CriticalGap:
    """Something that MUST be addressed before accepting a diagnosis."""
    description: str
    severity: Severity
    rationale: str
    recommended_action: str


@dataclass
class DiagnosticReasoning:
    """Complete diagnostic reasoning for a case."""
    # Extracted features
    features: list[ClinicalFeature] = field(default_factory=list)

    # Differential diagnosis
    differential_common: list[DifferentialItem] = field(default_factory=list)
    differential_dangerous: list[DifferentialItem] = field(default_factory=list)

    # Fit assessment
    working_diagnosis: Optional[str] = None
    fit_assessment: Optional[FitAssessment] = None

    # Critical findings
    unexplained_findings: list[str] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)
    cant_miss_diagnoses: list[DifferentialItem] = field(default_factory=list)

    # Gaps and next steps
    critical_gaps: list[CriticalGap] = field(default_factory=list)
    recommended_next_steps: list[str] = field(default_factory=list)

    # Metadata
    raw_response: str = ""
    processing_time_ms: int = 0

    @property
    def has_red_flags(self) -> bool:
        return len(self.red_flags) > 0 or len(self.unexplained_findings) > 0

    @property
    def highest_severity(self) -> Severity:
        if self.red_flags or any(d.mortality_if_missed for d in self.cant_miss_diagnoses):
            return Severity.CRITICAL
        if self.unexplained_findings:
            return Severity.HIGH
        if self.critical_gaps:
            return Severity.MODERATE
        return Severity.LOW


class DiagnosticReasoningEngine:
    """Engine for systematic diagnostic reasoning."""

    def __init__(self):
        pass

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Call the configured LLM."""
        if settings.llm_provider == "ollama":
            url = f"{settings.ollama_base_url}/api/generate"
            payload = {
                "model": settings.ollama_model,
                "prompt": f"{system_prompt}\n\n{user_prompt}",
                "stream": False,
            }
            with httpx.Client(timeout=300.0) as client:
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

        raise ValueError(f"No valid LLM configured: {settings.llm_provider}")

    def analyze(
        self,
        presentation: str,
        working_diagnosis: Optional[str] = None,
        proposed_plan: Optional[str] = None,
    ) -> DiagnosticReasoning:
        """
        Analyze a clinical presentation using systematic reasoning.

        This is the main entry point. It:
        1. Extracts all clinical features
        2. Generates a differential (common AND dangerous)
        3. Assesses fit of working diagnosis
        4. Identifies can't-miss diagnoses
        5. Determines critical next steps
        """
        start_time = time.time()

        # Build the analysis prompt
        user_prompt = CASE_ANALYSIS_PROMPT.format(
            presentation=presentation,
            diagnosis=working_diagnosis or "Not explicitly stated",
            plan=proposed_plan or "Not provided",
        )

        # Get LLM analysis
        raw_response = self._call_llm(CLINICAL_REASONING_SYSTEM, user_prompt)

        # Parse the response into structured format
        reasoning = self._parse_response(raw_response)
        reasoning.raw_response = raw_response
        reasoning.working_diagnosis = working_diagnosis
        reasoning.processing_time_ms = int((time.time() - start_time) * 1000)

        return reasoning

    def quick_check(
        self,
        presentation: str,
        working_diagnosis: str,
    ) -> DiagnosticReasoning:
        """
        Quick red flag check - faster than full analysis.

        Use this for real-time screening. Returns only:
        - Red flags (findings that don't fit)
        - Can't-miss diagnoses
        - One critical next step
        """
        start_time = time.time()

        user_prompt = QUICK_REASONING_PROMPT.format(
            presentation=presentation,
            diagnosis=working_diagnosis,
        )

        raw_response = self._call_llm(CLINICAL_REASONING_SYSTEM, user_prompt)

        reasoning = self._parse_quick_response(raw_response)
        reasoning.raw_response = raw_response
        reasoning.working_diagnosis = working_diagnosis
        reasoning.processing_time_ms = int((time.time() - start_time) * 1000)

        return reasoning

    def _parse_response(self, response: str) -> DiagnosticReasoning:
        """Parse full LLM response into structured DiagnosticReasoning."""
        reasoning = DiagnosticReasoning()

        # Extract clinical features section
        features_match = re.search(
            r"##\s*CLINICAL FEATURES\s*\n(.*?)(?=##|\Z)",
            response, re.DOTALL | re.IGNORECASE
        )
        if features_match:
            reasoning.features = self._parse_features(features_match.group(1))

        # Extract differential diagnosis
        diff_match = re.search(
            r"##\s*DIFFERENTIAL DIAGNOSIS\s*\n(.*?)(?=##|\Z)",
            response, re.DOTALL | re.IGNORECASE
        )
        if diff_match:
            common, dangerous = self._parse_differential(diff_match.group(1))
            reasoning.differential_common = common
            reasoning.differential_dangerous = dangerous
            reasoning.cant_miss_diagnoses = dangerous

        # Extract fit assessment
        fit_match = re.search(
            r"##\s*FIT ASSESSMENT\s*\n(.*?)(?=##|\Z)",
            response, re.DOTALL | re.IGNORECASE
        )
        if fit_match:
            reasoning.fit_assessment = self._parse_fit_assessment(fit_match.group(1))
            if reasoning.fit_assessment:
                reasoning.unexplained_findings = reasoning.fit_assessment.unexplained_findings
                reasoning.red_flags = reasoning.fit_assessment.red_flags

        # Extract can't miss diagnoses
        cantmiss_match = re.search(
            r"##\s*CAN'T MISS DIAGNOSES\s*\n(.*?)(?=##|\Z)",
            response, re.DOTALL | re.IGNORECASE
        )
        if cantmiss_match:
            # Parse into DifferentialItems with mortality info
            self._parse_cant_miss(cantmiss_match.group(1), reasoning)

        # Extract critical gaps
        gaps_match = re.search(
            r"##\s*CRITICAL GAPS\s*\n(.*?)(?=##|\Z)",
            response, re.DOTALL | re.IGNORECASE
        )
        if gaps_match:
            reasoning.critical_gaps = self._parse_gaps(gaps_match.group(1))

        # Extract recommended next steps
        steps_match = re.search(
            r"##\s*RECOMMENDED NEXT STEPS\s*\n(.*?)(?=##|\Z)",
            response, re.DOTALL | re.IGNORECASE
        )
        if steps_match:
            reasoning.recommended_next_steps = self._parse_steps(steps_match.group(1))

        # Also look for unexplained findings in "Does NOT explain" sections
        not_explain_matches = re.findall(
            r"(?:Does NOT explain|NOT EXPLAINED|Unexplained)[:\s]*(.*?)(?=\n\n|\n[A-Z]|\Z)",
            response, re.DOTALL | re.IGNORECASE
        )
        for match in not_explain_matches:
            items = [line.strip().lstrip("-*").strip() for line in match.split("\n") if line.strip()]
            for item in items:
                if item and item not in reasoning.unexplained_findings:
                    reasoning.unexplained_findings.append(item)

        # Look for explicit red flags
        redflag_matches = re.findall(
            r"(?:RED FLAG|CRITICAL|CONCERNING)[:\s]*(.*?)(?=\n\n|\n[A-Z]|\Z)",
            response, re.DOTALL | re.IGNORECASE
        )
        for match in redflag_matches:
            items = [line.strip().lstrip("-*").strip() for line in match.split("\n") if line.strip()]
            for item in items:
                if item and item not in reasoning.red_flags:
                    reasoning.red_flags.append(item)

        return reasoning

    def _parse_quick_response(self, response: str) -> DiagnosticReasoning:
        """Parse quick check response - simpler parsing."""
        reasoning = DiagnosticReasoning()

        response_lower = response.lower()

        # Check if no red flags
        if "no red flags" in response_lower or "no significant" in response_lower:
            return reasoning

        # Extract any mentioned concerns as red flags
        lines = response.split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Skip header-like lines
            if line.startswith("#") or line.startswith("THINK"):
                continue

            # Look for numbered items or bullet points with concerns
            if re.match(r"^[\d\-\*\•]", line):
                content = re.sub(r"^[\d\.\-\*\•\s]+", "", line).strip()
                if content and len(content) > 10:
                    # Classify as red flag or next step
                    if any(kw in content.lower() for kw in ["doesn't explain", "unexplained", "concerning", "doesn't fit", "rule out", "can't miss", "dangerous"]):
                        reasoning.red_flags.append(content)
                    elif any(kw in content.lower() for kw in ["order", "check", "get", "obtain", "imaging", "test", "x-ray", "ct", "ecg"]):
                        reasoning.recommended_next_steps.append(content)

        return reasoning

    def _parse_features(self, text: str) -> list[ClinicalFeature]:
        """Parse clinical features from text."""
        features = []
        lines = text.split("\n")
        current_category = "general"

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check for category headers
            if line.startswith("**") and line.endswith("**"):
                current_category = line.strip("*: ").lower()
                continue

            # Parse feature line
            if line.startswith("-") or line.startswith("*"):
                content = line.lstrip("-* ").strip()
                if content:
                    # Check if abnormal
                    abnormal = any(kw in content.lower() for kw in [
                        "elevated", "high", "low", "abnormal", "tachycard", "fever",
                        "hypox", "tachypne", "hypotens", "bradycard"
                    ])
                    features.append(ClinicalFeature(
                        category=current_category,
                        finding=content,
                        abnormal=abnormal,
                    ))

        return features

    def _parse_differential(self, text: str) -> tuple[list[DifferentialItem], list[DifferentialItem]]:
        """Parse differential diagnosis into common and dangerous lists."""
        common = []
        dangerous = []

        current_section = None

        lines = text.split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Detect section
            if "COMMON" in line.upper() or "LIKELY" in line.upper():
                current_section = "common"
                continue
            elif "DANGEROUS" in line.upper() or "CAN'T MISS" in line.upper():
                current_section = "dangerous"
                continue

            # Parse diagnosis line
            if (line.startswith("-") or line.startswith("*") or line.startswith("|")) and current_section:
                content = line.lstrip("-*| ").strip()
                if not content or content.startswith("---"):
                    continue

                # Extract diagnosis name and details
                parts = re.split(r"\s*[-–—]\s*", content, maxsplit=1)
                diagnosis_name = parts[0].strip()
                details = parts[1] if len(parts) > 1 else ""

                if not diagnosis_name:
                    continue

                item = DifferentialItem(
                    diagnosis=diagnosis_name,
                    category=current_section,
                )

                # Parse explains
                explains_match = re.search(r"explains?:\s*([^;|]+)", details, re.IGNORECASE)
                if explains_match:
                    item.explains = [e.strip() for e in explains_match.group(1).split(",")]

                # Parse mortality
                mortality_match = re.search(r"mortality:\s*([^;|,]+)", details, re.IGNORECASE)
                if mortality_match:
                    item.mortality_if_missed = mortality_match.group(1).strip()

                # Parse rule out
                rule_out_match = re.search(r"rule out (?:with|by):\s*([^;|]+)", details, re.IGNORECASE)
                if rule_out_match:
                    item.rule_out_with = rule_out_match.group(1).strip()

                # Check time-critical
                item.time_critical = "time-critical" in details.lower() or "urgent" in details.lower()

                if current_section == "common":
                    common.append(item)
                else:
                    dangerous.append(item)

        return common, dangerous

    def _parse_fit_assessment(self, text: str) -> Optional[FitAssessment]:
        """Parse fit assessment section."""
        assessment = FitAssessment(diagnosis="", fit_score=FitScore.PARTIAL)

        # Extract working diagnosis
        diag_match = re.search(r"Working diagnosis:\s*(.+?)(?:\n|$)", text, re.IGNORECASE)
        if diag_match:
            assessment.diagnosis = diag_match.group(1).strip()

        # Extract explained findings
        explains_match = re.search(r"Explains?:\s*(.+?)(?=\n[A-Z]|\nDoes|\nExpected|\Z)", text, re.DOTALL | re.IGNORECASE)
        if explains_match:
            items = [line.strip().lstrip("-*").strip() for line in explains_match.group(1).split("\n") if line.strip()]
            assessment.explained_findings = [i for i in items if i]

        # Extract unexplained findings
        unexplained_match = re.search(r"(?:Does NOT explain|NOT EXPLAINED|Unexplained)[:\s]*(.+?)(?=\n[A-Z]|\nExpected|\nContradicts|\Z)", text, re.DOTALL | re.IGNORECASE)
        if unexplained_match:
            items = [line.strip().lstrip("-*").strip() for line in unexplained_match.group(1).split("\n") if line.strip()]
            assessment.unexplained_findings = [i for i in items if i]

        # Extract expected but absent
        absent_match = re.search(r"Expected but absent:\s*(.+?)(?=\n[A-Z]|\nContradicts|\nOVERALL|\Z)", text, re.DOTALL | re.IGNORECASE)
        if absent_match:
            items = [line.strip().lstrip("-*").strip() for line in absent_match.group(1).split("\n") if line.strip()]
            assessment.expected_but_absent = [i for i in items if i]

        # Extract contradicting findings
        contradict_match = re.search(r"Contradicts?:\s*(.+?)(?=\n[A-Z]|\nOVERALL|\Z)", text, re.DOTALL | re.IGNORECASE)
        if contradict_match:
            items = [line.strip().lstrip("-*").strip() for line in contradict_match.group(1).split("\n") if line.strip()]
            assessment.contradicting_findings = [i for i in items if i]
            # Contradicting findings are red flags
            assessment.red_flags.extend(assessment.contradicting_findings)

        # Determine fit score
        overall_match = re.search(r"OVERALL FIT:\s*(\w+)", text, re.IGNORECASE)
        if overall_match:
            fit_text = overall_match.group(1).lower()
            if "good" in fit_text:
                assessment.fit_score = FitScore.GOOD
            elif "poor" in fit_text:
                assessment.fit_score = FitScore.POOR
            else:
                assessment.fit_score = FitScore.PARTIAL
        else:
            # Infer from findings
            if assessment.contradicting_findings:
                assessment.fit_score = FitScore.POOR
            elif assessment.unexplained_findings:
                assessment.fit_score = FitScore.PARTIAL
            else:
                assessment.fit_score = FitScore.GOOD

        return assessment

    def _parse_cant_miss(self, text: str, reasoning: DiagnosticReasoning):
        """Parse can't miss diagnoses and add to reasoning."""
        lines = text.split("\n")

        for line in lines:
            line = line.strip()
            if not line or line.startswith("|--") or line.startswith("---"):
                continue

            if line.startswith("-") or line.startswith("*") or line.startswith("|"):
                content = line.lstrip("-*| ").strip()
                if not content:
                    continue

                # Parse table format or bullet format
                parts = [p.strip() for p in re.split(r"\|", content) if p.strip()]
                if not parts:
                    continue

                diagnosis = parts[0]

                # Check if already in dangerous differential
                existing = [d for d in reasoning.cant_miss_diagnoses if d.diagnosis.lower() == diagnosis.lower()]

                if existing:
                    item = existing[0]
                else:
                    item = DifferentialItem(diagnosis=diagnosis, category="dangerous")
                    reasoning.cant_miss_diagnoses.append(item)

                # Extract additional info from remaining parts
                for part in parts[1:]:
                    if "%" in part or "mortality" in part.lower():
                        item.mortality_if_missed = part
                    elif any(kw in part.lower() for kw in ["hour", "minute", "time", "urgent", "immediate"]):
                        item.time_critical = True
                    elif any(kw in part.lower() for kw in ["x-ray", "ct", "ecg", "test", "check", "imaging"]):
                        item.rule_out_with = part

    def _parse_gaps(self, text: str) -> list[CriticalGap]:
        """Parse critical gaps section."""
        gaps = []
        lines = text.split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.startswith("-") or line.startswith("*") or re.match(r"^\d+\.", line):
                content = re.sub(r"^[\d\.\-\*\s]+", "", line).strip()
                if content:
                    # Determine severity from keywords
                    severity = Severity.MODERATE
                    content_lower = content.lower()
                    if any(kw in content_lower for kw in ["must", "critical", "immediate", "urgent", "cannot"]):
                        severity = Severity.CRITICAL
                    elif any(kw in content_lower for kw in ["should", "important", "recommended"]):
                        severity = Severity.HIGH

                    gaps.append(CriticalGap(
                        description=content,
                        severity=severity,
                        rationale="",
                        recommended_action="",
                    ))

        return gaps

    def _parse_steps(self, text: str) -> list[str]:
        """Parse recommended next steps."""
        steps = []
        lines = text.split("\n")

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.startswith("-") or line.startswith("*") or re.match(r"^\d+\.", line):
                content = re.sub(r"^[\d\.\-\*\s]+", "", line).strip()
                if content and len(content) > 5:
                    steps.append(content)

        return steps


# Singleton instance
diagnostic_engine = DiagnosticReasoningEngine()
