"""
Drafting Engine — Checklist-driven section drafting + Content library + Style guide + Inline AI + Voice learning
"""

from __future__ import annotations
from typing import Any

from grantforge.engine import Engine, EngineInput, EngineOutput
from grantforge.schemas import (
    Profile,
    RFP,
    ChecklistItem,
    SectionDraft,
    Proposal,
)


class DraftingInput(EngineInput):
    rfp: RFP
    profile: Profile
    proposal: Proposal | None = None
    section_id: str | None = None
    instruction: str | None = None  # "draft", "revise", "expand", "condense"


class DraftingOutput(EngineOutput):
    proposal: Proposal | None = None
    section: SectionDraft | None = None
    checklist: list[ChecklistItem] = []
    suggestions: list[str] = []


class DraftingEngine(Engine[DraftingInput, DraftingOutput]):
    """Drafting engine: RFP → checklist → section drafts → inline refinement."""

    name = "drafting"
    version = "2.0.0"

    # Style guide rules (enforced on every generation)
    STYLE_RULES = [
        "Use active voice",
        "Avoid jargon; define technical terms",
        "Lead with outcomes, not methods",
        "Quantify claims (%, $, n=)",
        "Max 20 words per sentence",
        "One idea per paragraph",
    ]

    def __init__(self):
        super().__init__()
        self._content_library: dict[str, str] = {}  # key → content

    async def execute(self, input: DraftingInput) -> DraftingOutput:
        if input.proposal is None:
            return await self._create_proposal(input)
        
        if input.section_id and input.instruction:
            return await self._modify_section(input)
        
        return await self._generate_checklist(input)

    async def _create_proposal(self, input: DraftingInput) -> DraftingOutput:
        """Create new proposal from RFP + profile."""
        checklist = await self._rfp_to_checklist(input.rfp)
        
        proposal = Proposal(
            rfp_id=input.rfp.id,
            title=input.rfp.title,
            pi_profile_id=input.profile.id,
            checklist=checklist,
            sections={},
        )
        return DraftingOutput(
            success=True,
            proposal=proposal,
            checklist=checklist,
        )

    async def _rfp_to_checklist(self, rfp: RFP) -> list[ChecklistItem]:
        """Convert RFP requirements into structured checklist."""
        items = []
        for i, section in enumerate(rfp.sections_required):
            items.append(ChecklistItem(
                id=f"cl_{i}",
                section=section,
                requirement=f"Write {section} per RFP guidelines",
                page_limit=rfp.page_limit,
                status="pending",
            ))
        # Add standard items
        items.extend([
            ChecklistItem(id="cl_budget", section="Budget", requirement="Budget justification"),
            ChecklistItem(id="cl_biosketches", section="Biosketches", requirement="PI + Co-I biosketches"),
            ChecklistItem(id="cl_letters", section="Letters", requirement="Support letters"),
        ])
        return items

    async def _generate_checklist(self, input: DraftingInput) -> DraftingOutput:
        checklist = await self._rfp_to_checklist(input.rfp)
        return DraftingOutput(
            success=True,
            checklist=checklist,
        )

    async def _modify_section(self, input: DraftingInput) -> DraftingOutput:
        """Draft, revise, expand, or condense a section with style enforcement."""
        # TODO: Retrieve section from proposal
        # TODO: Apply style rules via LLM
        # TODO: Pull relevant content from library
        # TODO: Return SectionDraft with version increment
        
        section = SectionDraft(
            id=input.section_id or "new",
            title="Section",
            content="[Drafted content with style rules applied]",
            word_count=150,
        )
        
        return DraftingOutput(
            success=True,
            section=section,
            suggestions=[
                "Consider adding quantitative outcome metric",
                "Define acronym on first use",
            ],
        )

    async def add_to_library(self, key: str, content: str) -> None:
        """Add content to searchable library."""
        self._content_library[key] = content

    async def search_library(self, query: str) -> list[tuple[str, str]]:
        """Search library for relevant content (semantic)."""
        # TODO: Embed query, cosine similarity vs library embeddings
        return [(k, v) for k, v in self._content_library.items() if query.lower() in k.lower()]

    async def health_check(self) -> dict[str, Any]:
        return await super().health_check()