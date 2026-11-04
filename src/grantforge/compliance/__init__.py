"""
Compliance Engine — supervisor_verdict fanout + DLV dual-ledger audit trail for every decision
"""

from __future__ import annotations
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from grantforge.engine import Engine, EngineInput, EngineOutput
from grantforge.schemas import EligibilityVerdict, Proposal, Profile

# Where compliance decisions are appended as JSONL. Unset means nothing is
# persisted, and the audit entry below must say so rather than claim a record.
AUDIT_ENV = "GRANTFORGE_AUDIT_DIR"
AUDIT_FILENAME = "grantforge_compliance.jsonl"


class ComplianceInput(EngineInput):
    proposal: Proposal
    pi_profile: Profile
    check_types: list[str] = ["eligibility", "budget", "format", "ethics", "coi"]


class ComplianceOutput(EngineOutput):
    checks: dict[str, Any] = {}
    audit_entries: list[dict[str, Any]] = []
    overall_pass: bool = True


class ComplianceEngine(Engine[ComplianceInput, ComplianceOutput]):
    """Compliance engine: runs all checks via supervisor_verdict fanout, records to DLV."""

    name = "compliance"
    version = "2.0.0"

    async def execute(self, input: ComplianceInput) -> ComplianceOutput:
        checks = {}
        audit = []
        overall = True

        for check_type in input.check_types:
            # TODO: Call supervisor_verdict fanout for each check
            # supervisor_verdict runs: PMB + Engram + PAMS in parallel
            # Returns: {check_type: {pass: bool, details: {...}, verdict: GO/CLARIFY/NO-GO}}
            
            check_result = await self._run_check(check_type, input)
            checks[check_type] = check_result
            
            # Record to DLV dual-ledger (DirectMemory + .audit/ JSONL)
            audit_entry = await self._record_audit(check_type, check_result, input)
            audit.append(audit_entry)
            
            if not check_result.get("pass", False):
                overall = False

        return ComplianceOutput(
            success=True,
            checks=checks,
            audit_entries=audit,
            overall_pass=overall,
        )

    async def _run_check(self, check_type: str, input: ComplianceInput) -> dict[str, Any]:
        """Run a single compliance check."""
        proposal = input.proposal
        profile = input.pi_profile

        if check_type == "eligibility":
            # Check if proposal has eligibility assessment
            if proposal.eligibility is None:
                return {"pass": False, "details": "No eligibility assessment attached", "verdict": "CLARIFY"}
            overall = proposal.eligibility.overall
            if overall == EligibilityVerdict.NOT_ELIGIBLE:
                return {"pass": False, "details": "Proposal not eligible", "verdict": "NO-GO"}
            if overall == EligibilityVerdict.NEED_MORE_INFO:
                # "Undetermined" used to be reported as "verified": the check
                # only looked for not_eligible.
                missing = ", ".join(proposal.eligibility.missing_info) or "criteria the assessment did not settle"
                return {
                    "pass": False,
                    "details": f"Eligibility undetermined — missing {missing}",
                    "verdict": "CLARIFY",
                }
            return {"pass": True, "details": "Eligibility verified", "verdict": "GO"}

        if check_type == "budget":
            # Check if proposal has budget-related sections
            has_budget = any("budget" in s.title.lower() for s in proposal.sections.values())
            if not has_budget:
                return {"pass": True, "details": "No budget section yet (optional at draft stage)", "verdict": "GO"}
            return {"pass": True, "details": "Budget section present", "verdict": "GO"}

        if check_type == "format":
            # Check formatting rules from RFP
            if not proposal.sections:
                # An empty proposal used to pass this check because the loop below
                # had nothing to iterate over: the review reported GO for a
                # document it never examined, and the pipeline exported it.
                return {
                    "pass": False,
                    "details": "Proposal has no sections — nothing was drafted to review",
                    "verdict": "CLARIFY",
                }
            issues = []
            for section in proposal.sections.values():
                if section.word_count > 0 and section.word_count < 50:
                    issues.append(f"Section '{section.title}' may be too short")
            if issues:
                return {"pass": False, "details": "; ".join(issues), "verdict": "CLARIFY"}
            return {"pass": True, "details": "Formatting checks passed", "verdict": "GO"}

        if check_type == "ethics":
            return self._check_identifiable_data(proposal)

        if check_type == "coi":
            return self._check_conflict_disclosure(proposal)

        # An unknown check cannot report a pass: previously it did, with the
        # detail "check completed", which was a GO from a box nobody opened.
        return {
            "pass": False,
            "details": f"Unknown check type '{check_type}' — nothing was performed",
            "verdict": "CLARIFY",
        }

    # Identifiable-data patterns. The detail names the KIND of match, never the
    # matched value: a compliance report that echoes an SSN into a log has spread
    # the data it was checking for.
    _PII_PATTERNS = (
        ("email address", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
        ("US social security number", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
        ("phone number", re.compile(r"\b\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b")),
    )

    _CONFLICT_STATEMENTS = (
        "no conflicts",
        "no conflict of interest",
        "no competing interest",
        "nothing to disclose",
    )

    def _proposal_text(self, proposal: Proposal) -> str:
        parts = [
            section.content
            for section in proposal.sections.values()
            if getattr(section, "content", None)
        ]
        return "\n".join(parts)

    def _check_identifiable_data(self, proposal: Proposal) -> dict[str, Any]:
        """Scan the draft for identifiable data instead of asserting a review."""
        text = self._proposal_text(proposal)
        findings = [
            kind for kind, pattern in self._PII_PATTERNS if pattern.search(text)
        ]
        if not findings:
            return {
                "pass": True,
                "details": f"No identifiable data found in {len(text)} characters of draft text",
                "verdict": "GO",
            }
        return {
            "pass": False,
            "details": (
                "Draft text contains " + ", ".join(sorted(set(findings)))
                + " — remove, or confirm the funder expects it"
            ),
            "verdict": "CLARIFY",
        }

    def _check_conflict_disclosure(self, proposal: Proposal) -> dict[str, Any]:
        """Look for the COI statement; absence is normal at draft stage."""
        text = self._proposal_text(proposal).lower()
        has_section = any("conflict" in s.title.lower() or "coi" in s.title.lower()
                          for s in proposal.sections.values())
        if not has_section and "conflict of interest" not in text:
            return {
                "pass": True,
                "details": "No conflict-of-interest statement yet (optional at draft stage)",
                "verdict": "GO",
            }
        if any(phrase in text for phrase in self._CONFLICT_STATEMENTS):
            return {"pass": True, "details": "COI statement declares no conflicts", "verdict": "GO"}
        return {
            "pass": False,
            "details": (
                "COI statement present but does not declare a position — reads as a "
                "disclosure that needs human review"
            ),
            "verdict": "CLARIFY",
        }

    async def _record_audit(self, check_type: str, result: dict, input: ComplianceInput) -> dict[str, Any]:
        """Record one compliance decision, and only claim it when it landed.

        This used to return ``dlv_recorded: True`` with a fixed timestamp while
        writing nothing — an audit trail that reported itself into existence.
        A sink is opt-in via ``GRANTFORGE_AUDIT_DIR``; with no sink, or a failed
        write, the entry says False and why.
        """
        entry: dict[str, Any] = {
            "check_type": check_type,
            "proposal_id": input.proposal.id,
            "verdict": result.get("verdict"),
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        body = json.dumps(entry, sort_keys=True, separators=(",", ":"))
        entry["sha256"] = hashlib.sha256(body.encode("utf-8")).hexdigest()

        sink = os.environ.get(AUDIT_ENV, "").strip()
        if not sink:
            entry["dlv_recorded"] = False
            entry["reason"] = f"no audit sink configured; set {AUDIT_ENV} to a directory to persist decisions"
            return entry

        path = Path(sink) / AUDIT_FILENAME
        line = json.dumps(entry, sort_keys=True)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            # A write that cannot be read back did not land.
            with path.open("r", encoding="utf-8") as fh:
                last = fh.read().strip().splitlines()[-1]
        except (OSError, IndexError) as exc:
            entry["dlv_recorded"] = False
            entry["reason"] = f"audit write failed: {exc}"
            return entry

        if last != line:
            entry["dlv_recorded"] = False
            entry["reason"] = "audit write could not be read back"
            return entry

        entry["dlv_recorded"] = True
        entry["audit_path"] = str(path)
        return entry

    async def health_check(self) -> dict[str, Any]:
        base = await super().health_check()
        # TODO: Check supervisor_verdict connectivity
        base["supervisor_verdict"] = "unknown"
        base["dlv"] = "unknown"
        return base