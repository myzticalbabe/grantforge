"""
Export Engine — Funder templates + Budget tables + One-click PDF/Word/Excel + Submission bundle
"""

from __future__ import annotations
from typing import Any
from datetime import datetime
from io import BytesIO

from grantforge.engine import Engine, EngineInput, EngineOutput
from grantforge.schemas import (
    Proposal, Profile, RFP, ExportFormat, ExportBundle, 
    SectionDraft, ChecklistItem
)


class ExportInput(EngineInput):
    proposal: Proposal
    pi_profile: Profile
    rfp: RFP
    formats: list[ExportFormat] = [ExportFormat.PDF, ExportFormat.WORD, ExportFormat.EXCEL]
    funder_template: str | None = None  # "nih", "nsf", "doe", "foundation"


class ExportOutput(EngineOutput):
    bundle: ExportBundle | None = None
    files: dict[str, bytes] = {}  # filename -> content


class ExportEngine(Engine[ExportInput, ExportOutput]):
    """Export engine: funder-specific templates → PDF/Word/Excel → complete submission bundle."""

    name = "export"
    version = "2.0.0"

    # Funder-specific template configs
    TEMPLATES = {
        "nih": {
            "page_limit": 12,
            "font": "Arial 11pt",
            "margins": "0.5in",
            "sections": [
                "Specific Aims",
                "Research Strategy",
                "Significance",
                "Innovation",
                "Approach",
                "Preliminary Studies",
            ],
        },
        "nsf": {
            "page_limit": 15,
            "font": "Arial 11pt", 
            "margins": "1in",
            "sections": [
                "Project Summary",
                "Project Description",
                "References Cited",
                "Biographical Sketches",
                "Budget Justification",
            ],
        },
        "doe": {
            "page_limit": 20,
            "font": "Times New Roman 12pt",
            "margins": "1in",
            "sections": [
                "Technical Abstract",
                "Technical Description",
                "Work Plan",
                "Management Plan",
                "Budget Justification",
            ],
        },
        "foundation": {
            "page_limit": 10,
            "font": "Calibri 11pt",
            "margins": "1in",
            "sections": [
                "Executive Summary",
                "Need Statement",
                "Project Description",
                "Evaluation Plan",
                "Sustainability",
                "Budget Narrative",
            ],
        },
    }

    async def execute(self, input: ExportInput) -> ExportOutput:
        files = {}
        
        for fmt in input.formats:
            if fmt == ExportFormat.PDF:
                pdf_bytes = await self._render_pdf(input)
                files[f"{input.proposal.id}_proposal.pdf"] = pdf_bytes
            elif fmt == ExportFormat.WORD:
                docx_bytes = await self._render_word(input)
                files[f"{input.proposal.id}_proposal.docx"] = docx_bytes
            elif fmt == ExportFormat.EXCEL:
                xlsx_bytes = await self._render_excel(input)
                files[f"{input.proposal.id}_budget.xlsx"] = xlsx_bytes

        # Create submission bundle
        bundle = ExportBundle(
            proposal_id=input.proposal.id,
            formats=input.formats,
            files=files,
            manifest={
                "proposal_id": input.proposal.id,
                "title": input.proposal.title,
                "pi": input.pi_profile.name,
                "funder": input.rfp.funder_id,
                "deadline": input.rfp.deadline.isoformat() if input.rfp.deadline else None,
                "generated_at": datetime.utcnow().isoformat(),
                "page_counts": {},  # TODO: compute
            },
        )

        return ExportOutput(
            success=True,
            bundle=bundle,
            files=files,
        )

    async def _render_pdf(self, input: ExportInput) -> bytes:
        """Render proposal to PDF using reportlab."""
        # TODO: Implement reportlab PDF generation
        # - Apply funder template (margins, font, page limit)
        # - Render each section with proper formatting
        # - Add budget tables, biosketches, references
        # - Return bytes
        
        # Placeholder
        buffer = BytesIO()
        buffer.write(b"%PDF-1.4\n%Placeholder PDF for grantforge export")
        return buffer.getvalue()

    async def _render_word(self, input: ExportInput) -> bytes:
        """Render proposal to Word using python-docx."""
        # TODO: Implement python-docx generation
        # - Use funder template styles
        # - Auto-generate table of contents
        # - Insert section headings, content, tables
        # - Return bytes
        
        buffer = BytesIO()
        buffer.write(b"PK\x03\x04")  # DOCX magic
        buffer.write(b"Placeholder DOCX for grantforge export")
        return buffer.getvalue()

    async def _render_excel(self, input: ExportInput) -> bytes:
        """Render budget to Excel using openpyxl."""
        # TODO: Implement openpyxl budget workbook
        # - Personnel, Equipment, Travel, Supplies, Other, Indirect Costs
        # - Year-by-year breakdown
        # - Formulas for totals
        # - Return bytes
        
        buffer = BytesIO()
        buffer.write(b"PK\x03\x04")  # XLSX magic
        buffer.write(b"Placeholder XLSX for grantforge export")
        return buffer.getvalue()

    def _get_template(self, funder: str) -> dict[str, Any]:
        return self.TEMPLATES.get(funder.lower(), self.TEMPLATES["foundation"])

    async def health_check(self) -> dict[str, Any]:
        base = await super().health_check()
        base["reportlab"] = "unknown"
        base["python-docx"] = "unknown"
        base["openpyxl"] = "unknown"
        return base