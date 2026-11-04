"""Section composer — the text layer behind the drafting engine.

A section body is assembled from three kinds of line, and nothing else:

* a sentence **quoted** from the RFP that governs this section,
* a fact **read** from the parsed RFP or the profile,
* an item the applicant still has to supply.

There is no language model behind this composer, so it never writes a sentence
about the research itself. "The work is significant because ..." would be a
judgement nobody made; "state why the work matters" is the same request without
the invention. That distinction is the reason this module exists at all rather
than a template string in the engine.
"""

from __future__ import annotations

import re

from grantforge.schemas import Profile, RFP

# Canonical section key → phrases that locate the RFP sentences governing it.
SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "specific_aims": ("specific aims", "aims", "objectives"),
    "research_strategy": ("research strategy", "approach", "method", "experimental design"),
    "budget_justification": ("budget", "cost", "award ceiling", "funding request"),
    "budget": ("budget", "cost", "award ceiling"),
    "biosketches": ("biosketch", "biographical sketch", "curriculum vitae"),
    "letters": ("letter", "letters of support"),
    "broader_impacts": ("broader impact", "broader impacts"),
    "innovation": ("innovation",),
    "significance": ("significance",),
    "data_management": ("data management", "data sharing", "sharing plan"),
    "mentoring_plan": ("mentoring", "training plan", "career development"),
    "facilities": ("facilities", "resources", "equipment"),
    "timeline": ("timeline", "schedule", "milestones"),
}

# What each section has to contain, as instructions rather than prose.
SECTION_GUIDANCE: dict[str, tuple[str, ...]] = {
    "specific_aims": (
        "the aims themselves, one numbered aim per paragraph",
        "for each aim, the hypothesis it tests and the measurement that would "
        "confirm or refute it",
        "what is new about the approach, stated by the applicant rather than "
        "assumed by this draft",
    ),
    "research_strategy": (
        "the design, methods and analysis plan for each aim",
        "milestones with dates and a quantitative exit criterion for each",
        "known pitfalls and the alternative taken if a milestone slips",
        "preliminary results, with the data that supports them",
    ),
    "budget_justification": (
        "line-item costs by budget period, with the basis for each figure "
        "(person-months, equipment quotes, travel)",
        "how the request fits the funder's ceiling, if the RFP states one",
        "who is charged to which line, and for how much time",
    ),
    "budget": (
        "line-item costs by budget period, with the basis for each figure",
        "the indirect-cost rate and the base it applies to",
    ),
    "biosketches": (
        "a biosketch for every senior/key person, in the funder's format",
        "each person's role on this project and the effort committed",
    ),
    "letters": (
        "the named letter writers and their relationship to the project",
        "what each letter commits to (access, data, time, cost share)",
    ),
    "broader_impacts": (
        "the societal outcome being pursued, and who benefits",
        "how the outcome will be measured, and by when",
    ),
    "innovation": (
        "what changes if this work succeeds, compared with current practice",
    ),
    "significance": (
        "the problem, who it affects, and the cost of leaving it unsolved",
    ),
    "data_management": (
        "what data is produced, in what format, and where it will be deposited",
        "who may access it, under what terms, and for how long",
    ),
    "mentoring_plan": (
        "the mentoring the PI receives, from whom, and how often",
        "the training the project provides, and to whom",
    ),
    "facilities": (
        "the equipment and space the work needs, and where it is",
        "anything the project must buy or borrow",
    ),
    "timeline": (
        "the budget periods and what lands at the end of each",
    ),
}

_GENERIC_GUIDANCE = (
    "the applicant's own wording for this section",
    "any figure or commitment the section promises",
)

# Splitting only on blank lines glued the title, funder, deadline and section
# list into one 27-word "requirement"; splitting on every newline cut "... a 12
# page / research strategy." in half. A line continues the previous one when it
# starts lowercase and is not a "key: value" record.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_RECORD_LINE = re.compile(r"^[a-z][a-z0-9 /_-]*:")
_TERMINAL = re.compile(r"[.!?:]$")


def section_key(label: str) -> str:
    """Normalise a section label: \"Budget Justification\" → \"budget_justification\"."""
    return re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")


def _plain(sentence: str) -> str:
    return " ".join(sentence.split())


def _money(amount: float) -> str:
    return f"${amount:,.0f}"


class SectionComposer:
    """Compose one section body from the parsed RFP and the profile."""

    def compose(
        self,
        key: str,
        rfp: RFP,
        profile: Profile | None,
        requirement: str | None = None,
        library_note: str | None = None,
    ) -> str:
        blocks: list[str] = [
            "DRAFT — a scaffold composed from this RFP and the profile. The "
            "applicant's own wording is not in it: every line below is quoted from "
            "the RFP, read from the record, or still to be supplied."
        ]

        quoted = self.rfp_sentences_for(key, rfp)
        if quoted:
            blocks.append(
                "What the RFP says about this section:\n"
                + "\n".join(f'- "{s}"' for s in quoted)
            )
        elif requirement:
            blocks.append(f"What the RFP asks for:\n- {requirement}")

        facts = self.recorded_facts(rfp, profile)
        if facts:
            blocks.append(
                "What the record supplies:\n" + "\n".join(f"- {f}" for f in facts)
            )

        gaps = list(SECTION_GUIDANCE.get(key, _GENERIC_GUIDANCE))
        gaps.extend(self.record_gaps(key, profile))
        blocks.append(
            "Still to supply:\n" + "\n".join(f"- [ ] {g}" for g in gaps)
        )

        if library_note:
            blocks.append(f"From the content library:\n- {library_note}")

        return "\n\n".join(blocks)

    def rfp_sentences_for(self, key: str, rfp: RFP) -> list[str]:
        """RFP sentences that mention this section, quoted rather than paraphrased."""
        aliases = SECTION_ALIASES.get(key, (key.replace("_", " "),))
        matched = [
            s for s in self.rfp_sentences(rfp)
            if any(alias in s.lower() for alias in aliases)
        ]
        return matched[:3]

    @staticmethod
    def rfp_sentences(rfp: RFP) -> list[str]:
        """The RFP's raw text as sentences, with wrapped lines rejoined."""
        lines = [line.strip() for line in (rfp.raw_text or "").splitlines()]
        merged: list[str] = []
        for line in lines:
            if not line:
                merged.append("")
                continue
            previous = merged[-1] if merged else ""
            if (
                previous
                and not _TERMINAL.search(previous)
                and line[:1].islower()
                and not _RECORD_LINE.match(line)
            ):
                merged[-1] = previous + " " + line
            else:
                merged.append(line)
        sentences: list[str] = []
        for block in merged:
            sentences.extend(
                _plain(part) for part in _SENTENCE_SPLIT.split(block) if part.strip()
            )
        return sentences

    def recorded_facts(self, rfp: RFP, profile: Profile | None) -> list[str]:
        facts: list[str] = []
        if profile is not None:
            where = ", ".join(
                part for part in (profile.department, profile.institution) if part
            )
            facts.append(f"PI: {profile.name}" + (f" — {where}" if where else ""))
            stage = (profile.career_stage or "").strip()
            if stage and stage.lower() not in {"unknown", "unspecified", "n/a"}:
                facts.append(f"Career stage on record: {stage}")
            if profile.esi_eligible is True:
                facts.append("Profile states the PI is ESI-eligible")
            if profile.research_areas:
                facts.append("Research areas on record: " + ", ".join(profile.research_areas))
            if profile.prior_grants:
                facts.append(
                    f"Prior awards listed ({len(profile.prior_grants)}): "
                    + ", ".join(profile.prior_grants)
                )
            if profile.publications:
                facts.append(f"Publications listed: {len(profile.publications)}")
        if rfp.mechanism is not None:
            # A GrantMechanism enum stringifies as "GrantMechanism.R01".
            mechanism = getattr(rfp.mechanism, "value", rfp.mechanism)
            facts.append(f"Mechanism named by the RFP: {mechanism}")
        if rfp.max_amount is not None:
            facts.append(f"Award ceiling in the RFP: {_money(rfp.max_amount)}")
        if rfp.deadline is not None:
            facts.append(f"Deadline in the RFP: {rfp.deadline.date().isoformat()}")
        if rfp.page_limit is not None:
            facts.append(f"Page limit in the RFP: {rfp.page_limit}")
        return facts

    def record_gaps(self, key: str, profile: Profile | None) -> list[str]:
        """Facts the section needs that the record does not hold, named one by one."""
        gaps: list[str] = []
        if profile is None:
            return ["the PI profile — no profile was supplied"]
        if not profile.research_areas:
            gaps.append("the research areas this section describes")
        if not profile.prior_grants and key in {"specific_aims", "research_strategy"}:
            gaps.append(
                "preliminary work or prior awards, if the RFP expects them "
                "(the profile lists none)"
            )
        if key in {"biosketches", "letters"} and not profile.publications:
            gaps.append("supporting publication record (the profile lists none)")
        return gaps
