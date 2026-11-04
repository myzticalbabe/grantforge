"""
Collaboration Engine — Operational Transform for real-time co-editing + Anchor comments + Info requests + Kanban
"""

from __future__ import annotations
from typing import Any
from datetime import datetime
from uuid import uuid4

from grantforge.engine import Engine, EngineInput, EngineOutput
from grantforge.schemas import Proposal, SectionDraft


class CollaborationInput(EngineInput):
    proposal: Proposal
    action: str  # "edit", "comment", "request", "assign", "move"
    section_id: str | None = None
    user_id: str
    content: str | None = None
    target_user: str | None = None
    position: int | None = None  # for OT


class CollaborationOutput(EngineOutput):
    proposal: Proposal | None = None
    operation: dict[str, Any] | None = None  # OT operation for broadcast
    comment_id: str | None = None
    request_id: str | None = None


class CollaborationEngine(Engine[CollaborationInput, CollaborationOutput]):
    """Collaboration engine: OT for co-editing, anchor comments, info requests, kanban."""

    name = "collaboration"
    version = "2.0.0"

    def __init__(self):
        super().__init__()
        self._pending_requests: dict[str, dict] = {}
        self._comments: dict[str, dict] = {}

    async def execute(self, input: CollaborationInput) -> CollaborationOutput:
        if input.action == "edit":
            return await self._apply_edit(input)
        elif input.action == "comment":
            return await self._add_comment(input)
        elif input.action == "request":
            return await self._create_request(input)
        elif input.action == "assign":
            return await self._assign_section(input)
        elif input.action == "move":
            return await self._move_checklist_item(input)
        else:
            return CollaborationOutput(success=False, error=f"Unknown action: {input.action}")

    @staticmethod
    def _section(proposal: Proposal, section_id: str | None) -> SectionDraft | None:
        """Resolve a section by id. None when the caller named no section or an
        id the proposal does not hold -- both are failures, not empty edits."""
        if not section_id:
            return None
        return proposal.sections.get(section_id)

    async def _apply_edit(self, input: CollaborationInput) -> CollaborationOutput:
        """Apply an edit to a section and report the version it produced.

        There is no operational transform here and the operation says so:
        concurrent operations are not rebased, so the caller must not present
        this as conflict-free co-editing. What it does do is real -- the section
        content changes and its version increments -- where the previous version
        returned success and a version-1 operation while leaving the proposal
        untouched.
        """
        section = self._section(input.proposal, input.section_id)
        if section is None:
            return CollaborationOutput(
                success=False,
                error=f"No section {input.section_id!r} in proposal {input.proposal.id}",
            )

        text = input.content or ""
        if text:
            section.content = text
        else:
            section.content = section.content[: input.position or 0]
        section.word_count = len(section.content.split())
        section.version += 1
        section.last_edited_by = input.user_id
        section.last_edited_at = datetime.utcnow()
        input.proposal.updated_at = section.last_edited_at

        operation = {
            "type": "insert" if text else "delete",
            "section_id": section.id,
            "position": input.position,
            "text": text,
            "user_id": input.user_id,
            "timestamp": section.last_edited_at.isoformat(),
            "version": section.version,
            "transformed": False,
        }

        return CollaborationOutput(
            success=True,
            proposal=input.proposal,
            operation=operation,
        )

    async def _add_comment(self, input: CollaborationInput) -> CollaborationOutput:
        """Anchor a comment to a section and keep it, so the id refers to a comment."""
        section = self._section(input.proposal, input.section_id)
        if section is None:
            return CollaborationOutput(
                success=False,
                error=f"No section {input.section_id!r} in proposal {input.proposal.id}",
            )

        comment_id = uuid4().hex[:12]
        self._comments[comment_id] = {
            "proposal_id": input.proposal.id,
            "section_id": section.id,
            "position": input.position,
            "user_id": input.user_id,
            "text": input.content,
            "created_at": datetime.utcnow().isoformat(),
        }
        return CollaborationOutput(
            success=True,
            proposal=input.proposal,
            comment_id=comment_id,
        )

    async def _create_request(self, input: CollaborationInput) -> CollaborationOutput:
        """Create info request to SME."""
        request_id = uuid4().hex[:12]
        self._pending_requests[request_id] = {
            "from": input.user_id,
            "to": input.target_user,
            "section_id": input.section_id,
            "question": input.content,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
        }
        return CollaborationOutput(
            success=True,
            request_id=request_id,
        )

    async def _assign_section(self, input: CollaborationInput) -> CollaborationOutput:
        """Assign every checklist item filed under this section to target_user.

        Success without a match would be indistinguishable from an assignment
        that landed, so an unknown section or no items under it is a failure.
        """
        section = self._section(input.proposal, input.section_id)
        if section is None:
            return CollaborationOutput(
                success=False,
                error=f"No section {input.section_id!r} in proposal {input.proposal.id}",
            )
        if not input.target_user:
            return CollaborationOutput(success=False, error="assign needs target_user")

        wanted = section.title.strip().lower()
        assigned = [item for item in input.proposal.checklist
                    if item.section.strip().lower() == wanted]
        if not assigned:
            return CollaborationOutput(
                success=False,
                error=f"No checklist items filed under {section.title!r}",
            )
        for item in assigned:
            item.assignee = input.target_user
        input.proposal.updated_at = datetime.utcnow()

        return CollaborationOutput(
            success=True,
            proposal=input.proposal,
            operation={
                "type": "assign",
                "section_id": section.id,
                "assignee": input.target_user,
                "item_ids": [item.id for item in assigned],
            },
        )

    async def _move_checklist_item(self, input: CollaborationInput) -> CollaborationOutput:
        """Advance one checklist item one column: pending -> in_progress -> review -> done."""
        order = ["pending", "in_progress", "review", "done"]
        item = next((i for i in input.proposal.checklist if i.id == input.section_id), None)
        if item is None:
            return CollaborationOutput(
                success=False,
                error=f"No checklist item {input.section_id!r} in proposal {input.proposal.id}",
            )
        if item.status != order[-1]:
            item.status = order[order.index(item.status) + 1]
        input.proposal.updated_at = datetime.utcnow()

        return CollaborationOutput(
            success=True,
            proposal=input.proposal,
            operation={
                "type": "move",
                "item_id": item.id,
                "status": item.status,
            },
        )

    async def health_check(self) -> dict[str, Any]:
        return await super().health_check()