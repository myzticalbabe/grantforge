# coding: utf-8
"""End-to-end tests for the six grantforge engines.

Every test drives an engine through ``Engine.run`` (validate -> execute) with a
complete domain fixture, then asserts on the *content* of the output: the parsed
deadline, the criterion set, the checklist ids, the export magic bytes. A test
that only asserted ``success is True`` would pass on an engine that returned an
empty model, which is exactly the state these tests exist to rule out.

Run with: python -m pytest tests/test_grantforge_engines.py -v
"""

import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile

import pytest
from datetime import datetime, timezone
from io import BytesIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from fixtures.grantforge_fixtures import (  # noqa: E402
    RFP_TEXT,
    make_assessment,
    make_profile,
    make_proposal,
    make_rfp,
    make_short_section_proposal,
)

from grantforge.collaboration import CollaborationEngine, CollaborationInput  # noqa: E402
from grantforge.compliance import ComplianceEngine, ComplianceInput  # noqa: E402
from grantforge.discovery import DiscoveryEngine, DiscoveryInput  # noqa: E402
from grantforge.drafting import DraftingEngine, DraftingInput  # noqa: E402
from grantforge.eligibility import EligibilityEngine, EligibilityInput  # noqa: E402
from grantforge.engine import Engine, EngineInput, EngineOutput  # noqa: E402
from grantforge import export as export_module  # noqa: E402
from grantforge.export import ExportEngine, ExportInput  # noqa: E402
from grantforge.pipeline import GrantPipeline  # noqa: E402
from grantforge.schemas import (  # noqa: E402
    EligibilityVerdict,
    ExportFormat,
    FunderType,
    GrantMechanism,
)


def run(coro):
    """Run one engine coroutine to completion (tests stay sync, no plugin needed)."""
    return asyncio.run(coro)


# ── discovery ────────────────────────────────────────────────────────────────

def test_discovery_parses_rfp_markers():
    out = run(DiscoveryEngine().run(DiscoveryInput(rfp_text=RFP_TEXT)))
    assert out.success is True
    rfp = out.rfp
    assert rfp is not None
    assert rfp.title == "INNOVATION FOR UNDERREPRESENTED RESEARCHERS (R01)"
    assert rfp.deadline is not None
    assert rfp.deadline.date().isoformat() == "2027-03-01"
    assert out.metadata["deadline_source"] == "parsed"
    assert rfp.page_limit == 12
    assert rfp.mechanism == GrantMechanism.R01
    assert rfp.max_amount == 450000.0
    assert rfp.sections_required == ["Specific Aims", "Research Strategy", "Budget Justification"]
    assert out.metadata["mode"] == "rfp_ingest"


def test_discovery_does_not_invent_a_deadline_the_rfp_never_stated():
    text = (
        "PILOT STUDIES IN CARDIAC SENSING\n"
        "Eligibility: Applicants must be early career investigators.\n"
        "Proposals are limited to a 12 page research strategy.\n"
        "Required sections: Specific Aims, Research Strategy\n"
    )
    out = run(DiscoveryEngine().run(DiscoveryInput(rfp_text=text)))
    assert out.rfp is not None
    assert out.rfp.deadline is None
    assert out.metadata["deadline_source"] == "not_stated"

    # Negative control: the same parser still reads a stated date.
    dated = text.replace(
        "Required sections:", "Deadline: 2027-01-15\nRequired sections:"
    )
    parsed = run(DiscoveryEngine().run(DiscoveryInput(rfp_text=dated)))
    assert parsed.rfp is not None and parsed.rfp.deadline is not None
    assert parsed.rfp.deadline.date().isoformat() == "2027-01-15"
    assert parsed.metadata["deadline_source"] == "parsed"


def test_export_says_a_deadline_is_unstated_instead_of_printing_none():
    rfp = make_rfp(deadline=None)
    out = run(ExportEngine().run(ExportInput(
        proposal=make_proposal(), pi_profile=make_profile(), rfp=rfp,
    )))
    assert out.bundle.manifest["deadline"] is None
    docx_text = _zip_text(out.files["prop_cardiac_01_proposal.docx"])
    assert "not stated in the RFP" in docx_text
    assert "Deadline: None" not in docx_text


def test_discovery_search_matches_the_query_not_a_fixed_prefix():
    """It used to return the first top_k of a fixed funder list for any query, so
    the keywords it extracted were decoration and 'crop rotation' answered
    nih/nsf/doe. Matching is now real: only funders whose domain hits the query."""
    engine = DiscoveryEngine()
    cardiac = run(engine.run(DiscoveryInput(query="cardiac sensing", top_k=5)))
    assert cardiac.success is True
    assert [f.id for f in cardiac.opportunities] == ["nih", "nsf"]
    assert cardiac.metadata["matched"] == {"nih": ["cardiac"], "nsf": ["sensing"]}
    assert cardiac.metadata["keywords"] == ["cardiac", "sensing"]

    crops = run(engine.run(DiscoveryInput(query="crop rotation", top_k=5)))
    assert [f.id for f in crops.opportunities] == ["usda"]

    # Ranked by hits, then id: 'power' hits doe only.
    power = run(engine.run(DiscoveryInput(query="power grid efficiency", top_k=5)))
    assert [f.id for f in power.opportunities] == ["doe"]
    assert power.metadata["matched"] == {"doe": ["efficiency", "grid", "power"]}


def test_discovery_search_with_no_match_returns_nothing():
    """An off-corpus query is an empty result, not the catalogue's first entries."""
    out = run(DiscoveryEngine().run(DiscoveryInput(query="medieval poetry", top_k=3)))
    assert out.success is True
    assert out.opportunities == []
    assert out.metadata["corpus_size"] == 5
    assert out.metadata["matched"] == {}
    assert "not that a call is open" in out.metadata["note"]


def test_discovery_search_respects_top_k():
    """One hit each, so the tie-break by id decides: doe, nih, nsf -> first 2."""
    out = run(DiscoveryEngine().run(DiscoveryInput(query="science health energy", top_k=2)))
    assert [f.id for f in out.opportunities] == ["doe", "nih"]


def test_discovery_funder_intel_reports_only_the_ein_it_was_given():
    """No 990 is fetched or parsed, so the intel must not claim a filing.

    It used to emit total_giving=0/avg_grant=0 and a hardcoded name map, and the
    map called 53-0196605 the National Science Foundation when that EIN is the
    American National Red Cross -- a fabricated identity behind a measured-
    looking dict. Identity is now the EIN and the giving figures are absent.
    """
    out = run(DiscoveryEngine().run(DiscoveryInput(funder_ein="53-0196605")))
    assert out.funder_intel is not None
    assert out.funder_intel.ein == "53-0196605"
    assert out.funder_intel.name == "EIN 53-0196605"
    assert out.funder_intel.giving_patterns == {}
    assert out.metadata["mode"] == "funder_intel"
    assert out.metadata["identity_source"] == "ein_only"
    assert out.metadata["giving_patterns_source"] == "unavailable_no_990_parser"


def test_discovery_builds_profile_from_supplied_profile():
    """`profile_build` is reached only when a profile is passed and no query is:
    dispatch order is rfp_text -> query -> funder_ein -> profile."""
    profile = make_profile()
    out = run(DiscoveryEngine().run(DiscoveryInput(profile=profile)))
    assert out.profile is profile
    assert out.profile.research_areas == [
        "low-power sensing", "edge inference", "biomedical signal processing",
    ]
    assert out.metadata["mode"] == "profile_build"
    assert out.metadata["areas"] == out.profile.research_areas


def test_discovery_rejects_empty_input():
    out = run(DiscoveryEngine().run(DiscoveryInput()))
    assert out.success is False
    assert out.error == "No valid input provided"


# ── eligibility ──────────────────────────────────────────────────────────────

def test_eligibility_full_profile_is_eligible():
    out = run(EligibilityEngine().run(EligibilityInput(rfp=make_rfp(), profile=make_profile())))
    assert out.success is True
    assessment = out.assessment
    assert assessment is not None
    assert assessment.overall == EligibilityVerdict.ELIGIBLE
    assert {c.category.value for c in assessment.checks} == {
        "career_stage", "citizenship", "esi_status", "prior_funding",
    }
    assert out.missing_criteria == []
    # the citizenship check must cite the profile value, not a placeholder
    citizenship = next(c for c in assessment.checks if c.category.value == "citizenship")
    assert citizenship.profile_value == "['US']"
    assert citizenship.confidence == 0.85


def test_eligibility_missing_citizenship_needs_info():
    profile = make_profile(citizenship=[])
    out = run(EligibilityEngine().run(EligibilityInput(rfp=make_rfp(), profile=profile)))
    assert out.assessment.overall == EligibilityVerdict.NEED_MORE_INFO
    assert "citizenship" in out.missing_criteria


def test_eligibility_esi_priority_does_not_make_a_pi_ineligible():
    """"ESI-eligible PIs receive priority" is a tie-break, not an eligibility gate."""
    profile = make_profile(esi_eligible=False)
    out = run(EligibilityEngine().run(EligibilityInput(rfp=make_rfp(), profile=profile)))
    esi = next(c for c in out.assessment.checks if c.category.value == "esi_status")
    assert esi.verdict == EligibilityVerdict.ELIGIBLE
    assert "priority" in esi.reason
    assert out.assessment.overall == EligibilityVerdict.ELIGIBLE

    # Evidence must come from the ESI sentence. The pattern was bare "esi",
    # which matches "r-esi-dents", so this check used to quote the citizenship
    # requirement as the ESI requirement.
    assert esi.requirement.startswith("ESI-eligible PIs receive priority")
    assert "residents" not in esi.requirement


def test_eligibility_esi_requirement_rejects_a_non_esi_pi():
    """Negative control: the same non-ESI profile fails when ESI is required."""
    rfp = make_rfp(raw_text=(
        "EARLY STAGE INVESTIGATOR AWARD\n\n"
        "Applicants must be early career investigators.\n\n"
        "Applicants must be ESI-eligible at the time of application.\n"
    ))
    profile = make_profile(esi_eligible=False)
    out = run(EligibilityEngine().run(EligibilityInput(rfp=rfp, profile=profile)))
    esi = next(c for c in out.assessment.checks if c.category.value == "esi_status")
    assert esi.verdict == EligibilityVerdict.NOT_ELIGIBLE
    assert "requires ESI" in esi.reason
    assert out.assessment.overall == EligibilityVerdict.NOT_ELIGIBLE


def test_eligibility_senior_pi_fails_an_early_career_rfp():
    """The RFP names its stage; the profile must be measured against that.

    This was a live defect: the career-stage branch accepted ("early", "mid")
    outright, so a senior PI scored need_more_info — not eligible, and not
    ineligible either — against a programme that says "must be early career".
    """
    profile = make_profile(career_stage="senior")
    out = run(EligibilityEngine().run(EligibilityInput(rfp=make_rfp(), profile=profile)))
    career = next(c for c in out.assessment.checks if c.category.value == "career_stage")
    assert career.verdict == EligibilityVerdict.NOT_ELIGIBLE
    assert "'senior'" in career.reason and "early" in career.reason
    assert out.assessment.overall == EligibilityVerdict.NOT_ELIGIBLE

    # The recorded requirement must be the sentence a grant office can read,
    # not a fixed window that begins mid-word.
    assert career.requirement.startswith("Applicants must be early career investigators")
    assert not career.requirement.startswith("search strategy")


def test_eligibility_prior_funding_disclosure_is_not_a_bar():
    """The fixture RFP only requires disclosure; a funded PI is still eligible."""
    out = run(EligibilityEngine().run(EligibilityInput(rfp=make_rfp(), profile=make_profile())))
    funding = next(c for c in out.assessment.checks if c.category.value == "prior_funding")
    assert funding.verdict == EligibilityVerdict.ELIGIBLE
    assert "disclosure only, not exclusion" in funding.reason
    assert out.assessment.overall == EligibilityVerdict.ELIGIBLE


def test_eligibility_prior_funding_bar_rejects_a_funded_pi():
    """Negative control: the same profile fails when the RFP forbids the funding."""
    rfp = make_rfp(raw_text=(
        "CONCURRENT SUPPORT RULE\n\n"
        "Applicants must not hold concurrent funding from this program.\n"
    ))
    out = run(EligibilityEngine().run(EligibilityInput(rfp=rfp, profile=make_profile())))
    funding = next(c for c in out.assessment.checks if c.category.value == "prior_funding")
    assert funding.verdict == EligibilityVerdict.NOT_ELIGIBLE
    assert "bars" in funding.reason
    assert out.assessment.overall == EligibilityVerdict.NOT_ELIGIBLE


def test_eligibility_overlap_question_is_not_answered_by_a_grant_list():
    """Overlap is a judgement about aims; a list of award numbers cannot make it."""
    rfp = make_rfp(raw_text=(
        "OVERLAP POLICY\n\n"
        "Applications that overlap with an existing award will be returned without review.\n"
    ))
    out = run(EligibilityEngine().run(EligibilityInput(rfp=rfp, profile=make_profile())))
    funding = next(c for c in out.assessment.checks if c.category.value == "prior_funding")
    assert funding.verdict == EligibilityVerdict.NEED_MORE_INFO
    assert "cannot settle" in funding.reason


def _eligibility_for(rfp_text: str, **profile_overrides):
    out = run(EligibilityEngine().run(EligibilityInput(
        rfp=make_rfp(raw_text=rfp_text), profile=make_profile(**profile_overrides),
    )))
    return out, {c.category.value: c for c in out.assessment.checks}


def test_eligibility_matches_a_named_country():
    out, checks = _eligibility_for(
        "LOCATION\n\nOnly US institutions may apply.\n", country="US",
    )
    geo = checks["geography"]
    assert geo.verdict == EligibilityVerdict.ELIGIBLE
    assert "names us" in geo.reason.lower() or "us" in geo.reason
    assert out.assessment.overall == EligibilityVerdict.ELIGIBLE


def test_eligibility_named_country_bar_rejects_another_country():
    """Negative control: the same sentence excludes a Canadian institution."""
    out, checks = _eligibility_for(
        "LOCATION\n\nOnly US institutions may apply.\n", country="CA",
    )
    geo = checks["geography"]
    assert geo.verdict == EligibilityVerdict.NOT_ELIGIBLE
    assert "restricts eligibility to us" in geo.reason
    assert out.assessment.overall == EligibilityVerdict.NOT_ELIGIBLE


def test_eligibility_subnational_region_is_not_guessed_from_a_country():
    """"Pennsylvania institutions" cannot be settled by country="US"."""
    out, checks = _eligibility_for(
        "LOCATION\n\nEligibility is limited to Pennsylvania institutions.\n", country="US",
    )
    geo = checks["geography"]
    assert geo.verdict == EligibilityVerdict.NEED_MORE_INFO
    assert "cannot be checked against a country field" in geo.reason


def test_eligibility_geography_ignores_the_word_statement():
    """`state` used to match inside `statement`, raising a geography criterion."""
    out, checks = _eligibility_for(
        "FORMAT\n\nThe statement of work must describe the aims.\n",
    )
    assert "geography" not in checks


def test_eligibility_institution_type_is_compared_to_the_class_named():
    rfp_text = "ORGANIZATION\n\nApplicants must be a nonprofit organization.\n"
    _, matching = _eligibility_for(rfp_text, institution_type="nonprofit")
    assert matching["institution_type"].verdict == EligibilityVerdict.ELIGIBLE

    out, mismatched = _eligibility_for(rfp_text, institution_type="university")
    assert mismatched["institution_type"].verdict == EligibilityVerdict.NOT_ELIGIBLE
    assert "restricts eligibility to nonprofit" in mismatched["institution_type"].reason
    assert out.assessment.overall == EligibilityVerdict.NOT_ELIGIBLE


def test_eligibility_says_which_profile_field_is_missing():
    out, checks = _eligibility_for(
        "LOCATION\n\nOnly US institutions may apply.\n", country=None,
    )
    geo = checks["geography"]
    assert geo.verdict == EligibilityVerdict.NEED_MORE_INFO
    assert "country" in geo.reason
    assert "geography" in out.assessment.missing_info


def test_eligibility_reads_the_stage_the_rfp_asks_for():
    """Reverse control: the check must follow the RFP, not a hardcoded stage."""
    senior_rfp = make_rfp(raw_text=(
        "SENIOR INVESTIGATOR AWARD\n\n"
        "Applicants must be senior investigators with an established program.\n"
    ))
    out = run(EligibilityEngine().run(EligibilityInput(rfp=senior_rfp, profile=make_profile())))
    career = next(c for c in out.assessment.checks if c.category.value == "career_stage")
    assert career.verdict == EligibilityVerdict.NOT_ELIGIBLE
    assert "early" in career.reason and "does not match" in career.reason
    assert out.assessment.overall == EligibilityVerdict.NOT_ELIGIBLE

    senior_profile = make_profile(career_stage="senior")
    ok = run(EligibilityEngine().run(EligibilityInput(rfp=senior_rfp, profile=senior_profile)))
    career_ok = next(c for c in ok.assessment.checks if c.category.value == "career_stage")
    assert career_ok.verdict == EligibilityVerdict.ELIGIBLE


# ── drafting ─────────────────────────────────────────────────────────────────

def test_drafting_creates_proposal_and_checklist():
    rfp, profile = make_rfp(), make_profile()
    out = run(DraftingEngine().run(DraftingInput(rfp=rfp, profile=profile)))
    assert out.proposal is not None
    assert out.proposal.rfp_id == rfp.id
    assert out.proposal.pi_profile_id == profile.id
    assert out.proposal.title == rfp.title
    sections = [c.section for c in out.checklist if c.id.startswith("cl_") and c.id[3:].isdigit()]
    assert sections == rfp.sections_required
    assert {c.id for c in out.checklist} >= {"cl_budget", "cl_biosketches", "cl_letters"}
    assert out.proposal.checklist == out.checklist


def test_drafting_writes_a_section_using_the_profile():
    out = run(DraftingEngine().run(DraftingInput(
        rfp=make_rfp(), profile=make_profile(),
        proposal=make_proposal(), section_id="research_strategy", instruction="draft",
    )))
    assert out.section is not None
    assert out.section.title == "Research Strategy"
    assert out.section.word_count == len(out.section.content.split())
    assert out.section.word_count > 20
    assert "Dr. Ada Okonkwo" in out.section.content
    assert "Rensselaer Polytechnic Institute" in out.section.content
    assert "Define acronym on first use" in out.suggestions


def test_drafting_draft_is_labelled_as_a_template():
    """The generated body must not pass itself off as proposal text: it used to
    assert the work "aligns with the funder's priorities" and "demonstrates clear
    significance and innovation" -- claims nothing in this engine assessed."""
    out = run(DraftingEngine().run(DraftingInput(
        rfp=make_rfp(), profile=make_profile(), proposal=make_proposal(),
        section_id="specific_aims", instruction="draft",
    )))
    assert out.section.content.startswith("TEMPLATE:")
    assert "grantforge has not assessed" in out.section.content
    assert "aligns with the funder's priorities" not in out.section.content


def test_drafting_revise_and_expand_refuse_instead_of_returning_a_marker():
    """These returned "[Revised content for ...]" with success=True, so a bracketed
    TODO could be exported as the section body and counted as prose."""
    for instruction in ("revise", "expand"):
        out = run(DraftingEngine().run(DraftingInput(
            rfp=make_rfp(), profile=make_profile(), proposal=make_proposal(),
            section_id="specific_aims", instruction=instruction,
        )))
        assert out.success is False
        assert "text model" in out.error
        assert out.section is None


def test_drafting_condense_trims_the_existing_section():
    proposal = make_proposal()
    original = proposal.sections["specific_aims"].content
    out = run(DraftingEngine().run(DraftingInput(
        rfp=make_rfp(), profile=make_profile(), proposal=proposal,
        section_id="specific_aims", instruction="condense",
    )))
    assert out.success is True
    assert out.section.content
    assert "[" not in out.section.content
    assert len(out.section.content.split()) <= len(original.split())
    assert out.section.version == proposal.sections["specific_aims"].version + 1
    # Every kept sentence is the caller's own text, not invented prose.
    first_sentence = re.split(r"(?<=[.!?])\s+", original.strip())[0]
    assert out.section.content.startswith(first_sentence)


def test_drafting_condense_without_a_section_fails():
    out = run(DraftingEngine().run(DraftingInput(
        rfp=make_rfp(), profile=make_profile(), proposal=make_proposal(),
        section_id="not_in_proposal", instruction="condense",
    )))
    assert out.success is False
    assert "not_in_proposal" in out.error


# ── compliance ───────────────────────────────────────────────────────────────

def test_compliance_fails_without_eligibility_assessment():
    out = run(ComplianceEngine().run(ComplianceInput(
        proposal=make_proposal(), pi_profile=make_profile(),
    )))
    assert out.success is True
    assert out.overall_pass is False
    assert out.checks["eligibility"]["verdict"] == "CLARIFY"
    assert out.checks["budget"]["pass"] is True
    assert len(out.audit_entries) == 5
    assert all(e["proposal_id"] == "prop_cardiac_01" for e in out.audit_entries)
    assert [e["check_type"] for e in out.audit_entries] == [
        "eligibility", "budget", "format", "ethics", "coi",
    ]


def test_compliance_passes_with_eligibility_attached():
    proposal = make_proposal(eligibility=make_assessment(EligibilityVerdict.ELIGIBLE))
    out = run(ComplianceEngine().run(ComplianceInput(
        proposal=proposal, pi_profile=make_profile(),
    )))
    assert out.overall_pass is True
    assert out.checks["eligibility"]["verdict"] == "GO"
    assert out.checks["format"]["pass"] is True


def test_compliance_flags_a_too_short_section():
    """Negative control for the format check."""
    out = run(ComplianceEngine().run(ComplianceInput(
        proposal=make_short_section_proposal(), pi_profile=make_profile(),
        check_types=["format"],
    )))
    assert out.overall_pass is False
    assert "too short" in out.checks["format"]["details"]


def _with_section_text(proposal, text):
    """Replace a section's text so a check has something real to read."""
    section = next(iter(proposal.sections.values()))
    section.content = text
    return proposal


def test_compliance_does_not_call_an_undetermined_eligibility_verified():
    assessment = make_assessment(EligibilityVerdict.NEED_MORE_INFO)
    assessment.missing_info = ["career stage", "country"]
    out = run(ComplianceEngine().run(ComplianceInput(
        proposal=make_proposal(eligibility=assessment),
        pi_profile=make_profile(),
        check_types=["eligibility"],
    )))
    check = out.checks["eligibility"]
    assert check["pass"] is False
    assert check["verdict"] == "CLARIFY"
    assert "undetermined" in check["details"]
    assert "career stage" in check["details"] and "country" in check["details"]
    assert out.overall_pass is False


def test_compliance_ethics_flags_identifiable_data_without_echoing_it():
    proposal = make_proposal(eligibility=make_assessment(EligibilityVerdict.ELIGIBLE))
    _with_section_text(proposal, "Send data to ada@example.edu or call 555-201-8899.")
    out = run(ComplianceEngine().run(ComplianceInput(
        proposal=proposal, pi_profile=make_profile(), check_types=["ethics"],
    )))
    ethics = out.checks["ethics"]
    assert ethics["pass"] is False
    assert ethics["verdict"] == "CLARIFY"
    assert "email address" in ethics["details"]
    assert "phone number" in ethics["details"]
    # The report must not spread the data it was checking for.
    assert "ada@example.edu" not in ethics["details"]
    assert "555-201-8899" not in ethics["details"]


def test_compliance_ethics_passes_a_clean_draft_and_says_what_it_scanned():
    """Negative control for the ethics check."""
    out = run(ComplianceEngine().run(ComplianceInput(
        proposal=make_proposal(eligibility=make_assessment(EligibilityVerdict.ELIGIBLE)),
        pi_profile=make_profile(), check_types=["ethics"],
    )))
    ethics = out.checks["ethics"]
    assert ethics["pass"] is True
    assert "characters of draft text" in ethics["details"]


def test_compliance_coi_reports_absence_instead_of_claiming_a_review():
    out = run(ComplianceEngine().run(ComplianceInput(
        proposal=make_proposal(eligibility=make_assessment(EligibilityVerdict.ELIGIBLE)),
        pi_profile=make_profile(), check_types=["coi"],
    )))
    coi = out.checks["coi"]
    assert coi["pass"] is True
    assert "No conflict-of-interest statement yet" in coi["details"]


def test_compliance_coi_flags_a_disclosure_that_declares_nothing():
    proposal = make_proposal(eligibility=make_assessment(EligibilityVerdict.ELIGIBLE))
    _with_section_text(
        proposal,
        "Conflict of interest: the PI holds equity in a company that sells related sensors.",
    )
    out = run(ComplianceEngine().run(ComplianceInput(
        proposal=proposal, pi_profile=make_profile(), check_types=["coi"],
    )))
    coi = out.checks["coi"]
    assert coi["pass"] is False
    assert coi["verdict"] == "CLARIFY"
    assert "human review" in coi["details"]


def test_compliance_unknown_check_type_does_not_report_a_pass():
    out = run(ComplianceEngine().run(ComplianceInput(
        proposal=make_proposal(), pi_profile=make_profile(), check_types=["vibes"],
    )))
    assert out.checks["vibes"]["pass"] is False
    assert out.checks["vibes"]["verdict"] == "CLARIFY"
    assert "Unknown check type" in out.checks["vibes"]["details"]
    assert out.overall_pass is False


def test_compliance_audit_entry_does_not_claim_a_record_it_did_not_write(monkeypatch):
    """No sink configured: the entry must say so, not `dlv_recorded: True`."""
    monkeypatch.delenv("GRANTFORGE_AUDIT_DIR", raising=False)
    out = run(ComplianceEngine().run(ComplianceInput(
        proposal=make_proposal(eligibility=make_assessment(EligibilityVerdict.ELIGIBLE)),
        pi_profile=make_profile(), check_types=["format"],
    )))
    entry = out.audit_entries[0]
    assert entry["dlv_recorded"] is False
    assert "GRANTFORGE_AUDIT_DIR" in entry["reason"]
    # The timestamp is a reading, not a constant baked on 2026-11-03.
    assert entry["timestamp"] != "2026-11-03T00:00:00Z"
    stamped = datetime.strptime(entry["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    assert abs((datetime.now(timezone.utc) - stamped).total_seconds()) < 300
    assert len(entry["sha256"]) == 64


def test_compliance_audit_entry_lands_in_the_configured_sink(tmp_path, monkeypatch):
    """With a sink, the claim is backed by a readable line in the file."""
    monkeypatch.setenv("GRANTFORGE_AUDIT_DIR", str(tmp_path))
    out = run(ComplianceEngine().run(ComplianceInput(
        proposal=make_proposal(eligibility=make_assessment(EligibilityVerdict.ELIGIBLE)),
        pi_profile=make_profile(), check_types=["format", "ethics"],
    )))
    assert [e["dlv_recorded"] for e in out.audit_entries] == [True, True]

    path = tmp_path / "grantforge_compliance.jsonl"
    lines = [json.loads(raw) for raw in path.read_text(encoding="utf-8").splitlines()]
    assert [row["check_type"] for row in lines] == ["format", "ethics"]
    assert all(row["proposal_id"] == "prop_cardiac_01" for row in lines)

    # Each line's digest must describe its own content.
    for row, entry in zip(lines, out.audit_entries):
        core = {key: row[key] for key in ("check_type", "proposal_id", "verdict", "timestamp")}
        body = json.dumps(core, sort_keys=True, separators=(",", ":"))
        assert hashlib.sha256(body.encode("utf-8")).hexdigest() == row["sha256"] == entry["sha256"]


def test_compliance_ineligible_proposal_is_no_go():
    proposal = make_proposal(eligibility=make_assessment(EligibilityVerdict.NOT_ELIGIBLE))
    out = run(ComplianceEngine().run(ComplianceInput(
        proposal=proposal, pi_profile=make_profile(), check_types=["eligibility"],
    )))
    assert out.checks["eligibility"]["verdict"] == "NO-GO"
    assert out.overall_pass is False


# ── collaboration ────────────────────────────────────────────────────────────

def test_collaboration_edit_changes_the_section_and_bumps_its_version():
    """An operation that says version 2 must be a section that is at version 2."""
    proposal = make_proposal()
    before = proposal.sections["specific_aims"].version
    out = run(CollaborationEngine().run(CollaborationInput(
        proposal=proposal, action="edit", section_id="specific_aims",
        user_id="prof_okonkwo", content="revised sentence", position=42,
    )))
    section = out.proposal.sections["specific_aims"]
    assert section.content == "revised sentence"
    assert section.version == before + 1
    assert section.last_edited_by == "prof_okonkwo"
    assert out.operation == {
        "type": "insert",
        "section_id": "specific_aims",
        "position": 42,
        "text": "revised sentence",
        "user_id": "prof_okonkwo",
        "timestamp": out.operation["timestamp"],
        "version": before + 1,
        # No transform is implemented, and the operation says so instead of
        # letting a caller assume conflict-free co-editing.
        "transformed": False,
    }


def test_collaboration_edit_of_a_missing_section_fails():
    out = run(CollaborationEngine().run(CollaborationInput(
        proposal=make_proposal(), action="edit", section_id="no_such_section",
        user_id="prof_okonkwo", content="text",
    )))
    assert out.success is False
    assert "no_such_section" in out.error


def test_collaboration_comment_is_stored_and_assign_move_land():
    """success=True used to be the whole effect: nothing was stored or assigned."""
    engine = CollaborationEngine()
    comment = run(engine.run(CollaborationInput(
        proposal=make_proposal(), action="comment", section_id="specific_aims",
        user_id="reviewer_1", content="tighten this aim", position=12,
    )))
    assert comment.success is True and len(comment.comment_id) == 12
    stored = engine._comments[comment.comment_id]
    assert stored["section_id"] == "specific_aims"
    assert stored["text"] == "tighten this aim"
    assert stored["position"] == 12

    proposal = make_proposal()
    assigned = run(engine.run(CollaborationInput(
        proposal=proposal, action="assign", user_id="lead", target_user="writer_2",
        section_id="research_strategy",
    )))
    assert assigned.success is True
    assert [i.id for i in assigned.proposal.checklist if i.assignee == "writer_2"] == ["cl_1"]

    moving = make_proposal()
    moved = run(engine.run(CollaborationInput(
        proposal=moving, action="move", user_id="lead", section_id="cl_budget",
    )))
    assert moved.success is True
    assert moved.operation["status"] == "in_progress"
    assert next(i for i in moved.proposal.checklist if i.id == "cl_budget").status == "in_progress"


def test_collaboration_assign_and_move_of_unknown_targets_fail():
    engine = CollaborationEngine()
    assigned = run(engine.run(CollaborationInput(
        proposal=make_proposal(), action="assign", user_id="lead", target_user="writer_2",
        section_id="no_such_section",
    )))
    assert assigned.success is False and "no_such_section" in assigned.error

    moved = run(engine.run(CollaborationInput(
        proposal=make_proposal(), action="move", user_id="lead", section_id="cl_nope",
    )))
    assert moved.success is False and "cl_nope" in moved.error


def test_collaboration_request_is_remembered():
    engine = CollaborationEngine()
    out = run(engine.run(CollaborationInput(
        proposal=make_proposal(), action="request", user_id="pi",
        target_user="statistician", section_id="research_strategy",
        content="What power calculation justifies n=40?",
    )))
    assert out.request_id in engine._pending_requests
    stored = engine._pending_requests[out.request_id]
    assert stored["question"] == "What power calculation justifies n=40?"
    assert stored["to"] == "statistician"
    assert stored["status"] == "pending"


def test_collaboration_unknown_action_fails():
    out = run(CollaborationEngine().run(CollaborationInput(
        proposal=make_proposal(), action="teleport", user_id="pi",
    )))
    assert out.success is False
    assert out.error == "Unknown action: teleport"


# ── export ───────────────────────────────────────────────────────────────────

def _zip_names(payload: bytes) -> list[str]:
    with zipfile.ZipFile(BytesIO(payload)) as zf:
        return zf.namelist()


def _zip_text(payload: bytes) -> str:
    """All parts concatenated: shared strings (openpyxl/docx) or inline text (fallback)."""
    with zipfile.ZipFile(BytesIO(payload)) as zf:
        return "".join(zf.read(n).decode("utf-8", "replace") for n in zf.namelist())


def _assert_word_package(payload: bytes, title: str) -> None:
    assert payload.startswith(b"PK\x03\x04")
    names = _zip_names(payload)
    assert "[Content_Types].xml" in names and "_rels/.rels" in names
    assert "word/document.xml" in names
    assert title in _zip_text(payload)


def _assert_excel_package(payload: bytes) -> None:
    assert payload.startswith(b"PK\x03\x04")
    names = _zip_names(payload)
    assert "[Content_Types].xml" in names and "_rels/.rels" in names
    assert "xl/workbook.xml" in names
    assert any(n.startswith("xl/worksheets/") for n in names)
    text = _zip_text(payload)
    assert "Personnel" in text and "Indirect Costs" in text


def _assert_pdf_carries_text(payload: bytes, title: str, section_title: str) -> None:
    """A PDF that opens is not a PDF that says anything.

    The fallback used to emit a catalog, one page object and no content stream: a
    valid file with zero words, exported as the proposal. Assert the page has
    contents and that a reader can extract the title and a section heading.
    """
    assert payload.startswith(b"%PDF-1.4")
    assert b"/Type /Page " in payload
    assert b"/Contents" in payload and b"stream" in payload
    assert b"startxref" in payload

    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(BytesIO(payload))
    assert len(reader.pages) >= 1
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert title in text, text[:200]
    assert section_title in text, text[:200]


def test_export_budget_does_not_report_zero_dollars_as_an_amount():
    """An unfilled budget is blank, and says so, instead of claiming $0.

    Runs on both interpreters: with openpyxl the cells are read back, without it
    the SpreadsheetML the fallback writes is inspected.
    """
    rfp = make_rfp(max_amount=450000.0)
    out = run(ExportEngine().run(ExportInput(
        proposal=make_proposal(), pi_profile=make_profile(), rfp=rfp,
    )))
    workbook = out.files["prop_cardiac_01_budget.xlsx"]

    try:
        from openpyxl import load_workbook
    except ImportError:
        sheet = _zip_text(workbook)
        assert "<v>0</v>" not in sheet
        assert 'r="B7"' in sheet
        assert '<c r="B7"/>' in sheet or '<c r="B7" />' in sheet
        return

    ws = load_workbook(BytesIO(workbook))["Budget"]
    assert ws["B7"].value is None
    assert ws["B12"].value is None
    texts = [str(c.value) for row in ws.iter_rows() for c in row if isinstance(c.value, str)]
    assert any("does not generate budget figures" in t for t in texts)
    assert any("Award ceiling stated in the RFP: $450,000" in t for t in texts)


def test_export_writes_three_real_files():
    rfp, profile, proposal = make_rfp(), make_profile(), make_proposal()
    title = proposal.title
    out = run(ExportEngine().run(ExportInput(proposal=proposal, pi_profile=profile, rfp=rfp)))
    assert set(out.files) == {
        "prop_cardiac_01_proposal.pdf",
        "prop_cardiac_01_proposal.docx",
        "prop_cardiac_01_budget.xlsx",
    }
    assert out.files["prop_cardiac_01_proposal.pdf"].startswith(b"%PDF")
    _assert_word_package(out.files["prop_cardiac_01_proposal.docx"], title)
    _assert_excel_package(out.files["prop_cardiac_01_budget.xlsx"])

    assert out.bundle.proposal_id == proposal.id
    assert out.bundle.formats == [ExportFormat.PDF, ExportFormat.WORD, ExportFormat.EXCEL]
    assert out.bundle.manifest["pi"] == "Dr. Ada Okonkwo"
    assert out.bundle.manifest["funder"] == "nsf"
    assert out.bundle.manifest["deadline"].startswith("2027-03-01")


def test_export_manifest_does_not_advertise_a_page_count_it_never_took():
    """The manifest carried "page_counts": {} with a TODO: compute.

    Nothing rendered and read back a page count, so an empty dict was a
    measurement-shaped hole -- a caller checking a page limit reads it as zero
    pages. The key is gone; the manifest lists the formats and files it produced.
    """
    out = run(ExportEngine().run(ExportInput(
        proposal=make_proposal(), pi_profile=make_profile(), rfp=make_rfp(),
    )))
    assert "page_counts" not in out.bundle.manifest
    assert out.bundle.manifest["formats"] == ["pdf", "docx", "xlsx"]
    assert out.bundle.manifest["files"] == sorted(out.files)


def test_export_fallback_produces_valid_office_packages(monkeypatch):
    """Force the no-dependency fallback (the shipped path on 3.15t) and check the
    artefacts are real packages, not CSV bytes or a bare XML file in a ZIP.

    The renderers are imported once at module level now, so the fallback is
    selected by the module attribute being None -- blocking builtins.__import__
    would only hit re-imports inside already-imported libraries.
    """
    from grantforge import export as export_module

    for name in ("Document", "Workbook", "Font", "SimpleDocTemplate"):
        monkeypatch.setattr(export_module, name, None)
    proposal = make_proposal()
    out = run(ExportEngine().run(ExportInput(
        proposal=proposal, pi_profile=make_profile(), rfp=make_rfp(),
    )))
    assert list(out.files) == [
        "prop_cardiac_01_proposal.pdf",
        "prop_cardiac_01_proposal.docx",
        "prop_cardiac_01_budget.xlsx",
    ]
    section_title = next(iter(proposal.sections.values())).title
    _assert_pdf_carries_text(
        out.files["prop_cardiac_01_proposal.pdf"], proposal.title, section_title
    )
    _assert_word_package(out.files["prop_cardiac_01_proposal.docx"], proposal.title)
    _assert_excel_package(out.files["prop_cardiac_01_budget.xlsx"])


def test_export_pdf_fallback_paginates_a_longer_proposal(monkeypatch):
    """More text than one page holds must produce more than one page object."""
    monkeypatch.setattr(export_module, "SimpleDocTemplate", None)
    proposal = make_proposal()
    for section in proposal.sections.values():
        section.content = " ".join([section.content] * 40)
    out = run(ExportEngine().run(ExportInput(
        proposal=proposal, pi_profile=make_profile(), rfp=make_rfp(),
        formats=[ExportFormat.PDF],
    )))
    payload = out.files["prop_cardiac_01_proposal.pdf"]
    pypdf = pytest.importorskip("pypdf")
    assert len(pypdf.PdfReader(BytesIO(payload)).pages) > 1


def test_export_single_format_only():
    out = run(ExportEngine().run(ExportInput(
        proposal=make_proposal(), pi_profile=make_profile(), rfp=make_rfp(),
        formats=[ExportFormat.WORD],
    )))
    assert list(out.files) == ["prop_cardiac_01_proposal.docx"]
    assert out.bundle.formats == [ExportFormat.WORD]


# ── engine contract ──────────────────────────────────────────────────────────

class _Rejecting(Engine[EngineInput, EngineOutput]):
    name = "rejecting"

    async def validate_input(self, input: EngineInput) -> bool:
        return False

    async def execute(self, input: EngineInput) -> EngineOutput:  # pragma: no cover
        raise AssertionError("execute must not run when validation rejects")


class _Accepting(_Rejecting):
    name = "accepting"
    executed = False

    async def validate_input(self, input: EngineInput) -> bool:
        return True

    async def execute(self, input: EngineInput) -> EngineOutput:
        self.executed = True
        return EngineOutput(success=True)


def test_run_enforces_the_validation_gate():
    try:
        run(_Rejecting().run(EngineInput()))
    except ValueError as exc:
        assert "rejecting: input rejected by validate_input" in str(exc)
    else:
        raise AssertionError("run() executed despite validate_input returning False")


def test_run_executes_when_validation_passes():
    engine = _Accepting()
    out = run(engine.run(EngineInput()))
    assert engine.executed is True and out.success is True


# ── full pipeline ────────────────────────────────────────────────────────────

def test_pipeline_runs_all_five_phases():
    result = run(GrantPipeline().run_full_pipeline(rfp_text=RFP_TEXT, profile=make_profile()))
    assert result["success"] is True, result.get("error")
    assert set(result["results"]) == {"discovery", "eligibility", "drafting", "compliance", "export"}

    proposal = result["proposal"]
    assert proposal.rfp_id
    assert proposal.eligibility is not None
    assert proposal.eligibility.overall == EligibilityVerdict.ELIGIBLE

    export = result["results"]["export"]
    assert len(export.files) == 3
    assert result["results"]["compliance"].overall_pass is True


def test_pipeline_stops_before_drafting_an_ineligible_application():
    """Writing a proposal the funder rejects is work with no outcome.

    The pipeline used to draft, review and export anyway and return
    success=True for a not_eligible applicant.
    """
    result = run(GrantPipeline().run_full_pipeline(
        rfp_text=RFP_TEXT,
        profile=make_profile(career_stage="senior"),
    ))
    assert result["success"] is False
    assert "not eligible" in result["error"]
    assert "career_stage" in result["error"]
    assert "drafting" not in result["results"]
    assert "export" not in result["results"]
    # The verdict must survive the refusal: the caller needs the reason.
    assert result["eligibility"].overall == EligibilityVerdict.NOT_ELIGIBLE


def test_pipeline_does_not_report_success_for_a_run_that_exported_nothing():
    """success=True for an empty bundle is the lie the pipeline used to tell; the
    phase results still come back so the caller can see what did happen."""
    result = run(GrantPipeline().run_full_pipeline(
        rfp_text=RFP_TEXT,
        profile=make_profile(),
        export_formats=[],
    ))
    assert result["success"] is False
    assert "produced no files" in result["error"]
    assert result["proposal"] is not None
    assert set(result["results"]) == {"discovery", "eligibility", "drafting", "compliance", "export"}
    assert result["results"]["export"].files == {}


def test_pipeline_does_not_report_success_when_review_fails(monkeypatch):
    """A failing compliance review is a failed run, not a run with a note."""
    pipeline = GrantPipeline()

    async def failing_review(_input):
        out = await original(_input)
        out.overall_pass = False
        out.checks = dict(out.checks, format={"pass": False, "details": "too short", "verdict": "CLARIFY"})
        return out

    original = pipeline.compliance.run
    monkeypatch.setattr(pipeline.compliance, "run", failing_review)
    result = run(pipeline.run_full_pipeline(rfp_text=RFP_TEXT, profile=make_profile()))
    assert result["success"] is False
    assert "review failed" in result["error"] and "format" in result["error"]
    # The artefacts are still produced; the verdict is what changed.
    assert len(result["results"]["export"].files) == 3


def test_pipeline_can_proceed_when_ineligibility_is_overridden():
    """The gate is a default, not a lock: the override still runs every phase.

    It does not turn the outcome into a success -- the review checks the same
    verdict and fails, so success is False with eligibility named, while the
    artefacts are produced.
    """
    result = run(GrantPipeline().run_full_pipeline(
        rfp_text=RFP_TEXT,
        profile=make_profile(career_stage="senior"),
        allow_ineligible=True,
    ))
    assert "drafting" in result["results"]
    assert len(result["results"]["export"].files) == 3
    assert result["results"]["eligibility"].assessment.overall == EligibilityVerdict.NOT_ELIGIBLE
    assert result["success"] is False
    assert "eligibility" in result["error"]


# ── entry point ──────────────────────────────────────────────

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _cli(*args: str) -> subprocess.CompletedProcess:
    """Invoke the real entry point, not the command function.

    A subprocess is the point: the typer/click incompatibility that made
    `python -m grantforge --help` die with `Parameter.make_metavar() missing 1
    required positional argument: 'ctx'` lived in the framework wiring, so
    calling ``discover()`` in-process would have missed it entirely.
    """
    env = {
        **os.environ,
        "PYTHONPATH": os.path.join(_REPO_ROOT, "src"),
        "PYTHONIOENCODING": "utf-8",
        "NO_COLOR": "1",
        "COLUMNS": "120",
    }
    return subprocess.run(
        [sys.executable, "-m", "grantforge", *args],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def test_cli_help_lists_the_commands():
    proc = _cli("--help")
    assert proc.returncode == 0, proc.stderr
    assert "discover" in proc.stdout
    assert "assess" in proc.stdout
    assert "review" in proc.stdout
    assert "export" in proc.stdout

    # Negative control: the same harness must see a non-zero exit when the
    # command does not exist, otherwise the assertion above proves nothing.
    bad = _cli("no-such-command")
    assert bad.returncode != 0
    assert "No such command" in (bad.stdout + bad.stderr)


def test_cli_discover_writes_real_results(tmp_path):
    out = tmp_path / "discovery.json"
    proc = _cli("discover", "cardiac sensing", "--top", "3", "-o", str(out))
    assert proc.returncode == 0, proc.stderr
    assert out.exists()

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["success"] is True
    assert [f["id"] for f in payload["opportunities"]] == ["nih", "nsf"]
    assert payload["metadata"]["mode"] == "keyword_search"
    assert payload["metadata"]["keywords"] == ["cardiac", "sensing"]
    assert payload["metadata"]["corpus_size"] == 5
