# coding: utf-8
"""Real fixtures for the six grantforge engines.

These are not stubs: each object is a complete, schema-valid domain object whose
content is what the engines actually parse. The RFP text carries the exact
markers ``discovery._ingest_rfp`` reads (deadline, page limit, mechanism, amount,
required sections) and the exact phrases ``eligibility`` matches per criterion
category, so a passing test means the parsers found those markers — not that a
model accepted a dict.

Important: the RFP text deliberately avoids the words the *other* criterion
patterns match (geography: state/region/country; institution type: nonprofit/
academic/hospital; mechanism limit: application/resubmission/amendment), so the
expected eligibility check set is exactly the four criteria below.
"""

from __future__ import annotations

from datetime import datetime

from grantforge.schemas import (
    ChecklistItem,
    CriterionCheck,
    EligibilityAssessment,
    EligibilityVerdict,
    CriterionCategory,
    Proposal,
    Profile,
    RFP,
    SectionDraft,
)

# Every marker below is consumed by a regex in discovery._ingest_rfp or by the
# eligibility CRITERION_PATTERNS. Do not reword without re-reading those.
RFP_TEXT = """INNOVATION FOR UNDERREPRESENTED RESEARCHERS (R01)
National Science Foundation - Directorate for Engineering
deadline: 2027-03-01
Required sections: Specific Aims, Research Strategy, Budget Justification

Award ceiling $450,000 over three years. Proposals are limited to a 12 page
research strategy.

Eligibility. Applicants must be early career investigators who are citizens or
permanent residents of the US. ESI-eligible PIs receive priority. Applicants
with prior funding from this program must disclose it.
"""


def make_rfp(**overrides) -> RFP:
    """The canned RFP as a parsed model, deadline fixed for reproducibility."""
    base = dict(
        id="rfp_nsf_career_01",
        funder_id="nsf",
        title="INNOVATION FOR UNDERREPRESENTED RESEARCHERS (R01)",
        number="NSF-25-601",
        deadline=datetime(2027, 3, 1),
        mechanism="R01",
        max_amount=450000.0,
        page_limit=12,
        sections_required=["Specific Aims", "Research Strategy", "Budget Justification"],
        formatting_rules={"font": "Arial 11pt", "margins": "1in"},
        raw_text=RFP_TEXT,
    )
    base.update(overrides)
    return RFP(**base)


def make_profile(**overrides) -> Profile:
    """A complete early-career profile: every criterion the RFP raises is answered."""
    base = dict(
        id="prof_okonkwo",
        name="Dr. Ada Okonkwo",
        orcid="0000-0002-1825-0097",
        institution="Rensselaer Polytechnic Institute",
        department="Electrical, Computer, and Systems Engineering",
        # The fixture RFP raises neither criterion, so these two answer only the
        # tests that add a geography or institution-type sentence — but they are
        # part of a complete profile, not test-only extras.
        institution_type="university",
        country="US",
        career_stage="early",
        esi_eligible=True,
        citizenship=["US"],
        prior_grants=["R21-EB034567"],
        publications=["10.1109/TBME.2025.0001", "10.1038/s41586-025-00001"],
        research_areas=["low-power sensing", "edge inference", "biomedical signal processing"],
    )
    base.update(overrides)
    return Profile(**base)


_AIMS = (
    "This proposal develops sub-milliwatt adaptive sensing hardware for continuous "
    "cardiac monitoring outside clinical settings. The central hypothesis is that "
    "event-driven sampling with on-chip inference reduces average power by an order "
    "of magnitude without losing diagnostic fidelity. We will build three integrated "
    "aims. Aim one characterises the noise floor of the analog front end across "
    "temperature and motion artefact. Aim two co-designs a spiking feature extractor "
    "with the sampling schedule so that computation and acquisition share one clock "
    "domain. Aim three validates the system against twelve-lead reference recordings "
    "collected from forty participants. Success is defined as a tenfold power "
    "reduction at equal sensitivity and specificity, measured on held-out subjects. "
    "The work is significant because wearable monitors fail on battery life rather "
    "than on signal quality, and it is innovative because sampling and inference are "
    "designed together instead of in sequence."
)

_STRATEGY = (
    "The research strategy is organised around three aims and four milestones. "
    "Milestone one delivers a characterised front end with a measured noise budget. "
    "Milestone two delivers the co-designed extractor with a cycle-accurate power "
    "model. Milestone three delivers the validation dataset and the statistical "
    "analysis plan. Milestone four delivers the integrated prototype and the "
    "reproducibility package. Each milestone has a quantitative exit criterion, "
    "and each is scheduled against a twelve-month budget period so that slippage is "
    "visible early. Risk is managed by keeping a conventional always-on sampling "
    "path as a fallback, which lets the team isolate whether a shortfall comes from "
    "the analog design or from the inference schedule. Preliminary work established "
    "the front-end topology and produced a working extractor on an FPGA, so the "
    "remaining risk is integration rather than invention."
)


def _section(sid: str, title: str, content: str, version: int = 1) -> SectionDraft:
    return SectionDraft(
        id=sid,
        title=title,
        content=content,
        word_count=len(content.split()),
        version=version,
    )


def make_proposal(rfp: RFP | None = None, profile: Profile | None = None, **overrides) -> Proposal:
    """A proposal with two full sections and a checklist, for compliance/export."""
    rfp = rfp or make_rfp()
    profile = profile or make_profile()
    aims = _section("specific_aims", "Specific Aims", _AIMS)
    strategy = _section("research_strategy", "Research Strategy", _STRATEGY)
    checklist = [
        ChecklistItem(id="cl_0", section="Specific Aims", requirement="Write Specific Aims",
                      page_limit=rfp.page_limit, status="done", assignee=profile.id),
        ChecklistItem(id="cl_1", section="Research Strategy", requirement="Write Research Strategy",
                      page_limit=rfp.page_limit, status="review"),
        ChecklistItem(id="cl_budget", section="Budget", requirement="Budget justification",
                      status="pending"),
    ]
    base = dict(
        id="prop_cardiac_01",
        rfp_id=rfp.id,
        title="Sub-milliwatt adaptive sensing for continuous cardiac monitoring",
        pi_profile_id=profile.id,
        sections={aims.id: aims, strategy.id: strategy},
        checklist=checklist,
        status="draft",
    )
    base.update(overrides)
    return Proposal(**base)


def make_assessment(verdict: EligibilityVerdict = EligibilityVerdict.ELIGIBLE) -> EligibilityAssessment:
    """An eligibility assessment for proposal-level compliance checks."""
    return EligibilityAssessment(
        overall=verdict,
        checks=[
            CriterionCheck(
                category=CriterionCategory.CAREER_STAGE,
                requirement="Applicants must be early career investigators",
                profile_value="early",
                verdict=verdict,
                reason="fixture",
                confidence=0.75,
            )
        ],
    )


def make_short_section_proposal() -> Proposal:
    """Negative control: a section too short for the format check to pass."""
    short = _section("specific_aims", "Specific Aims", "We will build a sensor.")
    return make_proposal(sections={short.id: short})
