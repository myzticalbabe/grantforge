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

    async def _apply_edit(self, input: CollaborationInput) -> CollaborationOutput:
        """Apply operational transform edit to section."""
        # TODO: Implement OT (operational transform) for concurrent edits
        # 1. Transform incoming operation against concurrent ops
        # 2. Apply to section content
        # 3. Broadcast transformed operation to other clients
        # 4. Update section version
        
        operation = {
            "type": "insert" if input.content else "delete",
            "section_id": input.section_id,
            "position": input.position,
            "text": input.content,
            "user_id": input.user_id,
            "timestamp": datetime.utcnow().isoformat(),
            "version": 1,  # TODO: increment
        }
        
        return CollaborationOutput(
            success=True,
            operation=operation,
        )

    async def _add_comment(self, input: CollaborationInput) -> CollaborationOutput:
        """Add anchor comment to section."""
        comment_id = uuid4().hex[:12]
        # TODO: Store comment with anchor (section_id, position)
        return CollaborationOutput(
            success=True,
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
        """Assign section to user (updates checklist assignee)."""
        # TODO: Update checklist item assignee
        return CollaborationOutput(success=True)

    async def _move_checklist_item(self, input: CollaborationInput) -> CollaborationOutput:
        """Move checklist item (kanban: pending → in_progress → review → done)."""
        # TODO: Update checklist item status
        return CollaborationOutput(success=True)

    async def health_check(self) -> dict[str, Any]:
        return await super().health_check()