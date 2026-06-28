"""Clinical analyzer - core reasoning engine."""

import re
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from enum import Enum

from .ollama_client import OllamaClient
from ..capture.screenpipe import ScreenContent
from ..config import settings


class AlertLevel(str, Enum):
    ALERT = "alert"      # Critical - immediate attention
    WARNING = "warning"  # Important - should review
    SUGGESTION = "suggestion"  # Helpful recommendation
    INFO = "info"        # Contextual information


class ClinicalAlert(BaseModel):
    """A clinical alert or finding."""
    level: AlertLevel
    message: str
    details: Optional[str] = None
    timestamp: datetime
    source_app: str
    confidence: float = 0.8
    category: Optional[str] = None  # labs, meds, vitals, etc.
    source_text: Optional[str] = None  # The text that triggered this alert
    patient_name: Optional[str] = None  # Patient name if detected
    patient_mrn: Optional[str] = None  # MRN if detected


class AnalysisResult(BaseModel):
    """Result of clinical analysis."""
    summary: str
    alerts: list[ClinicalAlert]
    raw_response: str
    model_used: str
    analysis_time_ms: int
    screen_context: str


class ClinicalAnalyzer:
    """Core clinical analysis engine."""

    # Patterns to detect in screen content
    LAB_PATTERNS = [
        r"(?i)(potassium|K\+?)\s*[:\s]*(\d+\.?\d*)\s*(mEq/L|mmol/L)?",
        r"(?i)(sodium|Na\+?)\s*[:\s]*(\d+\.?\d*)\s*(mEq/L|mmol/L)?",
        r"(?i)(creatinine|Cr)\s*[:\s]*(\d+\.?\d*)\s*(mg/dL)?",
        r"(?i)(glucose|Glu)\s*[:\s]*(\d+\.?\d*)\s*(mg/dL)?",
        r"(?i)(hemoglobin|Hgb|Hb)\s*[:\s]*(\d+\.?\d*)\s*(g/dL)?",
        r"(?i)(WBC|white blood)\s*[:\s]*(\d+\.?\d*)\s*(K/uL|x10\^9)?",
        r"(?i)(platelets?|PLT)\s*[:\s]*(\d+\.?\d*)\s*(K/uL)?",
        r"(?i)(INR)\s*[:\s]*(\d+\.?\d*)",
        r"(?i)(troponin|TnI|TnT)\s*[:\s]*(\d+\.?\d*)\s*(ng/mL)?",
        r"(?i)(BNP|NT-proBNP)\s*[:\s]*(\d+\.?\d*)\s*(pg/mL)?",
        r"(?i)(lactate)\s*[:\s]*(\d+\.?\d*)\s*(mmol/L)?",
        r"(?i)(A1c|HbA1c)\s*[:\s]*(\d+\.?\d*)\s*%?",
    ]

    # Vital sign patterns
    VITAL_PATTERNS = [
        r"(?i)(BP|blood pressure)\s*[:\s]*(\d+)\s*/\s*(\d+)",  # BP: 180/100
        r"(?i)(SBP|systolic)\s*[:\s]*(\d+)",  # SBP: 180
        r"(?i)(DBP|diastolic)\s*[:\s]*(\d+)",  # DBP: 100
        r"(?i)(HR|heart rate|pulse)\s*[:\s]*(\d+)",  # HR: 120
        r"(?i)(RR|resp rate|respiratory)\s*[:\s]*(\d+)",  # RR: 24
        r"(?i)(temp|temperature)\s*[:\s]*(\d+\.?\d*)\s*(F|C)?",  # Temp: 101.5
        r"(?i)(SpO2|O2 sat|oxygen sat)\s*[:\s]*(\d+)\s*%?",  # SpO2: 88%
        r"(\d{2,3})\s*/\s*(\d{2,3})\s*(mmHg)?",  # 180/100 (standalone BP)
    ]

    # Critical lab thresholds with clinical rationale and recommendations
    CRITICAL_LABS = {
        "potassium": {
            "low": 2.5, "high": 6.0, "unit": "mEq/L",
            "high_rationale": "Severe hyperkalemia risks fatal cardiac arrhythmias (peaked T waves, widened QRS, sine wave)",
            "high_recs": "Stat ECG, calcium gluconate 1g IV for cardiac protection, insulin 10U + D50 IV, consider kayexalate or dialysis",
            "low_rationale": "Severe hypokalemia causes muscle weakness, paralysis, and life-threatening arrhythmias (U waves, prolonged QT)",
            "low_recs": "Oral KCl 40-80 mEq if stable; IV KCl 10-20 mEq/hr via central line if severe. Check Mg (often concurrent)",
        },
        "sodium": {
            "low": 120, "high": 160, "unit": "mEq/L",
            "high_rationale": "Severe hypernatremia causes CNS dysfunction, seizures, and cerebral hemorrhage from brain shrinkage",
            "high_recs": "Calculate free water deficit, replace slowly (<10-12 mEq/L per 24h to avoid cerebral edema), identify cause",
            "low_rationale": "Severe hyponatremia causes cerebral edema, seizures, and herniation. Chronic vs acute matters for correction rate",
            "low_recs": "If symptomatic: hypertonic saline 100mL 3% NS bolus. Correct slowly (<8-10 mEq/L per 24h) to avoid osmotic demyelination",
        },
        "glucose": {
            "low": 50, "high": 400, "unit": "mg/dL",
            "high_rationale": "Severe hyperglycemia suggests DKA or HHS; check anion gap, ketones, and osmolality",
            "high_recs": "IV fluids (0.9% NS), insulin drip (0.1 U/kg/hr), monitor K+ closely (drops with insulin), check ABG for acidosis",
            "low_rationale": "Hypoglycemia causes neuroglycopenic symptoms, seizures, coma, and permanent brain injury if prolonged",
            "low_recs": "If alert: 15-20g oral glucose. If obtunded: D50 25-50mL IV push or glucagon 1mg IM. Find and treat cause",
        },
        "hemoglobin": {
            "low": 7.0, "high": 20, "unit": "g/dL",
            "high_rationale": "Polycythemia increases viscosity and thrombosis risk (stroke, MI, DVT/PE)",
            "high_recs": "Therapeutic phlebotomy if symptomatic. Rule out primary (PV) vs secondary causes. Hydration to reduce viscosity",
            "low_rationale": "Severe anemia causes tissue hypoxia, high-output heart failure, and may indicate active bleeding",
            "low_recs": "Transfuse if symptomatic or Hgb <7g/dL (higher threshold if CAD). Type & screen, find bleeding source",
        },
        "platelets": {
            "low": 50, "high": 1000, "unit": "K/uL",
            "high_rationale": "Thrombocytosis increases clot risk; may indicate essential thrombocythemia, reactive cause, or iron deficiency",
            "high_recs": "Aspirin 81mg if >1000 K/uL without bleeding. Rule out myeloproliferative neoplasm (JAK2). Check iron studies",
            "low_rationale": "Severe thrombocytopenia risks spontaneous bleeding, especially CNS hemorrhage if <10-20 K/uL",
            "low_recs": "Hold anticoagulants/NSAIDs. Transfuse if <10 K/uL or <50 K/uL with bleeding/procedure. Rule out HIT, TTP, ITP",
        },
        "inr": {
            "low": 0, "high": 4.0, "unit": "",
            "high_rationale": "Supratherapeutic INR dramatically increases bleeding risk including intracranial hemorrhage",
            "high_recs": "Hold warfarin. If INR >10 or bleeding: Vitamin K 2.5-5mg PO/IV + consider 4-factor PCC or FFP. Reassess indication",
            "low_rationale": "Subtherapeutic INR may indicate non-compliance or interaction",
            "low_recs": "Check compliance, drug interactions, vitamin K intake. Consider bridging if high-risk indication (mechanical valve)",
        },
        "troponin": {
            "low": 0, "high": 0.04, "unit": "ng/mL",
            "high_rationale": "Elevated troponin indicates myocardial injury - acute MI until proven otherwise. Type 1 vs Type 2 MI matters",
            "high_recs": "Stat ECG, serial troponins q3-6h. If STEMI: activate cath lab. If NSTEMI: antiplatelet, anticoagulation, cardiology consult",
            "low_rationale": "",
            "low_recs": "",
        },
        "lactate": {
            "low": 0, "high": 4.0, "unit": "mmol/L",
            "high_rationale": "Elevated lactate indicates tissue hypoperfusion/hypoxia - may be sepsis, shock, or mesenteric ischemia",
            "high_recs": "Aggressive fluid resuscitation, identify/treat source (sepsis workup, check mesentery). Repeat lactate to trend clearance",
            "low_rationale": "",
            "low_recs": "",
        },
        "creatinine": {
            "low": 0, "high": 2.0, "unit": "mg/dL",
            "high_rationale": "Elevated creatinine indicates acute kidney injury or CKD progression - assess baseline and trend",
            "high_recs": "Check baseline Cr, review nephrotoxins (NSAIDs, contrast, aminoglycosides), ensure adequate hydration, consider renal consult",
            "low_rationale": "",
            "low_recs": "",
        },
        "wbc": {
            "low": 1.5, "high": 30, "unit": "K/uL",
            "high_rationale": "Marked leukocytosis suggests severe infection, leukemia, or leukemoid reaction. Check differential",
            "high_recs": "Infection workup (cultures, imaging). If blasts present: hematology STAT for possible leukemia",
            "low_rationale": "Severe neutropenia (<500 ANC) creates high infection risk with poor ability to mount inflammatory response",
            "low_recs": "Neutropenic precautions. If febrile: immediate broad-spectrum antibiotics (febrile neutropenia protocol). Consider G-CSF",
        },
    }

    # Critical vital thresholds with clinical rationale and recommendations
    CRITICAL_VITALS = {
        "sbp": {
            "low": 90, "high": 180, "unit": "mmHg",
            "high_rationale": "Hypertensive urgency/emergency risks stroke, MI, aortic dissection, pulmonary edema",
            "high_recs": "Assess for end-organ damage (neuro exam, chest pain, vision). If emergency: IV labetalol or nicardipine, target 25% reduction in 1hr",
            "low_rationale": "Hypotension indicates shock - distributive (sepsis), cardiogenic, hypovolemic, or obstructive",
            "low_recs": "IV fluids 30mL/kg if not cardiogenic. Identify cause. Vasopressors (norepinephrine) if fluid-refractory",
        },
        "dbp": {
            "low": 60, "high": 120, "unit": "mmHg",
            "high_rationale": "Elevated DBP increases coronary perfusion pressure but indicates severe hypertension",
            "high_recs": "Same as SBP management - assess for end-organ damage, gradual controlled reduction",
            "low_rationale": "Low DBP may compromise coronary perfusion especially in CAD patients",
            "low_recs": "Support with fluids/vasopressors, maintain MAP >65",
        },
        "hr": {
            "low": 50, "high": 120, "unit": "bpm",
            "high_rationale": "Tachycardia may indicate pain, anxiety, fever, hypovolemia, sepsis, PE, or primary arrhythmia",
            "high_recs": "12-lead ECG to characterize rhythm. Treat underlying cause. If unstable SVT: vagal maneuvers, adenosine, cardioversion",
            "low_rationale": "Symptomatic bradycardia causes hypotension, syncope, altered mental status",
            "low_recs": "Check ECG for block/escape rhythm. Atropine 0.5-1mg IV. Transcutaneous pacing if unstable. Review bradycardic meds",
        },
        "rr": {
            "low": 10, "high": 24, "unit": "/min",
            "high_rationale": "Tachypnea signals respiratory distress, metabolic acidosis (Kussmaul), PE, sepsis, or anxiety",
            "high_recs": "ABG/VBG, chest imaging. Support oxygenation. Treat underlying cause (bronchodilators, diuretics, antibiotics)",
            "low_rationale": "Bradypnea suggests CNS depression, opioid toxicity, or impending respiratory failure",
            "low_recs": "If opioid-related: naloxone 0.4-2mg IV. Prepare for intubation if declining. Check pupils, LOC",
        },
        "temp": {
            "low": 95, "high": 101.5, "unit": "°F",
            "high_rationale": "Fever indicates infection, inflammation, malignancy, or drug reaction. High fever (>104°F) risks seizures",
            "high_recs": "Infection workup: blood/urine cultures, CXR, procalcitonin. Antipyretics. Start empiric antibiotics if sepsis suspected",
            "low_rationale": "Hypothermia causes coagulopathy, arrhythmias, and altered mentation. May mask infection in elderly/immunocompromised",
            "low_recs": "Active rewarming. Rule out sepsis (elderly may be hypothermic with infection). Check glucose, thyroid",
        },
        "spo2": {
            "low": 92, "high": 100, "unit": "%",
            "high_rationale": "",
            "high_recs": "",
            "low_rationale": "Hypoxemia indicates respiratory failure, PE, pneumonia, COPD exacerbation, or pulmonary edema",
            "low_recs": "Supplemental O2 to target SpO2 >92% (88-92% if COPD). ABG, CXR. Consider BiPAP, HFNC, or intubation if worsening",
        },
    }

    # Patient identification patterns
    PATIENT_PATTERNS = [
        r"(?i)(?:patient|pt|name)[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)",  # Patient: John Smith
        r"(?i)([A-Z][a-z]+,\s*[A-Z][a-z]+)",  # Smith, John
        r"(?i)(?:MRN|MR#|Medical Record)[:\s#]*(\d{6,10})",  # MRN: 12345678
        r"(?i)(?:DOB|Date of Birth)[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",  # DOB
    ]

    def __init__(self):
        self.llm = OllamaClient()
        self.specialty_mode = settings.specialty_mode
        self._recent_alerts: list[ClinicalAlert] = []
        self._current_patient: Optional[dict] = None

    # Common clinical words that look like names but aren't
    NON_NAME_WORDS = {
        "syncope", "shortness", "already", "anticoagulated", "history", "present",
        "illness", "chief", "complaint", "assessment", "plan", "diagnosis",
        "treatment", "medication", "allergies", "vitals", "labs", "imaging",
        "admission", "discharge", "transfer", "consult", "follow", "acute",
        "chronic", "stable", "unstable", "improved", "worsening", "resolved"
    }

    def extract_patient_info(self, text: str) -> Optional[dict]:
        """Extract patient name, MRN, DOB from text."""
        info = {}

        # Try to find MRN first (most reliable identifier)
        mrn_match = re.search(r"(?i)(?:MRN|MR#|Medical Record|Acct)[:\s#]*(\d{6,10})", text)
        if mrn_match:
            info["mrn"] = mrn_match.group(1)

        # Try to find patient name with context (Name:, Patient:, etc.)
        # Pattern 1: Explicit label like "Name: Smith, John" or "Patient: Smith, John"
        name_match = re.search(r"(?i)(?:patient|pt|name)[:\s]+([A-Z][a-z]+,\s*[A-Z][a-z]+)", text)
        if name_match:
            candidate = name_match.group(1)
            # Verify it's not a clinical phrase
            words = [w.lower().strip(",") for w in candidate.split()]
            if not any(w in self.NON_NAME_WORDS for w in words):
                info["name"] = candidate

        # Pattern 2: "Last, First" at start of line or after newline (common in headers)
        if "name" not in info:
            name_match2 = re.search(r"(?:^|\n)\s*([A-Z][a-z]+,\s*[A-Z][a-z]+)(?:\s+MRN|\s+DOB|\s+\d)", text)
            if name_match2:
                candidate = name_match2.group(1)
                words = [w.lower().strip(",") for w in candidate.split()]
                if not any(w in self.NON_NAME_WORDS for w in words):
                    info["name"] = candidate

        # Try to find DOB
        dob_match = re.search(r"(?i)(?:DOB|Date of Birth|Birth)[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", text)
        if dob_match:
            info["dob"] = dob_match.group(1)

        if info:
            self._current_patient = info
            return info
        return self._current_patient  # Return last known if nothing new found

    def get_patient_context(self) -> str:
        """Get current patient as string for display."""
        if not self._current_patient:
            return "Unknown patient"
        parts = []
        if "name" in self._current_patient:
            parts.append(self._current_patient["name"])
        if "mrn" in self._current_patient:
            parts.append(f"MRN: {self._current_patient['mrn']}")
        return " | ".join(parts) if parts else "Unknown patient"

    def _extract_labs(self, text: str) -> dict[str, float]:
        """Extract lab values from text."""
        labs = {}
        for pattern in self.LAB_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                if len(match) >= 2:
                    lab_name = match[0].lower()
                    try:
                        value = float(match[1])
                        labs[lab_name] = value
                    except ValueError:
                        continue
        return labs

    def _check_critical_labs(
        self,
        labs: dict[str, float],
        source_app: str
    ) -> list[ClinicalAlert]:
        """Check for critical lab values with clinical rationale and recommendations."""
        alerts = []
        now = datetime.now()

        for lab_name, value in labs.items():
            # Normalize lab name
            normalized = lab_name.lower().replace("+", "").replace(" ", "")

            for critical_name, thresholds in self.CRITICAL_LABS.items():
                if critical_name in normalized or normalized in critical_name:
                    unit = thresholds["unit"]

                    if value < thresholds["low"] and thresholds.get("low_rationale"):
                        rationale = thresholds.get("low_rationale", "")
                        recs = thresholds.get("low_recs", "")
                        details = f"⚠️ {rationale}\n\n💊 RECOMMENDED: {recs}"
                        alerts.append(ClinicalAlert(
                            level=AlertLevel.ALERT,
                            message=f"CRITICAL LOW: {lab_name} = {value} {unit}",
                            details=details,
                            timestamp=now,
                            source_app=source_app,
                            confidence=0.95,
                            category="labs",
                            source_text=f"{lab_name}: {value}",
                        ))
                    elif value > thresholds["high"] and thresholds.get("high_rationale"):
                        rationale = thresholds.get("high_rationale", "")
                        recs = thresholds.get("high_recs", "")
                        details = f"⚠️ {rationale}\n\n💊 RECOMMENDED: {recs}"
                        alerts.append(ClinicalAlert(
                            level=AlertLevel.ALERT,
                            message=f"CRITICAL HIGH: {lab_name} = {value} {unit}",
                            details=details,
                            timestamp=now,
                            source_app=source_app,
                            confidence=0.95,
                            category="labs",
                            source_text=f"{lab_name}: {value}",
                        ))
                    break

        return alerts

    def _extract_vitals(self, text: str) -> dict[str, float]:
        """Extract vital signs from text."""
        vitals = {}

        # Blood pressure patterns
        bp_match = re.search(r"(?i)(?:BP|blood pressure)\s*[:\s]*(\d+)\s*/\s*(\d+)", text)
        if bp_match:
            vitals["sbp"] = float(bp_match.group(1))
            vitals["dbp"] = float(bp_match.group(2))
        else:
            # Standalone BP format like "180/100"
            standalone_bp = re.search(r"(\d{2,3})\s*/\s*(\d{2,3})", text)
            if standalone_bp:
                sbp, dbp = float(standalone_bp.group(1)), float(standalone_bp.group(2))
                # Validate it looks like a BP (SBP > DBP, reasonable range)
                if 70 < sbp < 250 and 40 < dbp < 150 and sbp > dbp:
                    vitals["sbp"] = sbp
                    vitals["dbp"] = dbp

        # Heart rate
        hr_match = re.search(r"(?i)(?:HR|heart rate|pulse)\s*[:\s]*(\d+)", text)
        if hr_match:
            vitals["hr"] = float(hr_match.group(1))

        # Respiratory rate
        rr_match = re.search(r"(?i)(?:RR|resp|respiratory)\s*[:\s]*(\d+)", text)
        if rr_match:
            vitals["rr"] = float(rr_match.group(1))

        # Temperature
        temp_match = re.search(r"(?i)(?:temp|temperature)\s*[:\s]*(\d+\.?\d*)", text)
        if temp_match:
            vitals["temp"] = float(temp_match.group(1))

        # SpO2
        spo2_match = re.search(r"(?i)(?:SpO2|O2 sat|oxygen)\s*[:\s]*(\d+)", text)
        if spo2_match:
            vitals["spo2"] = float(spo2_match.group(1))

        return vitals

    def _check_critical_vitals(
        self,
        vitals: dict[str, float],
        source_app: str
    ) -> list[ClinicalAlert]:
        """Check for critical vital signs with clinical rationale and recommendations."""
        alerts = []
        now = datetime.now()

        for vital_name, value in vitals.items():
            if vital_name in self.CRITICAL_VITALS:
                thresholds = self.CRITICAL_VITALS[vital_name]
                unit = thresholds["unit"]

                if value < thresholds["low"] and thresholds.get("low_rationale"):
                    rationale = thresholds.get("low_rationale", "")
                    recs = thresholds.get("low_recs", "")
                    details = f"⚠️ {rationale}\n\n💊 RECOMMENDED: {recs}"
                    alerts.append(ClinicalAlert(
                        level=AlertLevel.ALERT,
                        message=f"CRITICAL LOW {vital_name.upper()}: {value} {unit}",
                        details=details,
                        timestamp=now,
                        source_app=source_app,
                        confidence=0.95,
                        category="vitals",
                        source_text=f"{vital_name.upper()}: {value}",
                    ))
                elif value > thresholds["high"] and thresholds.get("high_rationale"):
                    rationale = thresholds.get("high_rationale", "")
                    recs = thresholds.get("high_recs", "")
                    details = f"⚠️ {rationale}\n\n💊 RECOMMENDED: {recs}"
                    alerts.append(ClinicalAlert(
                        level=AlertLevel.ALERT,
                        message=f"CRITICAL HIGH {vital_name.upper()}: {value} {unit}",
                        details=details,
                        timestamp=now,
                        source_app=source_app,
                        confidence=0.95,
                        category="vitals",
                        source_text=f"{vital_name.upper()}: {value}",
                    ))

        return alerts

    # Phrases indicating low-value/obvious alerts to filter out
    OBVIOUS_PATTERNS = [
        r"(?i)patient (has|is on|is being treated)",
        r"(?i)I see (the|that|a)",
        r"(?i)the patient('s)? (chart|record|note)",
        r"(?i)^(noted|observed|documented)",
        r"(?i)monitor (closely|carefully)",
        r"(?i)consider (referral|consultation)$",
        r"(?i)continue current (management|treatment|therapy)",
    ]

    def _is_obvious_alert(self, message: str) -> bool:
        """Check if alert is obvious/low-value and should be filtered."""
        for pattern in self.OBVIOUS_PATTERNS:
            if re.search(pattern, message):
                return True
        return False

    def _parse_llm_response(
        self,
        response: str,
        source_app: str
    ) -> list[ClinicalAlert]:
        """Parse LLM response for alerts."""
        alerts = []
        now = datetime.now()

        # Check for "no insights" response
        if re.search(r"(?i)no actionable insights|nothing significant|no alerts", response):
            return []

        # Pattern to match alert tags
        alert_pattern = r"(?i)(ALERT|WARNING|SUGGESTION|INFO)[:\s]+(.+?)(?=(?:ALERT|WARNING|SUGGESTION|INFO|$))"

        matches = re.findall(alert_pattern, response, re.DOTALL)

        for level_str, message in matches:
            level_str = level_str.upper()
            message = message.strip()

            if not message:
                continue

            # Filter obvious/low-value alerts
            if self._is_obvious_alert(message):
                continue

            level = {
                "ALERT": AlertLevel.ALERT,
                "WARNING": AlertLevel.WARNING,
                "SUGGESTION": AlertLevel.SUGGESTION,
                "INFO": AlertLevel.INFO,
            }.get(level_str, AlertLevel.INFO)

            # Extract source text if present [Source: "..."]
            source_text = None
            source_match = re.search(r'\[Source:\s*["\']([^"\']+)["\']', message)
            if source_match:
                source_text = source_match.group(1)
                # Remove source from message
                message = re.sub(r'\s*\[Source:[^\]]+\]', '', message).strip()

            # Skip alerts without source (LLM hallucination)
            if not source_text:
                continue

            # Extract category if mentioned
            category = None
            if re.search(r"(?i)(drug|medication|med)", message):
                category = "medications"
            elif re.search(r"(?i)(lab|creatinine|potassium|sodium)", message):
                category = "labs"
            elif re.search(r"(?i)(vital|BP|heart rate|temp)", message):
                category = "vitals"

            alerts.append(ClinicalAlert(
                level=level,
                message=message[:200],
                timestamp=now,
                source_app=source_app,
                confidence=0.7,
                category=category,
                source_text=source_text,
            ))

        return alerts

    def quick_check(self, content: ScreenContent) -> list[ClinicalAlert]:
        """INSTANT: Pattern-based checks only (no LLM). Returns in <10ms."""
        text = content.text_content
        if content.ocr_text and content.ocr_text != content.text_content:
            text += "\n" + content.ocr_text

        # Extract and check labs
        labs = self._extract_labs(text)
        lab_alerts = self._check_critical_labs(labs, content.app_name)

        # Extract and check vitals
        vitals = self._extract_vitals(text)
        vital_alerts = self._check_critical_vitals(vitals, content.app_name)

        return lab_alerts + vital_alerts

    def analyze_with_llm(
        self,
        content: ScreenContent,
        additional_context: Optional[str] = None
    ) -> AnalysisResult:
        """LLM-only analysis for deeper insights. Takes 2-5 seconds."""
        start_time = datetime.now()

        text = content.text_content
        if content.ocr_text and content.ocr_text != content.text_content:
            text += "\n" + content.ocr_text

        try:
            llm_response = self.llm.analyze_clinical_content(
                screen_text=text,
                context=additional_context
            )
            llm_alerts = self._parse_llm_response(
                llm_response.content,
                content.app_name
            )
            summary = "LLM analysis complete"
        except Exception as e:
            llm_response = None
            llm_alerts = []
            summary = f"LLM error: {str(e)}"

        elapsed = datetime.now() - start_time
        analysis_time_ms = int(elapsed.total_seconds() * 1000)

        return AnalysisResult(
            summary=summary,
            alerts=llm_alerts,
            raw_response=llm_response.content if llm_response else "",
            model_used=llm_response.model if llm_response else "none",
            analysis_time_ms=analysis_time_ms,
            screen_context=text[:500],
        )

    def analyze(
        self,
        content: ScreenContent,
        additional_context: Optional[str] = None
    ) -> AnalysisResult:
        """Full analysis (pattern + LLM). Use quick_check + analyze_with_llm for async."""
        start_time = datetime.now()

        # Combine text content
        text = content.text_content
        if content.ocr_text and content.ocr_text != content.text_content:
            text += "\n" + content.ocr_text

        # Quick pattern-based checks first (instant feedback)
        labs = self._extract_labs(text)
        lab_alerts = self._check_critical_labs(labs, content.app_name)

        vitals = self._extract_vitals(text)
        vital_alerts = self._check_critical_vitals(vitals, content.app_name)

        pattern_alerts = lab_alerts + vital_alerts

        # LLM analysis for deeper insights
        try:
            llm_response = self.llm.analyze_clinical_content(
                screen_text=text,
                context=additional_context
            )
            llm_alerts = self._parse_llm_response(
                llm_response.content,
                content.app_name
            )

            # Extract summary from response
            summary_match = re.search(
                r"(?:Summary|1\.)[:\s]*(.+?)(?:\n|2\.|ALERT|WARNING)",
                llm_response.content,
                re.IGNORECASE | re.DOTALL
            )
            summary = summary_match.group(1).strip() if summary_match else "Clinical content analyzed"

        except Exception as e:
            llm_response = None
            llm_alerts = []
            summary = f"Analysis error: {str(e)}"

        # Combine alerts, prioritizing pattern-based (higher confidence)
        all_alerts = pattern_alerts + llm_alerts

        # Filter by confidence threshold
        filtered_alerts = [
            a for a in all_alerts
            if a.confidence >= settings.min_confidence
        ]

        # Calculate analysis time
        elapsed = datetime.now() - start_time
        analysis_time_ms = int(elapsed.total_seconds() * 1000)

        return AnalysisResult(
            summary=summary,
            alerts=filtered_alerts,
            raw_response=llm_response.content if llm_response else "",
            model_used=llm_response.model if llm_response else "pattern-only",
            analysis_time_ms=analysis_time_ms,
            screen_context=text[:500],  # Truncate for storage
        )

    def is_duplicate_alert(self, alert: ClinicalAlert) -> bool:
        """Check if this alert is a duplicate of a recent one."""
        cooldown = settings.alert_cooldown

        for recent in self._recent_alerts:
            # Same level and similar message within cooldown
            if (
                recent.level == alert.level
                and recent.message[:50] == alert.message[:50]
                and (alert.timestamp - recent.timestamp).total_seconds() < cooldown
            ):
                return True

        return False

    def record_alert(self, alert: ClinicalAlert):
        """Record an alert as shown."""
        self._recent_alerts.append(alert)
        # Keep only recent alerts (last 100)
        self._recent_alerts = self._recent_alerts[-100:]

    def close(self):
        """Clean up resources."""
        self.llm.close()
