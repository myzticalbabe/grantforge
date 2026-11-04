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
import json
import os
import subprocess
import sys
import zipfile
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
    assert rfp.deadline.date().isoformat() == "2027-03-01"
    assert rfp.page_limit == 12
    assert rfp.mechanism == GrantMechanism.R01
    assert rfp.max_amount == 450000.0
    assert rfp.sections_required == ["Specific Aims", "Research Strategy", "Budget Justification"]
    assert out.metadata["mode"] == "rfp_ingest"


def test_discovery_searches_opportunities():
    out = run(DiscoveryEngine().run(DiscoveryInput(query="low power cardiac sensing", top_k=3)))
    assert out.success is True
    assert len(out.opportunities) == 3
    assert [f.id for f in out.opportunities] == ["nih", "nsf", "doe"]
    assert out.metadata["keywords"] == ["low", "power", "cardiac", "sensing"]


def test_discovery_funder_intel_by_ein():
    out = run(DiscoveryEngine().run(DiscoveryInput(funder_ein="53-0196605")))
    assert out.funder_intel is not None
    assert out.funder_intel.name == "National Institutes of Health" or out.funder_intel.type == FunderType.FEDERAL
    assert out.funder_intel.ein == "53-0196605"
    assert out.metadata["mode"] == "funder_intel"


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


def test_drafting_revise_instruction_changes_the_body():
    out = run(DraftingEngine().run(DraftingInput(
        rfp=make_rfp(), profile=make_profile(), proposal=make_proposal(),
        section_id="specific_aims", instruction="revise",
    )))
    assert out.section.content.startswith("[Revised content for specific_aims")


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


def test_compliance_ineligible_proposal_is_no_go():
    proposal = make_proposal(eligibility=make_assessment(EligibilityVerdict.NOT_ELIGIBLE))
    out = run(ComplianceEngine().run(ComplianceInput(
        proposal=proposal, pi_profile=make_profile(), check_types=["eligibility"],
    )))
    assert out.checks["eligibility"]["verdict"] == "NO-GO"
    assert out.overall_pass is False


# ── collaboration ────────────────────────────────────────────────────────────

def test_collaboration_edit_produces_an_operation():
    out = run(CollaborationEngine().run(CollaborationInput(
        proposal=make_proposal(), action="edit", section_id="specific_aims",
        user_id="prof_okonkwo", content="revised sentence", position=42,
    )))
    assert out.operation == {
        "type": "insert",
        "section_id": "specific_aims",
        "position": 42,
        "text": "revised sentence",
        "user_id": "prof_okonkwo",
        "timestamp": out.operation["timestamp"],
        "version": 1,
    }


def test_collaboration_comment_assign_move():
    engine = CollaborationEngine()
    comment = run(engine.run(CollaborationInput(
        proposal=make_proposal(), action="comment", section_id="specific_aims",
        user_id="reviewer_1", content="tighten this aim",
    )))
    assert comment.success is True and len(comment.comment_id) == 12

    assigned = run(engine.run(CollaborationInput(
        proposal=make_proposal(), action="assign", user_id="lead", target_user="writer_2",
        section_id="research_strategy",
    )))
    assert assigned.success is True

    moved = run(engine.run(CollaborationInput(
        proposal=make_proposal(), action="move", user_id="lead", section_id="cl_1",
    )))
    assert moved.success is True


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


def test_export_fallback_produces_valid_office_packages(monkeypatch):
    """Force the no-dependency fallback (the shipped path on 3.15t) and check the
    artefacts are real packages, not CSV bytes or a bare XML file in a ZIP."""
    import builtins

    real_import = builtins.__import__

    def deny(name, *args, **kwargs):
        if name.split(".")[0] in {"openpyxl", "docx", "reportlab"}:
            raise ImportError(f"blocked for test: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", deny)
    proposal = make_proposal()
    out = run(ExportEngine().run(ExportInput(
        proposal=proposal, pi_profile=make_profile(), rfp=make_rfp(),
    )))
    assert list(out.files) == [
        "prop_cardiac_01_proposal.pdf",
        "prop_cardiac_01_proposal.docx",
        "prop_cardiac_01_budget.xlsx",
    ]
    assert out.files["prop_cardiac_01_proposal.pdf"].startswith(b"%PDF")
    _assert_word_package(out.files["prop_cardiac_01_proposal.docx"], proposal.title)
    _assert_excel_package(out.files["prop_cardiac_01_budget.xlsx"])


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


def test_pipeline_can_proceed_when_ineligibility_is_overridden():
    """The gate is a default, not a lock: an explicit override still runs."""
    result = run(GrantPipeline().run_full_pipeline(
        rfp_text=RFP_TEXT,
        profile=make_profile(career_stage="senior"),
        allow_ineligible=True,
    ))
    assert result["success"] is True, result.get("error")
    assert "drafting" in result["results"]
    assert result["results"]["eligibility"].assessment.overall == EligibilityVerdict.NOT_ELIGIBLE


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
    proc = _cli("discover", "low power cardiac sensing", "--top", "3", "-o", str(out))
    assert proc.returncode == 0, proc.stderr
    assert out.exists()

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["success"] is True
    assert [f["id"] for f in payload["opportunities"]] == ["nih", "nsf", "doe"]
    assert payload["metadata"]["mode"] == "keyword_search"
    assert payload["metadata"]["keywords"] == ["low", "power", "cardiac", "sensing"]
