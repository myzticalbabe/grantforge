"""
Discovery Engine — Semantic funding search + RFP ingestion + Funder intelligence + Auto-profiles
"""

from __future__ import annotations
from typing import Any

from grantforge.engine import Engine, EngineInput, EngineOutput
from grantforge.schemas import (
    Funder,
    RFP,
    Profile,
    EligibilityAssessment,
    CriterionCheck,
    EligibilityVerdict,
    CriterionCategory,
    FunderType,
    GrantMechanism,
)


class DiscoveryInput(EngineInput):
    query: str | None = None
    rfp_text: str | None = None
    rfp_url: str | None = None
    funder_ein: str | None = None
    profile: Profile | None = None
    top_k: int = 10
    use_npu: bool = True


class DiscoveryOutput(EngineOutput):
    opportunities: list[Funder] = []
    rfp: RFP | None = None
    funder_intel: Funder | None = None
    profile: Profile | None = None
    eligibility: EligibilityAssessment | None = None


class DiscoveryEngine(Engine[DiscoveryInput, DiscoveryOutput]):
    """Semantic discovery engine using mxbai-embed-large-v1 on NPU via ov_embed_server."""

    name = "discovery"
    version = "2.0.0"

    def __init__(self):
        super().__init__()
        self._ov_embed_url = "http://127.0.0.1:18083/v1/embeddings"
        self._initialized = False

    async def _ensure_initialized(self):
        if self._initialized:
            return
        # TODO: Verify ov_embed_server is running on NPU
        # TODO: Initialize marker for PDF parsing
        # TODO: Initialize BM25 index for hybrid search
        self._initialized = True

    async def execute(self, input: DiscoveryInput) -> DiscoveryOutput:
        await self._ensure_initialized()

        if input.rfp_text or input.rfp_url:
            return await self._ingest_rfp(input)
        elif input.query:
            return await self._search_opportunities(input)
        elif input.funder_ein:
            return await self._get_funder_intel(input)
        elif input.profile:
            return await self._build_profile(input)
        else:
            return DiscoveryOutput(success=False, error="No valid input provided")

    async def _search_opportunities(self, input: DiscoveryInput) -> DiscoveryOutput:
        """Semantic search: embed query → hybrid BM25+vector → rerank."""
        # TODO: Embed query via ov_embed_server
        # TODO: Hybrid search (BM25 + vector cosine)
        # TODO: Cross-encoder rerank
        # TODO: Return top_k funders with fit scores
        return DiscoveryOutput(
            success=True,
            opportunities=[],
            metadata={"query": input.query, "mode": "semantic_search"}
        )

    async def _ingest_rfp(self, input: DiscoveryInput) -> DiscoveryOutput:
        """Parse RFP (PDF/URL/text) → extract criteria, deadlines, sections."""
        # TODO: marker for PDF → Markdown
        # TODO: Extract: deadline, mechanism, page_limit, required_sections
        # TODO: Build RFP schema object
        return DiscoveryOutput(
            success=True,
            rfp=RFP(
                id="rfp_001",
                funder_id="nih",
                title="Sample RFP",
                deadline="2026-12-01T23:59:59",
                raw_text=input.rfp_text or "",
            ),
            metadata={"mode": "rfp_ingest"}
        )

    async def _get_funder_intel(self, input: DiscoveryInput) -> DiscoveryOutput:
        """Parse 990 filings → giving patterns, priorities, contact info."""
        # TODO: Fetch 990 via ProPublica/IRS API
        # TODO: Parse: total_giving, avg_grant, focus_areas, geographic_preference
        return DiscoveryOutput(
            success=True,
            funder_intel=Funder(
                id=input.funder_ein or "unknown",
                name="Unknown Funder",
                type=FunderType.FEDERAL,
            ),
            metadata={"mode": "funder_intel", "ein": input.funder_ein}
        )

    async def _build_profile(self, input: DiscoveryInput) -> DiscoveryOutput:
        """Auto-generate profile from publications (ORCID, Semantic Scholar) + DirectMemory."""
        # TODO: Fetch publications via ORCID/Semantic Scholar
        # TODO: Extract research areas, co-authors, funding history
        # TODO: Store in DirectMemory for reuse
        profile = input.profile or Profile(
            id="auto_001",
            name="Auto-generated",
            institution="Unknown",
            career_stage="early",
        )
        return DiscoveryOutput(
            success=True,
            profile=profile,
            metadata={"mode": "profile_build"}
        )

    async def health_check(self) -> dict[str, Any]:
        base = await super().health_check()
        # TODO: Check ov_embed_server connectivity
        base["ov_embed_server"] = "unknown"
        base["marker"] = "unknown"
        return base