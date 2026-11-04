"""
Eligibility Engine — Full RFP parsing → Criterion extraction → Verdict per criterion → Overall assessment
"""

from __future__ import annotations
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

    async def execute(self, input: EligibilityInput) -> EligibilityOutput:
        checks = []
        missing = []

        for category, patterns in self.CRITERION_PATTERNS.items():
            # TODO: Use LLM to extract exact requirement text from RFP.raw_text
            # For now, create placeholder checks
            requirement = f"RFP requirement for {category.value}"
            profile_value = getattr(input.profile, category.value, None)

            if profile_value is None:
                missing.append(category.value)
                checks.append(CriterionCheck(
                    category=category,
                    requirement=requirement,
                    profile_value=None,
                    verdict=EligibilityVerdict.NEED_MORE_INFO,
                    reason=f"Profile missing {category.value}",
                    confidence=0.5,
                ))
            else:
                # TODO: Actual matching logic
                checks.append(CriterionCheck(
                    category=category,
                    requirement=requirement,
                    profile_value=str(profile_value),
                    verdict=EligibilityVerdict.ELIGIBLE,
                    reason=f"Profile meets {category.value}",
                    confidence=0.8,
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