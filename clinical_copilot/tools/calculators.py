"""Clinical calculators for common scoring systems."""

from typing import Optional
from pydantic import BaseModel
from enum import Enum


class RiskLevel(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    VERY_HIGH = "very_high"


class CalculatorResult(BaseModel):
    """Result from a clinical calculator."""
    name: str
    score: float
    interpretation: str
    risk_level: RiskLevel
    details: Optional[dict] = None


class ClinicalCalculators:
    """Collection of clinical calculators."""

    @staticmethod
    def gfr_ckd_epi(
        creatinine: float,
        age: int,
        is_female: bool,
        is_black: bool = False
    ) -> CalculatorResult:
        """Calculate GFR using CKD-EPI equation (2021 update - no race)."""
        # 2021 CKD-EPI without race
        if is_female:
            if creatinine <= 0.7:
                gfr = 142 * ((creatinine / 0.7) ** -0.241) * (0.9938 ** age)
            else:
                gfr = 142 * ((creatinine / 0.7) ** -1.200) * (0.9938 ** age)
        else:
            if creatinine <= 0.9:
                gfr = 142 * ((creatinine / 0.9) ** -0.302) * (0.9938 ** age)
            else:
                gfr = 142 * ((creatinine / 0.9) ** -1.200) * (0.9938 ** age)

        # Stage determination
        if gfr >= 90:
            interpretation = "Normal or high (G1)"
            risk = RiskLevel.LOW
        elif gfr >= 60:
            interpretation = "Mildly decreased (G2)"
            risk = RiskLevel.LOW
        elif gfr >= 45:
            interpretation = "Mild to moderately decreased (G3a)"
            risk = RiskLevel.MODERATE
        elif gfr >= 30:
            interpretation = "Moderately to severely decreased (G3b)"
            risk = RiskLevel.MODERATE
        elif gfr >= 15:
            interpretation = "Severely decreased (G4)"
            risk = RiskLevel.HIGH
        else:
            interpretation = "Kidney failure (G5)"
            risk = RiskLevel.VERY_HIGH

        return CalculatorResult(
            name="GFR (CKD-EPI 2021)",
            score=round(gfr, 1),
            interpretation=interpretation,
            risk_level=risk,
            details={"unit": "mL/min/1.73m²"}
        )

    @staticmethod
    def meld_score(
        bilirubin: float,
        inr: float,
        creatinine: float,
        sodium: Optional[float] = None,
        is_dialysis: bool = False
    ) -> CalculatorResult:
        """Calculate MELD or MELD-Na score."""
        import math

        # Bound values
        bilirubin = max(1.0, bilirubin)
        creatinine = max(1.0, min(4.0, creatinine))
        if is_dialysis:
            creatinine = 4.0
        inr = max(1.0, inr)

        # MELD calculation
        meld = (
            10 * (
                0.957 * math.log(creatinine) +
                0.378 * math.log(bilirubin) +
                1.120 * math.log(inr) +
                0.643
            )
        )
        meld = round(meld)

        # MELD-Na if sodium provided
        if sodium is not None:
            sodium = max(125, min(137, sodium))
            meld_na = meld + 1.32 * (137 - sodium) - 0.033 * meld * (137 - sodium)
            meld_na = round(max(6, min(40, meld_na)))
            score = meld_na
            name = "MELD-Na"
        else:
            score = max(6, min(40, meld))
            name = "MELD"

        # Interpretation
        if score < 10:
            interpretation = "3-month mortality ~2%"
            risk = RiskLevel.LOW
        elif score < 20:
            interpretation = "3-month mortality ~6%"
            risk = RiskLevel.MODERATE
        elif score < 30:
            interpretation = "3-month mortality ~20%"
            risk = RiskLevel.HIGH
        else:
            interpretation = "3-month mortality ~50%+"
            risk = RiskLevel.VERY_HIGH

        return CalculatorResult(
            name=name,
            score=score,
            interpretation=interpretation,
            risk_level=risk,
        )

    @staticmethod
    def wells_dvt(
        active_cancer: bool = False,
        paralysis_paresis: bool = False,
        bedridden_3_days: bool = False,
        localized_tenderness: bool = False,
        entire_leg_swollen: bool = False,
        calf_swelling_3cm: bool = False,
        pitting_edema: bool = False,
        collateral_veins: bool = False,
        previous_dvt: bool = False,
        alternative_diagnosis_likely: bool = False
    ) -> CalculatorResult:
        """Calculate Wells' Criteria for DVT."""
        score = 0
        if active_cancer:
            score += 1
        if paralysis_paresis:
            score += 1
        if bedridden_3_days:
            score += 1
        if localized_tenderness:
            score += 1
        if entire_leg_swollen:
            score += 1
        if calf_swelling_3cm:
            score += 1
        if pitting_edema:
            score += 1
        if collateral_veins:
            score += 1
        if previous_dvt:
            score += 1
        if alternative_diagnosis_likely:
            score -= 2

        if score <= 0:
            interpretation = "Low probability (~5% DVT risk)"
            risk = RiskLevel.LOW
        elif score <= 2:
            interpretation = "Moderate probability (~17% DVT risk)"
            risk = RiskLevel.MODERATE
        else:
            interpretation = "High probability (~53% DVT risk)"
            risk = RiskLevel.HIGH

        return CalculatorResult(
            name="Wells' Criteria (DVT)",
            score=score,
            interpretation=interpretation,
            risk_level=risk,
        )

    @staticmethod
    def wells_pe(
        clinical_signs_dvt: bool = False,
        pe_most_likely: bool = False,
        heart_rate_gt_100: bool = False,
        immobilization_surgery: bool = False,
        previous_pe_dvt: bool = False,
        hemoptysis: bool = False,
        malignancy: bool = False
    ) -> CalculatorResult:
        """Calculate Wells' Criteria for PE."""
        score = 0
        if clinical_signs_dvt:
            score += 3
        if pe_most_likely:
            score += 3
        if heart_rate_gt_100:
            score += 1.5
        if immobilization_surgery:
            score += 1.5
        if previous_pe_dvt:
            score += 1.5
        if hemoptysis:
            score += 1
        if malignancy:
            score += 1

        if score <= 4:
            interpretation = "PE unlikely (<15% probability)"
            risk = RiskLevel.LOW
        else:
            interpretation = "PE likely (>15% probability)"
            risk = RiskLevel.HIGH

        return CalculatorResult(
            name="Wells' Criteria (PE)",
            score=score,
            interpretation=interpretation,
            risk_level=risk,
        )

    @staticmethod
    def chadsvasc(
        chf: bool = False,
        hypertension: bool = False,
        age_65_74: bool = False,
        age_75_plus: bool = False,
        diabetes: bool = False,
        stroke_tia: bool = False,
        vascular_disease: bool = False,
        female: bool = False
    ) -> CalculatorResult:
        """Calculate CHA₂DS₂-VASc score."""
        score = 0
        if chf:
            score += 1
        if hypertension:
            score += 1
        if age_75_plus:
            score += 2
        elif age_65_74:
            score += 1
        if diabetes:
            score += 1
        if stroke_tia:
            score += 2
        if vascular_disease:
            score += 1
        if female:
            score += 1

        # Annual stroke risk
        risk_map = {
            0: ("0% annual stroke risk", RiskLevel.LOW),
            1: ("1.3% annual stroke risk", RiskLevel.LOW),
            2: ("2.2% annual stroke risk", RiskLevel.MODERATE),
            3: ("3.2% annual stroke risk", RiskLevel.MODERATE),
            4: ("4.0% annual stroke risk", RiskLevel.HIGH),
            5: ("6.7% annual stroke risk", RiskLevel.HIGH),
            6: ("9.8% annual stroke risk", RiskLevel.VERY_HIGH),
            7: ("9.6% annual stroke risk", RiskLevel.VERY_HIGH),
            8: ("12.5% annual stroke risk", RiskLevel.VERY_HIGH),
            9: ("15.2% annual stroke risk", RiskLevel.VERY_HIGH),
        }

        interpretation, risk = risk_map.get(min(score, 9), ("High risk", RiskLevel.VERY_HIGH))

        return CalculatorResult(
            name="CHA₂DS₂-VASc",
            score=score,
            interpretation=interpretation,
            risk_level=risk,
        )

    @staticmethod
    def hasbled(
        hypertension: bool = False,
        renal_disease: bool = False,
        liver_disease: bool = False,
        stroke_history: bool = False,
        bleeding_history: bool = False,
        labile_inr: bool = False,
        age_gt_65: bool = False,
        drugs_alcohol: bool = False
    ) -> CalculatorResult:
        """Calculate HAS-BLED score."""
        score = 0
        if hypertension:
            score += 1
        if renal_disease:
            score += 1
        if liver_disease:
            score += 1
        if stroke_history:
            score += 1
        if bleeding_history:
            score += 1
        if labile_inr:
            score += 1
        if age_gt_65:
            score += 1
        if drugs_alcohol:
            score += 1  # Can be up to 2 if both

        if score <= 1:
            interpretation = "Low bleeding risk"
            risk = RiskLevel.LOW
        elif score == 2:
            interpretation = "Moderate bleeding risk"
            risk = RiskLevel.MODERATE
        else:
            interpretation = "High bleeding risk - caution with anticoagulation"
            risk = RiskLevel.HIGH

        return CalculatorResult(
            name="HAS-BLED",
            score=score,
            interpretation=interpretation,
            risk_level=risk,
        )

    @staticmethod
    def curb65(
        confusion: bool = False,
        urea_gt_7: bool = False,
        respiratory_rate_ge_30: bool = False,
        sbp_lt_90_or_dbp_le_60: bool = False,
        age_ge_65: bool = False
    ) -> CalculatorResult:
        """Calculate CURB-65 score for pneumonia severity."""
        score = sum([
            confusion, urea_gt_7, respiratory_rate_ge_30,
            sbp_lt_90_or_dbp_le_60, age_ge_65
        ])

        if score <= 1:
            interpretation = "Low severity - consider outpatient treatment"
            risk = RiskLevel.LOW
        elif score == 2:
            interpretation = "Moderate severity - consider hospital admission"
            risk = RiskLevel.MODERATE
        else:
            interpretation = "High severity - consider ICU admission"
            risk = RiskLevel.HIGH

        return CalculatorResult(
            name="CURB-65",
            score=score,
            interpretation=interpretation,
            risk_level=risk,
        )

    @classmethod
    def list_calculators(cls) -> list[str]:
        """List available calculators."""
        return [
            "gfr_ckd_epi",
            "meld_score",
            "wells_dvt",
            "wells_pe",
            "chadsvasc",
            "hasbled",
            "curb65",
        ]
