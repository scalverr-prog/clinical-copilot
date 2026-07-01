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

    # Wound care and DFU patterns for clinical alerts
    WOUND_CARE_PATTERNS = {
        "dfu_with_pain": {
            "pattern": r"(?i)(diabetic|DM|T1DM|T2DM|diabetes).{0,100}(ulcer|DFU|wound|foot).{0,100}(pain|ache|tender)",
            "level": "warning",
            "message": "DFU with pain - rule out infection/osteomyelitis",
            "details": "Nocturnal or rest pain in diabetic foot ulcer may indicate deep infection, osteomyelitis, or ischemia. Consider: probe-to-bone test, inflammatory markers (WBC, ESR, CRP), X-ray or MRI for osteomyelitis."
        },
        "chronic_wound": {
            "pattern": r"(?i)(chronic|non-?healing|present for \d+ (weeks|months)).{0,50}(ulcer|wound|DFU)",
            "level": "suggestion",
            "message": "Chronic wound - assess for healing barriers",
            "details": "Chronic wounds require assessment of: vascular status (ABI), glycemic control (HbA1c), nutrition, offloading compliance, biofilm, and underlying osteomyelitis."
        },
        "plantar_ulcer": {
            "pattern": r"(?i)plantar.{0,30}(ulcer|wound|DFU)",
            "level": "warning",
            "message": "Plantar ulcer - high osteomyelitis risk location",
            "details": "Plantar ulcers over bony prominences have increased risk of osteomyelitis. Consider probe-to-bone test (positive if bone felt). If present >2 weeks or >2cm, MRI recommended."
        },
        "vitals_not_documented": {
            "pattern": r"(?i)vitals.{0,20}(not documented|not (obtained|recorded|available))",
            "level": "warning",
            "message": "Vitals not documented - document or obtain",
            "details": "Vital signs are essential for clinical assessment. Ensure BP, HR, temp are recorded. In wound patients, assess for signs of systemic infection."
        },
        "diabetes_wound": {
            "pattern": r"(?i)(T1DM|T2DM|type [12] diabetes|diabetic|DM).{0,150}(ulcer|wound|foot)",
            "level": "suggestion",
            "message": "Diabetic wound - ensure HbA1c and vascular assessment",
            "details": "DFU care requires: recent HbA1c (<3 months), vascular assessment (ABI, pulses), neuropathy assessment, appropriate offloading, and infection monitoring."
        },
        "infection_signs": {
            # Must have POSITIVE infection signs, not "denies" or "no" before them
            "pattern": r"(?i)(wound|ulcer|DFU).{0,50}(?<!deni)(?<!no )(?<!without )(has|with|shows?|present|noted|observed).{0,30}(drainage|purulent|erythema|cellulitis|malodor|fever)",
            "level": "alert",
            "message": "Wound infection signs - assess and treat",
            "details": "Signs of wound infection require: wound culture (deep tissue preferred), inflammatory markers, imaging if osteomyelitis suspected, antibiotics based on severity."
        }
    }

    # Critical syndrome patterns - ALWAYS flag these regardless of LLM reasoning
    # These are "can't miss" patterns with high mortality if delayed
    # The LLM reasoning layer provides additional coverage for novel patterns
    CRITICAL_PATTERNS = {
        "boerhaave_basic": {
            "pattern": r"(?i)(chest pain|thoracic|substernal).{0,100}(vomit|retch|heav)",
            "level": "warning",
            "message": "Chest pain + vomiting - consider esophageal injury",
            "details": "Chest pain following vomiting raises concern for esophageal injury (Boerhaave syndrome). Consider chest X-ray to rule out pneumomediastinum before diagnosing as spasm.",
            "category": "cant_miss"
        },
        "boerhaave_high_risk": {
            # Match alcohol mention anywhere in text with chest pain + vomiting
            "pattern": r"(?i)(?=.*(alcohol|drinker|etoh|heavy drink))(?=.*(chest pain|thoracic|substernal))(?=.*(vomit|retch))",
            "level": "alert",
            "message": "HIGH RISK: Heavy drinker + chest pain + vomiting = Boerhaave until proven otherwise",
            "details": "Classic Boerhaave presentation. Mortality >80% if missed. STAT chest imaging required before discharge. Do NOT dismiss as esophageal spasm without imaging.",
            "category": "cant_miss"
        },
        "boerhaave_with_systemic": {
            # Match chest pain + vomiting + any systemic sign (order independent)
            "pattern": r"(?i)(?=.*(chest pain|thoracic|substernal))(?=.*(vomit|retch))(?=.*(HR.{0,5}1[0-2]\d|Temp.{0,5}(99|10)|RR.{0,5}2[4-9]|SpO2.{0,5}9[0-4]|tachycard|fever|tachypne))",
            "level": "alert",
            "message": "CRITICAL: Chest pain + vomiting + systemic signs = possible mediastinitis",
            "details": "Fever, tachycardia, tachypnea, or hypoxia after chest pain + vomiting suggests esophageal perforation with mediastinal contamination. SURGICAL EMERGENCY. CT chest and thoracic surgery consult STAT.",
            "category": "cant_miss"
        },
        "dissection": {
            "pattern": r"(?i)(tearing|ripping|worst.{0,15}life|sudden severe).{0,50}(chest|back).{0,30}pain",
            "level": "alert",
            "message": "Tearing/ripping chest or back pain - rule out aortic dissection",
            "details": "Tearing quality pain suggests aortic dissection. Check BP both arms, pulse deficits. CT angiography STAT. Do NOT give thrombolytics for suspected MI without ruling out dissection.",
            "category": "cant_miss"
        },
        "mesenteric": {
            "pattern": r"(?i)(abd|abdominal).{0,30}pain.{0,50}(out of proportion|severe|excruciating).{0,50}(exam|benign|soft|non.?tender)",
            "level": "alert",
            "message": "Severe abdominal pain with benign exam - consider mesenteric ischemia",
            "details": "Pain out of proportion to exam is classic for mesenteric ischemia. Risk factors: A-fib, vascular disease. Lactate and CT angiography. Mortality >70% if bowel necrosis occurs.",
            "category": "cant_miss"
        },
        "nec_fasc": {
            "pattern": r"(?i)(cellulitis|skin.{0,20}infection).{0,80}(pain out of proportion|crepitus|rapid.{0,20}spread|bullae|necrotic|gas)",
            "level": "alert",
            "message": "Skin infection with severe pain or rapid spread - consider necrotizing fasciitis",
            "details": "Pain out of proportion, crepitus, rapid spread, or bullae in soft tissue infection suggests necrotizing fasciitis. Surgical debridement is definitive treatment. Broad-spectrum antibiotics and surgery consult STAT.",
            "category": "cant_miss"
        },
        "pe_syncope": {
            "pattern": r"(?i)(syncope|collapse|passed out).{0,100}(dyspnea|SOB|shortness|tachycard|chest pain)",
            "level": "warning",
            "message": "Syncope with cardiopulmonary symptoms - consider PE",
            "details": "Syncope with dyspnea, chest pain, or tachycardia may indicate massive PE. Calculate Wells score. Consider CT-PA or empiric anticoagulation if high suspicion.",
            "category": "cant_miss"
        },
        "spasm_with_abnormal_vitals": {
            # Match spasm diagnosis with any abnormal vital (order independent)
            "pattern": r"(?i)(?=.*(esophageal spasm|Dx:.{0,20}spasm|spasm.{0,20}(relaxant|antispasmodic)))(?=.*(HR.{0,5}1[0-2]\d|Temp.{0,5}(99|10)|RR.{0,5}2[4-9]|SpO2.{0,5}9[0-4]))",
            "level": "alert",
            "message": "Esophageal spasm diagnosis with abnormal vitals - DIAGNOSIS DOES NOT FIT",
            "details": "Esophageal spasm should have NORMAL vital signs. Tachycardia, fever, tachypnea, or hypoxia indicate tissue injury or systemic process - NOT functional spasm. Reconsider diagnosis. Obtain chest imaging.",
            "category": "fit_check"
        },
    }

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

        # Heart rate - must have label with colon/space, avoid matching ages like "45-yo"
        hr_match = re.search(r"(?i)(?:HR|heart rate|pulse)\s*[:=]\s*(\d+)", text)
        if hr_match:
            val = float(hr_match.group(1))
            if 30 <= val <= 250:  # Reasonable HR range
                vitals["hr"] = val

        # Respiratory rate
        rr_match = re.search(r"(?i)(?:RR|resp|respiratory)\s*[:\s]*(\d+)", text)
        if rr_match:
            vitals["rr"] = float(rr_match.group(1))

        # Temperature
        temp_match = re.search(r"(?i)(?:temp|temperature)\s*[:\s]*(\d+\.?\d*)", text)
        if temp_match:
            vitals["temp"] = float(temp_match.group(1))

        # SpO2 - with label
        spo2_match = re.search(r"(?i)(?:SpO2|O2 sat|oxygen)\s*[:\s]*(\d+)", text)
        if spo2_match:
            vitals["spo2"] = float(spo2_match.group(1))
        else:
            # SpO2 - standalone percentage (common in EHR displays)
            # Look for percentage values that could be SpO2 (typically 70-100%)
            pct_matches = re.findall(r"(\d{2,3})%", text)
            for pct in pct_matches:
                val = float(pct)
                if 50 <= val <= 100:  # Valid SpO2 range
                    vitals["spo2"] = val
                    break

        # Also look for unlabeled HR (number between 40-200)
        # Be very conservative - avoid matching ages like "45-yo"
        if "hr" not in vitals:
            # Only match numbers that are clearly vital signs context
            # Exclude numbers followed by -yo, yo, y/o, year, yo male/female
            hr_candidates = re.findall(r"(\d{2,3})(?![-\s]?y/?o|[-\s]?year|[-\s]?yo)", text)
            for n in hr_candidates:
                val = float(n)
                if 50 <= val <= 200 and val not in [vitals.get("sbp"), vitals.get("dbp")]:
                    # Must be in explicit vitals context (not just mention of "vitals")
                    # Look for vitals section markers
                    if re.search(r"(?i)vitals?\s*[:\[]", text):
                        vitals["hr"] = val
                        break

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

    def _check_wound_care_patterns(self, text: str, source_app: str) -> list[ClinicalAlert]:
        """Check for wound care and DFU-related patterns."""
        alerts = []
        now = datetime.now()

        for name, config in self.WOUND_CARE_PATTERNS.items():
            if re.search(config["pattern"], text):
                level = AlertLevel.ALERT if config["level"] == "alert" else \
                        AlertLevel.WARNING if config["level"] == "warning" else \
                        AlertLevel.SUGGESTION
                alerts.append(ClinicalAlert(
                    level=level,
                    message=config["message"],
                    details=config["details"],
                    timestamp=now,
                    source_app=source_app,
                    confidence=0.85,
                    category="wound_care"
                ))

        return alerts

    def _check_critical_patterns(self, text: str, source_app: str) -> list[ClinicalAlert]:
        """Check for critical 'can't miss' patterns - high mortality if delayed.

        These patterns are ALWAYS checked regardless of LLM reasoning.
        They serve as a safety net for known deadly presentations.

        Strategy: Fire the MOST SPECIFIC matching pattern for each condition.
        E.g., if boerhaave_high_risk matches, skip boerhaave_basic.
        """
        alerts = []
        now = datetime.now()

        # Track which base conditions matched at what severity
        # Higher number = more specific/severe
        severity_order = {"basic": 1, "high_risk": 2, "with_systemic": 3, "abnormal_vitals": 2}
        matched_conditions = {}  # base_name -> (severity, config, name)

        for name, config in self.CRITICAL_PATTERNS.items():
            if re.search(config["pattern"], text, re.DOTALL | re.IGNORECASE):
                # Determine base condition and specificity
                parts = name.split("_")
                base_name = parts[0]
                variant = "_".join(parts[1:]) if len(parts) > 1 else "basic"
                severity = severity_order.get(variant, 1)

                # Keep the most specific/severe match for each base condition
                if base_name not in matched_conditions or severity > matched_conditions[base_name][0]:
                    matched_conditions[base_name] = (severity, config, name)

        # Also check fit_check patterns - these always fire if matched
        for name, config in self.CRITICAL_PATTERNS.items():
            if config.get("category") == "fit_check":
                if re.search(config["pattern"], text, re.DOTALL | re.IGNORECASE):
                    level = AlertLevel.ALERT if config["level"] == "alert" else AlertLevel.WARNING
                    alerts.append(ClinicalAlert(
                        level=level,
                        message=config["message"],
                        details=config["details"],
                        timestamp=now,
                        source_app=source_app,
                        confidence=0.92,
                        category="fit_check",
                    ))

        # Create alerts for the most specific match of each condition
        for base_name, (severity, config, name) in matched_conditions.items():
            if config.get("category") == "fit_check":
                continue  # Already handled above

            level = AlertLevel.ALERT if config["level"] == "alert" else \
                    AlertLevel.WARNING if config["level"] == "warning" else \
                    AlertLevel.SUGGESTION

            alerts.append(ClinicalAlert(
                level=level,
                message=config["message"],
                details=config["details"],
                timestamp=now,
                source_app=source_app,
                confidence=0.90,
                category=config.get("category", "cant_miss"),
            ))

        return alerts

    def quick_check(self, content: ScreenContent) -> list[ClinicalAlert]:
        """INSTANT: Pattern-based checks (no LLM). Returns in <10ms.

        Two types of pattern checks:
        1. OBJECTIVE thresholds - critical labs and vitals
        2. CRITICAL patterns - known deadly presentations (can't miss)

        The LLM reasoning layer (analyze_with_llm) provides ADDITIONAL coverage
        for novel patterns and diagnostic fit assessment.
        """
        text = content.text_content
        if content.ocr_text and content.ocr_text != content.text_content:
            text += "\n" + content.ocr_text

        # Extract and check labs (objective thresholds)
        labs = self._extract_labs(text)
        lab_alerts = self._check_critical_labs(labs, content.app_name)

        # Extract and check vitals (objective thresholds)
        vitals = self._extract_vitals(text)
        vital_alerts = self._check_critical_vitals(vitals, content.app_name)

        # Check wound care patterns (domain-specific)
        wound_alerts = self._check_wound_care_patterns(text, content.app_name)

        # Check critical "can't miss" patterns (Boerhaave, dissection, etc.)
        # These ALWAYS fire - LLM reasoning provides additional coverage
        critical_alerts = self._check_critical_patterns(text, content.app_name)

        return lab_alerts + vital_alerts + wound_alerts + critical_alerts

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
