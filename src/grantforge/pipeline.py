"""
grantforge pipeline — end-to-end workflow orchestration.
Chains: discover → assess → draft → review → export
"""
from __future__ import annotations
from typing import Any

from grantforge.discovery import DiscoveryEngine, DiscoveryInput
from grantforge.eligibility import EligibilityEngine, EligibilityInput
from grantforge.drafting import DraftingEngine, DraftingInput
from grantforge.compliance import ComplianceEngine, ComplianceInput
from grantforge.export import ExportEngine, ExportInput
from grantforge.schemas import Profile, RFP, Proposal, ExportFormat, EligibilityVerdict


class GrantPipeline:
    """End-to-end grant proposal pipeline."""

    def __init__(self):
        self.discovery = DiscoveryEngine()
        self.eligibility = EligibilityEngine()
        self.drafting = DraftingEngine()
        self.compliance = ComplianceEngine()
        self.export = ExportEngine()

    async def run_full_pipeline(
        self,
        query: str = "",
        rfp_text: str = "",
        profile: Profile | None = None,
        funder_ein: str | None = None,
        export_formats: list[ExportFormat] | None = None,
        allow_ineligible: bool = False,
    ) -> dict[str, Any]:
        """Run the full pipeline: discover → assess → draft → review → export.

        A ``not_eligible`` verdict stops the run before drafting. Writing and
        exporting a proposal the funder will not accept is work with no outcome,
        and the previous behaviour returned ``success: True`` for it. Pass
        ``allow_ineligible=True`` to continue anyway (the verdict stays recorded).
        """
        results: dict[str, Any] = {}

        # Phase 1: Discovery
        disc_input = DiscoveryInput(
            query=query,
            rfp_text=rfp_text,
            funder_ein=funder_ein,
            profile=profile,
        )
        disc_result = await self.discovery.run(disc_input)
        results["discovery"] = disc_result

        rfp = disc_result.rfp
        if rfp is None and rfp_text:
            # Use the input text as RFP
            # No deadline is passed: this path has no parsed RFP to take one from,
            # and inventing "in 90 days" put a fabricated date in the export.
            rfp = RFP(
                funder_id="unknown",
                title="User RFP",
                raw_text=rfp_text,
            )
            results["discovery"].rfp = rfp

        if profile is None:
            profile = disc_result.profile

        if rfp is None or profile is None:
            return {"success": False, "error": "Could not obtain RFP or profile", "results": results}

        # Phase 2: Eligibility
        elig_input = EligibilityInput(rfp=rfp, profile=profile)
        elig_result = await self.eligibility.run(elig_input)
        results["eligibility"] = elig_result

        assessment = elig_result.assessment
        if (
            assessment is not None
            and assessment.overall == EligibilityVerdict.NOT_ELIGIBLE
            and not allow_ineligible
        ):
            failed = [
                c.category.value
                for c in assessment.checks
                if c.verdict == EligibilityVerdict.NOT_ELIGIBLE
            ]
            return {
                "success": False,
                "error": "Applicant is not eligible for this RFP: " + ", ".join(failed),
                "eligibility": assessment,
                "results": results,
            }

        # Phase 3: Drafting (create proposal)
        draft_input = DraftingInput(rfp=rfp, profile=profile)
        draft_result = await self.drafting.run(draft_input)
        results["drafting"] = draft_result

        proposal = draft_result.proposal
        if proposal is None:
            return {"success": False, "error": "Could not create proposal", "results": results}

        # Attach eligibility assessment to proposal
        if elig_result.assessment is not None:
            proposal.eligibility = elig_result.assessment

        # Phase 4: Compliance review
        comp_input = ComplianceInput(proposal=proposal, pi_profile=profile)
        comp_result = await self.compliance.run(comp_input)
        results["compliance"] = comp_result

        # Phase 5: Export
        if export_formats is None:
            export_formats = [ExportFormat.PDF, ExportFormat.WORD, ExportFormat.EXCEL]
        export_input = ExportInput(
            proposal=proposal,
            pi_profile=profile,
            rfp=rfp,
            formats=export_formats,
        )
        export_result = await self.export.run(export_input)
        results["export"] = export_result

        return {
            "success": True,
            "proposal": proposal,
            "results": results,
        }

    async def health_check_all(self) -> dict[str, Any]:
        """Check health of all engines."""
        return {
            "discovery": await self.discovery.health_check(),
            "eligibility": await self.eligibility.health_check(),
            "drafting": await self.drafting.health_check(),
            "compliance": await self.compliance.health_check(),
            "export": await self.export.health_check(),
        }