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


_COUNTRY_ALIASES = {
    "us": "us",
    "usa": "us",
    "u s": "us",
    "u s a": "us",
    "united states": "us",
    "united states of america": "us",
    "canada": "canada",
    "ca": "canada",
    "uk": "uk",
    "gb": "uk",
    "united kingdom": "uk",
    "australia": "australia",
    "au": "australia",
}

_INSTITUTION_CLASSES = {
    "academic": ("university", "universities", "academic", "college", "colleges", "higher education"),
    "nonprofit": ("nonprofit", "non profit", "charitable", "501 c 3", "501c3"),
    "hospital": ("hospital", "health system"),
    "industry": ("small business", "for profit", "industry", "commercial"),
    "government": ("government", "federal agency", "state agency", "municipal"),
}


def _norm(value: str) -> str:
    """Lowercase and collapse punctuation so "non-profit" and "Non Profit" agree."""
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


# Values that fill a required field without describing anything. A profile built
# from no source carries these, so they must not be compared as if they were data.
_UNSTATED = {"", "unknown", "unspecified", "unstated", "not stated", "n a", "none", "tbd"}


def _canonical_country(value: str | None) -> str | None:
    if not value:
        return None
    normalised = _norm(value)
    return _COUNTRY_ALIASES.get(normalised, normalised)


def _canonical_institution(value: str | None) -> str | None:
    if not value:
        return None
    normalised = _norm(value)
    for klass, aliases in _INSTITUTION_CLASSES.items():
        if normalised == klass or normalised in {_norm(a) for a in aliases}:
            return klass
    return normalised


# Codes are scanned case-sensitively (uppercase "US" is a country, lowercase
# "us" is a pronoun); full names are case-insensitive.
_COUNTRY_CODES = {
    "US": "us",
    "USA": "us",
    "U.S.": "us",
    "U.S.A.": "us",
    "CA": "canada",
    "AU": "australia",
    "GB": "uk",
}

_COUNTRY_NAMES = {
    "united states": "us",
    "united states of america": "us",
    "canada": "canada",
    "united kingdom": "uk",
    "australia": "australia",
}


def _named_countries(statement: str) -> set[str]:
    """Countries the requirement names."""
    named = {
        canonical
        for code, canonical in _COUNTRY_CODES.items()
        if re.search(rf"(?<![A-Za-z]){re.escape(code)}(?![A-Za-z])", statement)
    }
    lowered = statement.lower()
    named |= {canonical for name, canonical in _COUNTRY_NAMES.items() if name in lowered}
    return named


def _named_institution_classes(statement: str) -> set[str]:
    named = set()
    for klass, aliases in _INSTITUTION_CLASSES.items():
        if any(re.search(rf"\b{re.escape(_norm(a))}\b", statement) for a in aliases):
            named.add(klass)
    return named


class EligibilityInput(EngineInput):
    rfp: RFP
    profile: Profile


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
            # Word-bounded: bare "esi" matches "r-esi-dents", so the ESI check
            # used to fire on the citizenship sentence and quote it as evidence.
            r"\bESI\b",
            r"\bESI-eligible\b",
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
        # Word-bounded: bare "state" matches "statement" (and "region" matches
        # nothing useful), so a statement-of-work sentence raised a geography
        # criterion and quoted itself as the requirement.
        CriterionCategory.GEOGRAPHY: [
            r"geographic",
            r"\bregion\b",
            r"\bstate\b",
            r"\bcountry\b",
            r"located in",
            # "Proposals are limited to 12 pages" is a length rule, so the
            # narrowing phrase has to be attached to eligibility.
            r"\beligibility (?:is )?limited to\b",
            # "institutions in Pennsylvania", "institutions based in ..."
            r"\binstitutions? (?:located |based )?in\b",
            # "US institutions", "U.S. organizations": a location rule with no
            # geography noun in it, which the nouns above never caught.
            r"\b(?:US|U\.S\.)\b[^.]{0,40}\b(?:institutions|organizations|applicants|entities)\b",
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
        matched = [
            sentence
            for sentence in sentences
            if any(re.search(p, sentence, re.IGNORECASE) for p in patterns)
        ]
        # A heading such as "EARLY STAGE INVESTIGATOR AWARD" matches the same
        # pattern as the requirement, so prefer a sentence that actually states
        # a rule: the heading was being quoted as the eligibility criterion.
        normative = re.compile(
            r"\b(must|shall|required|requires|eligib\w*|applicants?|priority|preference|only)\b",
            re.IGNORECASE,
        )
        if matched:
            stated = [s for s in matched if normative.search(s)]
            return " ".join((stated or matched)[0].split())[:300]
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
                CriterionCategory.GEOGRAPHY: "country",
                CriterionCategory.INSTITUTION_TYPE: "institution_type",
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
                    reason=(
                        f"Profile does not state {attr}, so {category.value} "
                        "cannot be assessed"
                    ),
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

                # For ESI status: a priority is not a requirement. "ESI-eligible
                # PIs receive priority" marked a non-ESI PI not_eligible, which
                # silently kills an application the funder invites.
                if category == CriterionCategory.ESI_STATUS:
                    stmt = (requirement_text or "").lower()
                    soft = any(
                        marker in stmt
                        for marker in ("priority", "preference", "preferred", "encouraged")
                    )
                    hard = any(
                        marker in stmt
                        for marker in ("must be", "required", "only", "eligibility requires")
                    )
                    if profile_value is True:
                        verdict = EligibilityVerdict.ELIGIBLE
                        reason = "ESI eligible - meets early stage investigator criterion"
                        confidence = 0.9
                    elif soft and not hard:
                        verdict = EligibilityVerdict.ELIGIBLE
                        reason = (
                            "ESI status is stated as a priority, not a requirement; "
                            "profile is not ESI-eligible and may rank lower"
                        )
                        confidence = 0.6
                    elif hard:
                        verdict = EligibilityVerdict.NOT_ELIGIBLE
                        reason = (
                            "RFP requires ESI status; profile is not ESI-eligible"
                        )
                        confidence = 0.8
                    else:
                        verdict = EligibilityVerdict.NEED_MORE_INFO
                        reason = (
                            "RFP mentions ESI without stating whether it is required; "
                            "profile is not ESI-eligible"
                        )
                        confidence = 0.5

                # For prior funding: the sentence says whether existing awards
                # are a bar, an overlap test, or only something to disclose. A
                # non-empty grant list was answering all three the same way.
                if category == CriterionCategory.PRIOR_FUNDING:
                    stmt = (requirement_text or "").lower()
                    barred = any(
                        marker in stmt
                        for marker in (
                            "must not",
                            "may not",
                            "no prior",
                            "not currently funded",
                            "not hold",
                            "are not eligible",
                        )
                    )
                    overlap = any(
                        marker in stmt
                        for marker in ("overlap", "duplicate", "same aims")
                    )
                    disclose = any(
                        marker in stmt
                        for marker in ("disclose", "disclosure", "must be listed", "report")
                    )
                    if barred:
                        verdict = EligibilityVerdict.NOT_ELIGIBLE
                        reason = (
                            "RFP bars applicants with prior or concurrent funding; "
                            f"profile lists {profile_value}"
                        )
                        confidence = 0.8
                    elif overlap:
                        verdict = EligibilityVerdict.NEED_MORE_INFO
                        reason = (
                            "RFP tests overlap with existing awards, which a grant "
                            f"list cannot settle (profile lists {profile_value})"
                        )
                        confidence = 0.5
                    elif disclose:
                        verdict = EligibilityVerdict.ELIGIBLE
                        reason = (
                            "RFP requires disclosure only, not exclusion; "
                            f"profile lists {profile_value} for disclosure"
                        )
                        confidence = 0.75
                    else:
                        verdict = EligibilityVerdict.NEED_MORE_INFO
                        reason = (
                            "RFP mentions prior funding without stating the rule; "
                            f"profile lists {profile_value}"
                        )
                        confidence = 0.5

                # For geography: a named country either matches the profile's
                # or it does not. A sub-national region ("Pennsylvania") is not
                # answerable from a country field, so it stays need_more_info.
                if category == CriterionCategory.GEOGRAPHY:
                    stmt = requirement_text or ""
                    canon = _canonical_country(str(profile_value))
                    named = _named_countries(stmt)
                    bar = any(
                        marker in _norm(stmt)
                        for marker in (
                            "only",
                            "limited to",
                            "restricted to",
                            "must be located",
                            "must reside",
                        )
                    )
                    if canon in named:
                        verdict = EligibilityVerdict.ELIGIBLE
                        reason = (
                            f"RFP names {canon} in its location rule; "
                            f"profile country is '{profile_value}'"
                        )
                        confidence = 0.85
                    elif named and bar:
                        verdict = EligibilityVerdict.NOT_ELIGIBLE
                        reason = (
                            f"RFP restricts eligibility to {'/'.join(sorted(named))}; "
                            f"profile country is '{profile_value}'"
                        )
                        confidence = 0.8
                    elif named:
                        verdict = EligibilityVerdict.NEED_MORE_INFO
                        reason = (
                            f"RFP names {'/'.join(sorted(named))} without stating whether "
                            f"it is a bar; profile country is '{profile_value}'"
                        )
                        confidence = 0.5
                    else:
                        verdict = EligibilityVerdict.NEED_MORE_INFO
                        reason = (
                            "RFP mentions geography without naming a country (a state or "
                            f"region cannot be checked against a country field); "
                            f"profile country is '{profile_value}'"
                        )
                        confidence = 0.5

                # For institution type: the funder names classes. A profile
                # class the RFP names is eligible; a bar naming only other
                # classes is a rejection; anything vaguer needs a human.
                if category == CriterionCategory.INSTITUTION_TYPE:
                    stmt = requirement_text or ""
                    klass = _canonical_institution(str(profile_value))
                    named = _named_institution_classes(_norm(stmt))
                    bar = any(
                        marker in _norm(stmt)
                        for marker in ("must be", "only", "limited to", "eligible", "required")
                    )
                    if klass in named:
                        verdict = EligibilityVerdict.ELIGIBLE
                        reason = (
                            f"RFP names {klass} institutions; profile institution type "
                            f"'{profile_value}' matches"
                        )
                        confidence = 0.85
                    elif named and bar:
                        verdict = EligibilityVerdict.NOT_ELIGIBLE
                        reason = (
                            f"RFP restricts eligibility to {'/'.join(sorted(named))}; "
                            f"profile institution type is '{profile_value}'"
                        )
                        confidence = 0.75
                    else:
                        verdict = EligibilityVerdict.NEED_MORE_INFO
                        reason = (
                            "RFP mentions institution type without naming a class the "
                            f"profile can be compared to; profile institution type is "
                            f"'{profile_value}'"
                        )
                        confidence = 0.5

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
                    elif stage_value in _UNSTATED:
                        # A placeholder is not a stage: comparing "unknown" to
                        # "early" produced NOT_ELIGIBLE at 0.8 confidence, a
                        # rejection built from a field nobody filled in.
                        verdict = EligibilityVerdict.NEED_MORE_INFO
                        reason = (
                            f"RFP targets {'/'.join(sorted(required))}-career "
                            "applicants; the profile states no career stage, so "
                            "this criterion is unchecked"
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