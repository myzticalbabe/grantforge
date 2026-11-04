"""
Shared Pydantic schemas for grantforge engines.
All engines use these models for type-safe interfaces.
"""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl


class FunderType(str, Enum):
    FEDERAL = "federal"
    FOUNDATION = "foundation"
    INDUSTRY = "industry"
    INTERNAL = "internal"
    OTHER = "other"


class GrantMechanism(str, Enum):
    R01 = "R01"
    R21 = "R21"
    R03 = "R03"
    SBIR = "SBIR"
    STTR = "STTR"
    COOPERATIVE = "cooperative"
    CONTRACT = "contract"
    FELLOWSHIP = "fellowship"
    OTHER = "other"


class EligibilityVerdict(str, Enum):
    ELIGIBLE = "eligible"
    NOT_ELIGIBLE = "not_eligible"
    NEED_MORE_INFO = "need_more_info"


class CriterionCategory(str, Enum):
    CAREER_STAGE = "career_stage"
    CITIZENSHIP = "citizenship"
    ESI_STATUS = "esi_status"
    PRIOR_FUNDING = "prior_funding"
    MECHANISM_LIMIT = "mechanism_limit"
    GEOGRAPHY = "geography"
    INSTITUTION_TYPE = "institution_type"
    OTHER = "other"


class CriterionCheck(BaseModel):
    category: CriterionCategory
    requirement: str
    profile_value: str | None = None
    verdict: EligibilityVerdict
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)


class EligibilityAssessment(BaseModel):
    overall: EligibilityVerdict
    checks: list[CriterionCheck]
    missing_info: list[str] = []
    assessed_at: datetime = Field(default_factory=datetime.utcnow)
    assessed_by: str = "grantforge.eligibility"


class Funder(BaseModel):
    id: str
    name: str
    type: FunderType
    website: HttpUrl | None = None
    ein: str | None = None
    giving_patterns: dict[str, Any] = {}
    deadlines: list[datetime] = []
    contact_email: str | None = None


class RFP(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    funder_id: str
    title: str
    number: str | None = None
    url: HttpUrl | None = None
    # Optional: an RFP that states no date has no date, and a computed one is a
    # fabricated fact the user would plan against.
    deadline: datetime | None = None
    mechanism: GrantMechanism | None = None
    max_amount: float | None = None
    page_limit: int | None = None
    sections_required: list[str] = []
    formatting_rules: dict[str, str] = {}
    raw_text: str
    parsed_at: datetime = Field(default_factory=datetime.utcnow)


class Profile(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str
    orcid: str | None = None
    institution: str
    department: str | None = None
    # The two attributes an RFP asks about by name but the model had no field
    # for, so geography and institution-type criteria could only ever answer
    # need_more_info. Free text; the eligibility engine canonicalises it.
    institution_type: str | None = None  # "university", "nonprofit", "hospital", ...
    country: str | None = None  # "US", "CA", "GB", ...
    career_stage: str  # "early", "mid", "senior"
    # Tri-state on purpose: False means "checked, not ESI", None means nobody
    # said. With a plain bool the default read as a denial, so an RFP requiring
    # ESI rejected a profile that had never been asked the question.
    esi_eligible: bool | None = None
    citizenship: list[str] = []
    prior_grants: list[str] = []  # grant numbers
    publications: list[str] = []  # DOIs
    research_areas: list[str] = []
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ChecklistItem(BaseModel):
    id: str
    section: str
    requirement: str
    page_limit: int | None = None
    formatting: str | None = None
    status: Literal["pending", "in_progress", "review", "done"] = "pending"
    assignee: str | None = None
    due_date: datetime | None = None


class SectionDraft(BaseModel):
    id: str
    title: str
    content: str
    checklist_items: list[str] = []  # checklist item IDs
    word_count: int = 0
    version: int = 1
    last_edited_by: str | None = None
    last_edited_at: datetime = Field(default_factory=datetime.utcnow)


class Proposal(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    rfp_id: str
    title: str
    pi_profile_id: str
    co_investigators: list[str] = []  # profile IDs
    sections: dict[str, SectionDraft] = {}
    checklist: list[ChecklistItem] = []
    eligibility: EligibilityAssessment | None = None
    compliance_checks: dict[str, Any] = {}
    status: Literal["draft", "review", "final", "submitted"] = "draft"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    submitted_at: datetime | None = None


class ExportFormat(str, Enum):
    PDF = "pdf"
    WORD = "docx"
    EXCEL = "xlsx"
    ZIP = "zip"


class ExportBundle(BaseModel):
    proposal_id: str
    formats: list[ExportFormat]
    files: dict[str, bytes] = {}  # filename -> content
    manifest: dict[str, Any] = {}
    created_at: datetime = Field(default_factory=datetime.utcnow)