"""
Eligibility Engine — Full RFP parsing → Criterion extraction → Verdict per criterion → Overall assessment
"""

from __future__ import annotations
import re
from typing import Any

from grantforge.engine import Engine, EngineInput, EngineOutput
from grantforge.schemas import (
    Profile,
    EligibilityAssessment,
    CriterionCheck,
    EligibilityVerdict,
    CriterionCategory,
    RFP,
)


class EligibilityInput(EngineInput):
    rfp: RFP
    profile: Profile
    strict: bool = False


class EligibilityOutput(EngineOutput):
    assessment: EligibilityAssessment | None = None
    missing_criteria: list[str] = []


class EligibilityEngine(Engine[EligibilityInput, EligibilityOutput]):
    """Eligibility engine: parses RFP criteria, checks against profile, returns per-criterion verdict."""

    name = "eligibility"
    version = "2.0.0"

    # Criterion extraction patterns (career stage, citizenship, ESI, prior funding, etc.)
    CRITERION_PATTERNS = {
        CriterionCategory.CAREER_STAGE: [
            r"career stage",
            r"early career",
            r"new investigator",
            r"senior investigator",
        ],
        CriterionCategory.CITIZENSHIP: [
            r"citizen",
            r"permanent resident",
            r"nationality",
            r"foreign national",
        ],
        CriterionCategory.ESI_STATUS: [
            r"early stage investigator",
            r"esi",
            r"new investigator",
        ],
        CriterionCategory.PRIOR_FUNDING: [
            r"prior funding",
            r"previous grant",
            r"concurrent funding",
            r"overlap",
        ],
        CriterionCategory.MECHANISM_LIMIT: [
            r"limit.*application",
            r"one application",
            r"resubmission",
            r"amendment",
        ],
        CriterionCategory.GEOGRAPHY: [
            r"geographic",
            r"region",
            r"state",
            r"country",
        ],
        CriterionCategory.INSTITUTION_TYPE: [
            r"institution type",
            r"nonprofit",
            r"for-profit",
            r"academic",
            r"hospital",
        ],
    }

    # Phrases that name the career stage a funder targets. Used to compare the
    # profile against what the RFP actually asks for: a hardcoded "early/mid is
    # fine" rule marked a senior PI eligible for an early-career programme.
    STAGE_PHRASES = {
        "early": ("early career", "early-career", "new investigator", "junior investigator"),
        "mid": ("mid-career", "mid career", "midcareer"),
        "senior": ("senior investigator", "senior career", "established investigator"),
    }

    def _extract_requirement(self, rfp_text: str, category: CriterionCategory) -> str | None:
        """Return the sentence stating the requirement, not a fixed-size window.

        A window that starts 50 characters before the match begins mid-word
        ("search strategy.\n\nEligibility. Applicants must be early c"), which is
        the quote a grant office would have to read back to the PI.
        """
        patterns = self.CRITERION_PATTERNS.get(category, [])
        sentences = [s for s in re.split(r"(?<=\.)\s+|\n{2,}", rfp_text) if s.strip()]
        for pattern in patterns:
            for sentence in sentences:
                if re.search(pattern, sentence, re.IGNORECASE):
                    return " ".join(sentence.split())[:300]
        # Fall back to a window only if no single sentence carries the match.
        for pattern in patterns:
            match = re.search(pattern, rfp_text, re.IGNORECASE)
            if match:
                start = max(0, match.start() - 50)
                end = min(len(rfp_text), match.end() + 150)
                return " ".join(rfp_text[start:end].split())
        return None

    async def execute(self, input: EligibilityInput) -> EligibilityOutput:
        checks = []
        missing = []
        rfp_text = input.rfp.raw_text.lower()

        for category, patterns in self.CRITERION_PATTERNS.items():
            requirement_text = self._extract_requirement(input.rfp.raw_text, category)
            requirement = requirement_text or f"RFP requirement for {category.value}"

            # Map profile attributes to criterion categories
            profile_attr_map = {
                CriterionCategory.CAREER_STAGE: "career_stage",
                CriterionCategory.CITIZENSHIP: "citizenship",
                CriterionCategory.ESI_STATUS: "esi_eligible",
                CriterionCategory.PRIOR_FUNDING: "prior_grants",
                CriterionCategory.GEOGRAPHY: None,
                CriterionCategory.INSTITUTION_TYPE: None,
                CriterionCategory.MECHANISM_LIMIT: None,
                CriterionCategory.OTHER: None,
            }

            attr = profile_attr_map.get(category)
            profile_value = None
            if attr:
                profile_value = getattr(input.profile, attr, None)

            # Check if requirement exists in RFP
            req_in_rfp = any(
                re.search(p, rfp_text, re.IGNORECASE) for p in patterns
            )

            if not req_in_rfp:
                # Criterion not mentioned in RFP - skip
                continue

            if profile_value is None or (isinstance(profile_value, list) and not profile_value):
                missing.append(category.value)
                checks.append(CriterionCheck(
                    category=category,
                    requirement=requirement,
                    profile_value=None,
                    verdict=EligibilityVerdict.NEED_MORE_INFO,
                    reason=f"Profile missing {category.value} information",
                    confidence=0.5,
                ))
            else:
                # Basic matching: check if profile value aligns with RFP requirement
                verdict = EligibilityVerdict.ELIGIBLE
                reason = f"Profile provides {category.value}: {profile_value}"
                confidence = 0.7

                # For citizenship, check if profile citizenship matches RFP
                if category == CriterionCategory.CITIZENSHIP:
                    if isinstance(profile_value, list) and "US" in profile_value:
                        verdict = EligibilityVerdict.ELIGIBLE
                        reason = "US citizen/permanent resident - meets typical citizenship requirement"
                        confidence = 0.85
                    else:
                        verdict = EligibilityVerdict.NEED_MORE_INFO
                        reason = "Citizenship status may not meet RFP requirement"
                        confidence = 0.6

                # For ESI status
                if category == CriterionCategory.ESI_STATUS:
                    if profile_value is True:
                        verdict = EligibilityVerdict.ELIGIBLE
                        reason = "ESI eligible - meets early stage investigator requirement"
                        confidence = 0.9
                    else:
                        verdict = EligibilityVerdict.NOT_ELIGIBLE
                        reason = "Not ESI eligible - does not meet early stage investigator requirement"
                        confidence = 0.8

                # For career stage: compare against the stage the RFP names, not
                # against an assumption about what funders usually want.
                if category == CriterionCategory.CAREER_STAGE:
                    required = {
                        stage
                        for stage, phrases in self.STAGE_PHRASES.items()
                        if any(phrase in rfp_text for phrase in phrases)
                    }
                    # "early stage investigator" / ESI language also means early career.
                    if re.search(r"early stage investigator|\besi\b", rfp_text, re.IGNORECASE):
                        required.add("early")

                    stage_value = str(profile_value).strip().lower()
                    if not required:
                        verdict = EligibilityVerdict.NEED_MORE_INFO
                        reason = (
                            f"RFP mentions career stage without naming one; "
                            f"profile career stage is '{profile_value}'"
                        )
                        confidence = 0.5
                    elif stage_value in required:
                        verdict = EligibilityVerdict.ELIGIBLE
                        reason = (
                            f"RFP targets {'/'.join(sorted(required))}-career applicants; "
                            f"profile career stage '{profile_value}' matches"
                        )
                        confidence = 0.85
                    else:
                        verdict = EligibilityVerdict.NOT_ELIGIBLE
                        reason = (
                            f"RFP targets {'/'.join(sorted(required))}-career applicants; "
                            f"profile career stage '{profile_value}' does not match"
                        )
                        confidence = 0.8

                checks.append(CriterionCheck(
                    category=category,
                    requirement=requirement,
                    profile_value=str(profile_value),
                    verdict=verdict,
                    reason=reason,
                    confidence=confidence,
                ))

        # Overall verdict
        if any(c.verdict == EligibilityVerdict.NOT_ELIGIBLE for c in checks):
            overall = EligibilityVerdict.NOT_ELIGIBLE
        elif any(c.verdict == EligibilityVerdict.NEED_MORE_INFO for c in checks):
            overall = EligibilityVerdict.NEED_MORE_INFO
        else:
            overall = EligibilityVerdict.ELIGIBLE

        assessment = EligibilityAssessment(
            overall=overall,
            checks=checks,
            missing_info=missing,
        )

        return EligibilityOutput(
            success=True,
            assessment=assessment,
            missing_criteria=missing,
        )

    async def health_check(self) -> dict[str, Any]:
        return await super().health_check()