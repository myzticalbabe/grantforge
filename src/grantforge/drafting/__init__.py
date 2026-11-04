"""
Drafting Engine — Checklist-driven section drafting + Content library + Style guide + Inline AI + Voice learning
"""

from __future__ import annotations
import re
from typing import Any

from grantforge.drafting.sections import SectionComposer, section_key
from grantforge.engine import Engine, EngineInput, EngineOutput
from grantforge.schemas import (
    Profile,
    RFP,
    ChecklistItem,
    SectionDraft,
    Proposal,
)


_LIBRARY_STOPWORDS = frozenset(
    """a an and any are as at be been by can for from has have if in into is it
    its no not of on or our so than that the their there these this to was we
    were what when which will with you your""".split()
)


def _library_terms(text: str) -> set[str]:
    """Content words in ``text``: lowercased, three letters or more, no stopwords."""
    return {
        term for term in re.findall(r"[a-z][a-z0-9]{2,}", text.lower())
        if term not in _LIBRARY_STOPWORDS
    }


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

    # Advisory: the composer cannot obey a word limit it does not measure, and
    # nothing applies these rules to generated text. They are guidance for the
    # applicant, not a gate -- the header used to claim enforcement.
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
        self._composer = SectionComposer()

    async def execute(self, input: DraftingInput) -> DraftingOutput:
        if input.proposal is None:
            return await self._create_proposal(input)
        
        if input.section_id and input.instruction:
            return await self._modify_section(input)
        
        return await self._generate_checklist(input)

    async def _create_proposal(self, input: DraftingInput) -> DraftingOutput:
        """Create new proposal from RFP + profile, composing every section.

        This used to return a checklist and an empty ``sections`` map, so the
        compliance review had nothing to read and the run exported a bundle with
        no text in it. Each checklist item now gets a composed scaffold, and the
        output says which kind of draft it is rather than implying finished prose.
        """
        checklist = await self._rfp_to_checklist(input.rfp)
        sections: dict[str, SectionDraft] = {}
        composed: list[str] = []
        # The standard Budget item would duplicate a required Budget section.
        budget_covered = any(
            "budget" in item.section.lower()
            for item in checklist
            if item.id.startswith("cl_") and item.id[3:].isdigit()
        )
        for item in checklist:
            if item.id == "cl_budget" and budget_covered:
                continue
            key = section_key(item.section)
            if key in sections:  # two labels normalise to the same key
                continue
            library_hits = await self.search_library(key)
            content = self._composer.compose(
                key, input.rfp, input.profile,
                requirement=item.requirement,
                library_note=library_hits[0][1] if library_hits else None,
            )
            sections[key] = SectionDraft(
                id=key,
                title=item.section,
                content=content,
                word_count=len(content.split()),
            )
            composed.append(key)

        proposal = Proposal(
            rfp_id=input.rfp.id,
            title=input.rfp.title,
            pi_profile_id=input.profile.id,
            checklist=checklist,
            sections=sections,
        )
        return DraftingOutput(
            success=True,
            proposal=proposal,
            checklist=checklist,
            metadata={
                "drafted_sections": composed,
                "composer": "deterministic_scaffold_no_model",
                "draft_kind": "scaffold",
            },
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
        """Draft a template, or condense existing text. Revise and expand need a model.

        revise/expand used to return a bracketed marker ("[Revised content for
        specific_aims ...]") with success=True, so a placeholder could be exported
        as the section body and word-counted as prose. There is no text generator
        behind this engine, so those instructions now fail and say what they need;
        condense is real (it trims the section the proposal already holds).
        """
        section_id = input.section_id or "new"
        instruction = (input.instruction or "draft").lower()

        existing = None
        if input.proposal is not None:
            existing = input.proposal.sections.get(section_id)

        # Get relevant content from library
        library_hits = await self.search_library(section_id)

        if instruction == "draft":
            content = self._draft_content(section_id, input.rfp, input.profile, library_hits)
        elif instruction == "condense":
            if existing is None or not existing.content.strip():
                return DraftingOutput(
                    success=False,
                    error=(f"condense needs the existing text of {section_id!r}; "
                           "the proposal has no such section"),
                )
            content = self._condense_content(existing.content)
        elif instruction in {"revise", "expand"}:
            return DraftingOutput(
                success=False,
                error=(f"{instruction} needs a text model: no generator is wired into "
                       "grantforge, and returning a bracketed marker as the section "
                       "body would be a placeholder dressed as a revision"),
            )
        else:
            return DraftingOutput(
                success=False,
                error=f"Unknown instruction: {instruction}",
            )

        word_count = len(content.split())

        section = SectionDraft(
            id=section_id,
            title=existing.title if existing else section_id.replace("_", " ").title(),
            content=content,
            word_count=word_count,
            version=(existing.version + 1) if existing else 1,
            last_edited_by=input.profile.name if input.profile else None,
        )

        suggestions = self._generate_suggestions(section_id, content)

        return DraftingOutput(
            success=True,
            section=section,
            suggestions=suggestions,
        )

    def _draft_content(self, section_id: str, rfp: RFP, profile: Profile,
                       library_hits: list) -> str:
        """Compose the section from the RFP and the profile.

        No sentence here claims significance, alignment or innovation: nothing in
        this engine assessed them, so the scaffold asks for them instead.
        """
        return self._composer.compose(
            section_key(section_id), rfp, profile,
            library_note=library_hits[0][1][:200] if library_hits else None,
        )

    @staticmethod
    def _condense_content(text: str) -> str:
        """Deterministic trim: first sentence of each paragraph, capped at 80 words.

        A real reduction of the text that was supplied, not a marker standing in
        for one: every sentence kept comes from the caller's own section.
        """
        kept: list[str] = []
        for paragraph in text.split("\n\n"):
            stripped = paragraph.strip()
            if not stripped:
                continue
            first = re.split(r"(?<=[.!?])\s+", stripped)[0].strip()
            kept.append(first)
        condensed = " ".join(kept)
        words = condensed.split()
        if len(words) > 80:
            condensed = " ".join(words[:80]) + " …"
        return condensed

    # An acronym is a run of capitals; it counts as defined when the text spells
    # it out in parentheses, the conventional form ("magnetic sensing (MEGS)").
    _ACRONYM_RE = re.compile(r"\b[A-Z]{2,6}\b")
    _EXPANSION_RE = re.compile(r"\([^()]*?([A-Z]{2,6})s?\)")

    def _undefined_acronyms(self, content: str) -> list[str]:
        defined = set(self._EXPANSION_RE.findall(content))
        return sorted({a for a in self._ACRONYM_RE.findall(content) if a not in defined})

    def _generate_suggestions(self, section_id: str, content: str) -> list[str]:
        """Advice about this text, naming what in it prompted the advice.

        The acronym suggestion used to fire whenever the literal word "acronym"
        was absent, so it appeared on text with no acronyms at all and named
        none of the ones present.
        """
        suggestions = []
        if "quantif" not in content.lower() and "%" not in content and "$" not in content:
            suggestions.append("Consider adding quantitative outcome metric")
        if len(content.split()) > 300:
            suggestions.append("Section may exceed page limit - consider condensing")
        undefined = self._undefined_acronyms(content)
        if undefined:
            suggestions.append("Define on first use: " + ", ".join(undefined))
        return suggestions

    async def add_to_library(self, key: str, content: str) -> None:
        """Add content to searchable library."""
        self._content_library[key] = content

    async def search_library(self, query: str, limit: int = 3) -> list[tuple[str, str]]:
        """Rank stored content by the terms it shares with ``query``.

        This used to be a substring test against the key alone, so a section stored
        as ``preliminary_studies`` could not be found by the query ``prior data``
        even when its body was about exactly that. Ranking key and body together
        needs no model and no embedding: a query term found in the key weighs 2,
        the same term found only in the body weighs 1, and an entry sharing nothing
        is not a hit at all. Ties break on key, so one library always ranks the
        same way twice.
        """
        terms = _library_terms(query)
        if not terms:
            return []
        scored: list[tuple[int, str]] = []
        for key, content in self._content_library.items():
            key_terms = _library_terms(key)
            body_terms = _library_terms(content)
            score = 0
            for term in terms:
                if term in key_terms:
                    score += 2
                elif term in body_terms:
                    score += 1
            if score:
                scored.append((score, key))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [(key, self._content_library[key]) for _, key in scored[:limit]]

    async def health_check(self) -> dict[str, Any]:
        return await super().health_check()