"""Screen monitor that extracts real clinical data - no hallucinations."""

import re
import time
import httpx
from typing import Optional
from dataclasses import dataclass
from rich.console import Console

console = Console()


@dataclass
class ClinicalContext:
    """Extracted clinical data from screen."""
    patient_name: Optional[str] = None
    mrn: Optional[str] = None
    medications: list[str] = None
    vitals: dict = None
    labs: dict = None
    diagnoses: list[str] = None
    allergies: list[str] = None
    concerns: list[str] = None  # Clinical concerns needing attention
    wound_info: dict = None  # Wound-specific data
    raw_text: str = ""

    def __post_init__(self):
        if self.medications is None:
            self.medications = []
        if self.vitals is None:
            self.vitals = {}
        if self.labs is None:
            self.labs = {}
        if self.diagnoses is None:
            self.diagnoses = []
        if self.allergies is None:
            self.allergies = []
        if self.concerns is None:
            self.concerns = []
        if self.wound_info is None:
            self.wound_info = {}

    def has_clinical_data(self) -> bool:
        """Check if we actually found clinical data."""
        return bool(
            self.mrn or
            self.medications or
            self.vitals or
            self.labs or
            self.diagnoses or
            self.allergies or
            self.concerns or
            self.wound_info
        )

    def summary(self) -> str:
        """Get a summary of extracted data."""
        parts = []
        if self.mrn:
            parts.append(f"MRN: {self.mrn}")
        if self.medications:
            parts.append(f"Meds: {', '.join(self.medications[:5])}")
        if self.vitals:
            parts.append(f"Vitals: {self.vitals}")
        if self.labs:
            parts.append(f"Labs: {list(self.labs.keys())[:5]}")
        if self.diagnoses:
            parts.append(f"Dx: {', '.join(self.diagnoses[:3])}")
        if self.allergies:
            parts.append(f"Allergies: {', '.join(self.allergies[:3])}")
        return " | ".join(parts) if parts else "No clinical data found"


class ScreenMonitor:
    """Monitor screen for clinical content and extract real data."""

    # Common medication patterns
    MED_PATTERNS = [
        r'\b(metformin|lisinopril|atorvastatin|omeprazole|amlodipine|metoprolol|losartan|gabapentin|hydrochlorothiazide|sertraline)\b',
        r'\b(aspirin|ibuprofen|acetaminophen|naproxen|prednisone|amoxicillin|azithromycin|ciprofloxacin)\b',
        r'\b(insulin|warfarin|heparin|enoxaparin|clopidogrel|apixaban|rivaroxaban)\b',
        r'\b(furosemide|spironolactone|carvedilol|digoxin|diltiazem|verapamil)\b',
        r'\b\d+\s*mg\b.*?\b[A-Za-z]+\b',  # "500 mg Metformin" pattern
    ]

    # Vital sign patterns
    VITAL_PATTERNS = {
        'bp': r'(?:BP|Blood Pressure)[:\s]*(\d{2,3})[/\\](\d{2,3})',
        'hr': r'(?:HR|Heart Rate|Pulse)[:\s]*(\d{2,3})',
        'temp': r'(?:Temp|Temperature)[:\s]*(\d{2,3}\.?\d?)',
        'spo2': r'(?:SpO2|O2 Sat|Oxygen)[:\s]*(\d{2,3})%?',
        'rr': r'(?:RR|Resp Rate)[:\s]*(\d{1,2})',
    }

    # Lab patterns
    LAB_PATTERNS = {
        'glucose': r'(?:Glucose|BG|Blood Sugar)[:\s]*(\d{2,4})',
        'hba1c': r'(?:HbA1c|A1C)[:\s]*(\d{1,2}\.?\d?)',
        'creatinine': r'(?:Creat|Creatinine)[:\s]*(\d{1,2}\.?\d{1,2})',
        'potassium': r'(?:K\+?|Potassium)[:\s]*(\d{1}\.?\d{1,2})',
        'sodium': r'(?:Na\+?|Sodium)[:\s]*(\d{2,3})',
        'wbc': r'(?:WBC|White Blood)[:\s]*(\d{1,2}\.?\d?)',
        'hemoglobin': r'(?:Hgb|Hemoglobin)[:\s]*(\d{1,2}\.?\d?)',
        'inr': r'(?:INR)[:\s]*(\d{1}\.?\d{1,2})',
    }

    # MRN patterns
    MRN_PATTERNS = [
        r'MRN[:\s#]*(\d{6,10})',
        r'Medical Record[:\s#]*(\d{6,10})',
        r'Patient ID[:\s#]*(\d{6,10})',
    ]

    # Diagnosis/ICD patterns
    DX_PATTERNS = [
        r'(?:Diagnosis|Dx|ICD)[:\s]*([A-Z]\d{2,3}\.?\d{0,2})',
        r'\b(diabetes|hypertension|CHF|COPD|CKD|CAD|afib|DVT|PE)\b',
        r'\b(T1DM|T2DM|DM1|DM2|type [12] diabetes)\b',
        r'\b(DFU|diabetic foot ulcer|pressure ulcer|venous ulcer)\b',
        r'\b(osteomyelitis|cellulitis|sepsis|SIRS)\b',
        r'\b(E10\.\d+|E11\.\d+|L97\.\d+|L89\.\d+)\b',  # Diabetes and ulcer ICD codes
    ]

    # Allergy patterns
    ALLERGY_PATTERNS = [
        r'(?:Allergies?|NKDA)[:\s]*([A-Za-z,\s]+?)(?:\n|$)',
        r'(?:Allergic to)[:\s]*([A-Za-z,\s]+?)(?:\n|$)',
    ]

    # Wound/procedure patterns
    WOUND_PATTERNS = [
        r'(?:wound|ulcer|DFU)[:\s]*(\d+\.?\d*)\s*(?:cm|mm|x)',
        r'(?:necrotic|slough|granulation|epithelial)',
        r'(?:debridement|I&D|wound care|dressing)',
        r'(?:plantar|heel|toe|forefoot|midfoot)',
    ]

    # Clinical concern patterns that need deeper analysis
    CONCERN_PATTERNS = {
        'infection_risk': r'(?:fever|chills|erythema|purulent|malodor|warmth|swelling)',
        'vascular_concern': r'(?:claudication|rest pain|ABI|pulse|ischemia|gangrene)',
        'glycemic_issue': r'(?:hypoglycemia|hyperglycemia|DKA|HHS|glucose.*(?:high|low|\d{3,}))',
        'anticoagulation': r'(?:warfarin|coumadin|INR|anticoag|bleeding|hematoma)',
        'renal_concern': r'(?:creatinine|GFR|dialysis|nephro|kidney)',
        'cardiac_concern': r'(?:chest pain|dyspnea|edema|BNP|troponin)',
    }

    def __init__(self, screenpipe_url: str = "http://localhost:3030"):
        self.screenpipe_url = screenpipe_url
        self.last_context: Optional[ClinicalContext] = None
        self.last_mrn: Optional[str] = None

    def get_screen_text(self) -> Optional[str]:
        """Get current screen text from Screenpipe."""
        try:
            with httpx.Client(timeout=5.0) as client:
                # Get recent OCR content with minimum length to filter noise
                resp = client.get(
                    f"{self.screenpipe_url}/search",
                    params={
                        "content_type": "ocr",
                        "limit": 10,
                        "offset": 0,
                        "min_length": 20,
                    }
                )
                if resp.status_code == 200:
                    data = resp.json()
                    texts = []
                    for item in data.get("data", []):
                        if "content" in item and "text" in item["content"]:
                            text = item["content"]["text"]
                            if text and len(text) > 10:
                                texts.append(text)
                    return "\n".join(texts)
        except Exception as e:
            return None
        return None

    def extract_clinical_data(self, text: str) -> ClinicalContext:
        """Extract structured clinical data from screen text."""
        context = ClinicalContext(raw_text=text[:1000])  # Keep first 1000 chars

        # Extract MRN
        for pattern in self.MRN_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                context.mrn = match.group(1)
                break

        # Extract medications
        meds_found = set()
        for pattern in self.MED_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            meds_found.update(m.lower() for m in matches if len(m) > 3)
        context.medications = list(meds_found)[:10]  # Limit to 10

        # Extract vitals
        for vital_name, pattern in self.VITAL_PATTERNS.items():
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                context.vitals[vital_name] = match.group(1)

        # Extract labs
        for lab_name, pattern in self.LAB_PATTERNS.items():
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                context.labs[lab_name] = match.group(1)

        # Extract diagnoses
        dx_found = set()
        for pattern in self.DX_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            dx_found.update(matches)
        context.diagnoses = list(dx_found)[:5]

        # Extract allergies
        for pattern in self.ALLERGY_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                allergies = match.group(1).strip()
                if allergies.upper() != "NKDA":
                    context.allergies = [a.strip() for a in allergies.split(",")][:5]
                break

        # Extract wound info
        for pattern in self.WOUND_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                context.wound_info['present'] = True
                if match.groups():
                    context.wound_info['detail'] = match.group(0)

        # Extract clinical concerns
        for concern_name, pattern in self.CONCERN_PATTERNS.items():
            if re.search(pattern, text, re.IGNORECASE):
                context.concerns.append(concern_name)

        return context

    def check_for_clinical_content(self) -> Optional[ClinicalContext]:
        """Check screen for clinical content and return extracted data."""
        text = self.get_screen_text()
        if not text:
            return None

        context = self.extract_clinical_data(text)

        # Only return if we found actual clinical data
        if context.has_clinical_data():
            self.last_context = context

            # Check if patient changed
            if context.mrn and context.mrn != self.last_mrn:
                self.last_mrn = context.mrn
                console.print(f"[bold cyan]Patient context: MRN {context.mrn}[/bold cyan]")

            return context

        return None

    def analyze_with_clinical_insight(self, context: ClinicalContext) -> Optional[str]:
        """Send extracted clinical data to Clinical Insight for analysis."""
        if not context.has_clinical_data():
            return None

        # Build a factual prompt based on REAL extracted data
        prompt_parts = ["Based on the following EXTRACTED clinical data from the patient's chart:\n"]

        if context.medications:
            prompt_parts.append(f"Current Medications: {', '.join(context.medications)}")

        if context.vitals:
            vitals_str = ", ".join(f"{k}: {v}" for k, v in context.vitals.items())
            prompt_parts.append(f"Vitals: {vitals_str}")

        if context.labs:
            labs_str = ", ".join(f"{k}: {v}" for k, v in context.labs.items())
            prompt_parts.append(f"Labs: {labs_str}")

        if context.diagnoses:
            prompt_parts.append(f"Diagnoses: {', '.join(context.diagnoses)}")

        if context.allergies:
            prompt_parts.append(f"Allergies: {', '.join(context.allergies)}")

        prompt_parts.append("\nIdentify any potential issues with this specific data:")
        prompt_parts.append("- Drug interactions between the listed medications")
        prompt_parts.append("- Lab values that are concerning given the diagnoses")
        prompt_parts.append("- Vital signs that need attention")
        prompt_parts.append("\nONLY comment on the data provided. Do not make assumptions.")

        prompt = "\n".join(prompt_parts)

        try:
            # Create conversation and send to Clinical Insight
            with httpx.Client(timeout=10.0) as client:
                conv_resp = client.post("http://localhost:8001/api/chat/new")
                conv_id = conv_resp.json().get("conversation_id")

            with httpx.Client(timeout=180.0) as client:
                result = client.post(
                    "http://localhost:8001/api/chat/message",
                    json={
                        "conversation_id": conv_id,
                        "message": prompt
                    }
                )
                return result.json().get("response")

        except Exception as e:
            console.print(f"[red]Analysis error: {e}[/red]")
            return None


def main():
    """Test the screen monitor."""
    monitor = ScreenMonitor()

    console.print("[bold]Screen Monitor Test[/bold]")
    console.print("Checking for clinical content...\n")

    context = monitor.check_for_clinical_content()

    if context:
        console.print(f"[green]Found clinical data:[/green]")
        console.print(context.summary())
    else:
        console.print("[yellow]No clinical data detected on screen[/yellow]")


if __name__ == "__main__":
    main()
