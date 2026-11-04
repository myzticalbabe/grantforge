"""
Discovery Engine — Semantic funding search + RFP ingestion + Funder intelligence + Auto-profiles
"""

from __future__ import annotations
import re
from datetime import datetime
from typing import Any

from grantforge import config as grantforge_config
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
        # Read at construction, not import, so GRANTFORGE_OV_EMBED_URL is honoured
        # for a process that sets it after importing grantforge.
        self._ov_embed_url = grantforge_config.OV_EMBED_URL
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

    # Funder identities and the domains they fund -- NOT an opportunity database.
    # A match says "this funder's stated domain overlaps your query"; it never says
    # "this funder has a call open". The previous version returned the first top_k
    # of this list for every query, so "crop rotation" and "cardiac sensing" both
    # produced nih/nsf/doe and the extracted keywords were never used.
    FUNDER_CATALOGUE: tuple[dict, ...] = (
        {"id": "nih", "name": "National Institutes of Health", "type": FunderType.FEDERAL,
         "keywords": ("health", "biomedical", "clinical", "disease", "cardiac",
                      "heart", "neuroscience", "physiology")},
        {"id": "nsf", "name": "National Science Foundation", "type": FunderType.FEDERAL,
         "keywords": ("science", "engineering", "physics", "chemistry", "materials",
                      "computing", "mathematics", "education", "sensor", "sensing")},
        {"id": "doe", "name": "Department of Energy", "type": FunderType.FEDERAL,
         "keywords": ("energy", "power", "battery", "grid", "nuclear", "fusion",
                      "climate", "efficiency")},
        {"id": "dod", "name": "Department of Defense", "type": FunderType.FEDERAL,
         "keywords": ("defense", "security", "aerospace", "autonomy", "radar",
                      "robotics")},
        {"id": "usda", "name": "US Department of Agriculture", "type": FunderType.FEDERAL,
         "keywords": ("agriculture", "food", "nutrition", "crop", "soil", "forestry",
                      "rural")},
    )

    async def _search_opportunities(self, input: DiscoveryInput) -> DiscoveryOutput:
        """Keyword match over a funder-identity catalogue, ranked by hits."""
        # Full semantic search requires ov_embed_server (NPU); until that exists
        # this is an honest keyword match over what the engine actually holds.
        query = input.query or ""
        top_k = input.top_k

        keywords = [w.strip(".,;:!?()\"'").lower() for w in query.split()]
        keywords = [w for w in keywords if len(w) > 2]

        scored = []
        for funder in self.FUNDER_CATALOGUE:
            haystack = {funder["id"], *(w.lower() for w in funder["name"].split()),
                        *funder["keywords"]}
            hits = sorted({k for k in keywords if k in haystack})
            if hits:
                scored.append((len(hits), funder, hits))
        # Deterministic order: most hits first, then id, so the same query always
        # produces the same list.
        scored.sort(key=lambda row: (-row[0], row[1]["id"]))
        chosen = scored[:top_k]

        opportunities = [
            Funder(id=funder["id"], name=funder["name"], type=funder["type"])
            for _, funder, _ in chosen
        ]

        return DiscoveryOutput(
            success=True,
            opportunities=opportunities,
            metadata={
                "query": query,
                "mode": "keyword_search",
                "keywords": keywords,
                "top_k": top_k,
                "corpus_size": len(self.FUNDER_CATALOGUE),
                "matched": {funder["id"]: hits for _, funder, hits in chosen},
                "note": ("Keyword match against a builtin funder-identity catalogue. "
                         "No opportunity (call) data is indexed, so a result means the "
                         "funder's stated domain overlaps the query -- not that a call "
                         "is open. Semantic search requires ov_embed_server on NPU."),
            },
        )

    async def _ingest_rfp(self, input: DiscoveryInput) -> DiscoveryOutput:
        """Parse RFP (PDF/URL/text) → extract criteria, deadlines, sections."""
        text = input.rfp_text or ""
        # Values the text supplied but the parser could not read. They are
        # reported rather than dropped: an unread deadline is not "no deadline".
        unparsed: list[str] = []

        # Extract title (first line or first heading)
        lines = text.strip().split("\n")
        title = lines[0].strip() if lines else "Untitled RFP"
        if len(title) > 200:
            title = title[:200]

        # Extract deadline
        deadline = None
        deadline_patterns = [
            r"deadline[:\s]+(\d{4}-\d{2}-\d{2})",
            r"due date[:\s]+(\d{4}-\d{2}-\d{2})",
            r"submission date[:\s]+(\d{4}-\d{2}-\d{2})",
            r"(\d{1,2}/\d{1,2}/\d{4})",
        ]
        for pattern in deadline_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                date_str = match.group(1)
                fmt = "%m/%d/%Y" if "/" in date_str else "%Y-%m-%d"
                try:
                    deadline = datetime.strptime(date_str, fmt)
                except ValueError:
                    unparsed.append(f"deadline:{date_str}")
                if deadline is not None:
                    break

        # No fallback date: a sheet that says "deadline: 2026-02-01" because the
        # parser wanted a value is a fact nobody stated. None is the answer.

        # Extract page limit
        page_limit = None
        page_match = re.search(r"(\d+)\s*page", text, re.IGNORECASE)
        if page_match:
            page_limit = int(page_match.group(1))

        # Extract sections required
        sections = []
        section_patterns = [
            r"required sections?[:\s]+([^.]+?)(?:\.|$|\n)",
            r"sections? required[:\s]+([^.]+?)(?:\.|$|\n)",
            r"sections?[:\s]+([^.]+?)(?:\.|$|\n)",
        ]
        for pattern in section_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                sections = [s.strip() for s in match.group(1).split(",")]
                break

        # Extract mechanism
        mechanism = None
        mech_patterns = {
            "R01": r"R01|R01\s*grant",
            "R21": r"R21|R21\s*grant",
            "R03": r"R03",
            "SBIR": r"SBIR",
            "STTR": r"STTR",
        }
        for mech, pattern in mech_patterns.items():
            if re.search(pattern, text, re.IGNORECASE):
                mechanism = mech
                break

        # Extract max amount
        max_amount = None
        amount_match = re.search(r"\$[\d,]+(?:\.\d{2})?", text)
        if amount_match:
            raw_amount = amount_match.group(0)
            try:
                max_amount = float(raw_amount.replace("$", "").replace(",", ""))
            except ValueError:
                unparsed.append(f"amount:{raw_amount}")

        rfp = RFP(
            id=f"rfp_{hash(text) % 10000:04d}",
            funder_id="unknown",
            title=title,
            deadline=deadline,
            mechanism=mechanism,
            max_amount=max_amount,
            page_limit=page_limit,
            sections_required=sections,
            raw_text=text,
        )

        return DiscoveryOutput(
            success=True,
            rfp=rfp,
            metadata={
                "mode": "rfp_ingest",
                "sections_found": len(sections),
                "deadline_source": "parsed" if deadline is not None else "not_stated",
                **({"unparsed": unparsed} if unparsed else {}),
            }
        )

    async def _get_funder_intel(self, input: DiscoveryInput) -> DiscoveryOutput:
        """Look a funder up by EIN. No 990 is fetched, downloaded or parsed.

        There is no 990 parser behind this, so the engine reports identity as the
        EIN the caller supplied and nothing else: giving totals of 0 would read
        as a measured filing, and the EIN->name map this used to carry was wrong
        (53-0196605 is the American National Red Cross, not NSF), so a name here
        was a fabricated identity the caller had no way to detect.
        """
        ein = input.funder_ein or "unknown"

        funder = Funder(
            id=ein,
            name=f"EIN {ein}",
            type=FunderType.OTHER,
            ein=ein,
            # Left empty: no filing was read, so there is no giving pattern to
            # report. Empty is the honest answer; zeros are a claim.
        )

        return DiscoveryOutput(
            success=True,
            funder_intel=funder,
            metadata={
                "mode": "funder_intel",
                "ein": ein,
                "identity_source": "ein_only",
                "giving_patterns_source": "unavailable_no_990_parser",
            },
        )

    async def _build_profile(self, input: DiscoveryInput) -> DiscoveryOutput:
        """Return the caller's profile, or an explicitly empty shell.

        Nothing is read from publications or DirectMemory — there is no lookup
        behind this method. The shell used to assert ``career_stage="early"``
        and ``esi_eligible=True``, so an eligibility run reported "eligible" for
        an investigator nobody had described. Unknown fields are now marked
        unknown and named in the metadata.
        """
        profile = input.profile
        unestablished: list[str] = []
        if profile is None:
            profile = Profile(
                id=f"auto_{hash(input.query or '') % 10000:04d}",
                name="Auto-generated Profile",
                institution="Unknown Institution",
                career_stage="unknown",
                esi_eligible=False,
                research_areas=[],
            )
            unestablished = ["name", "institution", "career_stage", "esi_eligible"]

        # Fill research areas from the query only when the profile has none: a
        # supplied profile's areas were being overwritten by the query's words.
        if input.query and not profile.research_areas:
            keywords = [w for w in input.query.split() if len(w) > 3]
            profile.research_areas = keywords[:5]

        return DiscoveryOutput(
            success=True,
            profile=profile,
            metadata={
                "mode": "profile_build",
                "areas": profile.research_areas,
                "lookup": "none_no_publication_or_memory_source",
                **({"unestablished": unestablished} if unestablished else {}),
            },
        )

    async def health_check(self) -> dict[str, Any]:
        base = await super().health_check()
        # TODO: Check ov_embed_server connectivity
        base["ov_embed_server"] = "unknown"
        base["marker"] = "unknown"
        return base