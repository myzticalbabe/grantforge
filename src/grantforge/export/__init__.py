"""
Export Engine — Funder templates + Budget tables + One-click PDF/Word/Excel + Submission bundle
"""

from __future__ import annotations
from typing import Any
from datetime import datetime
from io import BytesIO
import textwrap
import zipfile
from xml.sax.saxutils import escape

# Optional renderers, imported once: a fallback branch must not import inside the
# function it is the fallback for (the scanner's import_inside_function rule).
try:
    from docx import Document
except ImportError:  # python-docx absent on 3.15t: the OOXML fallback ships there
    Document = None

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font
except ImportError:  # openpyxl absent on 3.15t: the SpreadsheetML fallback ships there
    Workbook = None
    Font = None

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
except ImportError:  # reportlab absent: the hand-built PDF fallback ships
    SimpleDocTemplate = None

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
                # No page counts: nothing here renders and reads back a page count,
                # and an empty page_counts dict read as "zero pages" to a caller
                # checking a page limit. The key is absent rather than hollow.
                "formats": [fmt.value for fmt in input.formats],
                "files": sorted(files),
            },
        )

        return ExportOutput(
            success=True,
            bundle=bundle,
            files=files,
        )

    async def _render_pdf(self, input: ExportInput) -> bytes:
        """Render proposal to PDF using reportlab if available, else text fallback."""
        if SimpleDocTemplate is not None:
            buffer = BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=letter)
            styles = getSampleStyleSheet()
            story = []

            story.append(Paragraph(input.proposal.title, styles["Title"]))
            story.append(Spacer(1, 12))
            story.append(Paragraph(f"PI: {input.pi_profile.name}", styles["Normal"]))
            story.append(Paragraph(f"Funder: {input.rfp.funder_id}", styles["Normal"]))
            story.append(Spacer(1, 12))

            for section_id, section in input.proposal.sections.items():
                story.append(Paragraph(section.title, styles["Heading2"]))
                story.append(Paragraph(section.content, styles["Normal"]))
                story.append(Spacer(1, 6))

            doc.build(story)
            return buffer.getvalue()

        return self._minimal_pdf(input)

    # Lines per page at 11pt with 14pt leading inside 648pt of text height.
    PDF_LINES_PER_PAGE = 44
    PDF_WRAP_COLUMNS = 95

    @staticmethod
    def _pdf_string(text: str) -> str:
        """A PDF literal string: latin-1 safe, backslashes and parens escaped."""
        safe = str(text).encode("latin-1", "replace").decode("latin-1")
        return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    def _pdf_lines(self, input: ExportInput) -> list[tuple[str, bool, int]]:
        """(text, bold, size) for every line the document must carry."""
        lines: list[tuple[str, bool, int]] = [
            (input.proposal.title, True, 16),
            ("", False, 11),
            (f"PI: {input.pi_profile.name}", False, 11),
            (f"Institution: {input.pi_profile.institution}", False, 11),
            (f"Funder: {input.rfp.funder_id}", False, 11),
            (self._deadline_line(input), False, 11),
            ("", False, 11),
        ]
        for _section_id, section in input.proposal.sections.items():
            lines.append((section.title, True, 13))
            wrapped = textwrap.wrap(
                " ".join(str(section.content).split()), self.PDF_WRAP_COLUMNS
            ) or [""]
            lines.extend((line, False, 11) for line in wrapped)
            lines.append(("", False, 11))
        return lines

    def _minimal_pdf(self, input: ExportInput) -> bytes:
        """A real PDF built without reportlab, carrying the proposal's text.

        The previous fallback wrote a well-formed PDF with one page object and
        **no content stream at all**: valid bytes, zero words, exported as
        ``<proposal>_proposal.pdf`` with success=True. Word and Excel already had
        real fallbacks for the interpreters that lack their renderer; this is the
        same treatment for PDF. reportlab is not in grantforge's requirements, so
        this path ships wherever the bundle is built on a clean install.
        """
        lines = self._pdf_lines(input)
        pages: list[bytes] = []
        for start in range(0, len(lines), self.PDF_LINES_PER_PAGE):
            chunk = lines[start:start + self.PDF_LINES_PER_PAGE]
            ops = ["BT", "1 0 0 1 72 720 Tm"]
            for text, bold, size in chunk:
                font = "/F2" if bold else "/F1"
                ops.append(f"{font} {size} Tf 0 -{size + 4} Td")
                if text:
                    ops.append(f"({self._pdf_string(text)}) Tj")
            ops.append("ET")
            pages.append("\n".join(ops).encode("latin-1"))
        if not pages:
            pages.append(b"BT /F1 11 Tf 72 720 Td (empty proposal) Tj ET")

        # Objects: 1 catalog, 2 pages tree, 3-4 fonts, then (stream, page) pairs.
        objects: dict[int, bytes] = {
            1: b"<< /Type /Catalog /Pages 2 0 R >>",
            3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            4: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        }
        kids = []
        for index, content in enumerate(pages):
            page_obj = 5 + 2 * index + 1
            kids.append(f"{page_obj} 0 R")
            objects[page_obj - 1] = (
                f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
                + content
                + b"\nendstream"
            )
            objects[page_obj] = (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                "/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
                f"/Contents {page_obj - 1} 0 R >>"
            ).encode("ascii")
        objects[2] = (
            f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>"
        ).encode("ascii")

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: dict[int, int] = {}
        for number in sorted(objects):
            offsets[number] = len(out)
            out += f"{number} 0 obj\n".encode("ascii") + objects[number] + b"\nendobj\n"
        xref_at = len(out)
        count = len(objects) + 1
        out += f"xref\n0 {count}\n".encode("ascii")
        out += b"0000000000 65535 f \n"
        for number in sorted(objects):
            out += f"{offsets[number]:010d} 00000 n \n".encode("ascii")
        out += (
            f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
        ).encode("ascii")
        return bytes(out)

    async def _render_word(self, input: ExportInput) -> bytes:
        """Render proposal to Word using python-docx if available."""
        if Document is not None:
            doc = Document()
            doc.add_heading(input.proposal.title, level=0)
            doc.add_paragraph(f"PI: {input.pi_profile.name}")
            doc.add_paragraph(f"Institution: {input.pi_profile.institution}")
            doc.add_paragraph(f"Funder: {input.rfp.funder_id}")
            doc.add_paragraph(self._deadline_line(input))

            for section_id, section in input.proposal.sections.items():
                doc.add_heading(section.title, level=1)
                doc.add_paragraph(section.content)

            buffer = BytesIO()
            doc.save(buffer)
            return buffer.getvalue()

        # Fallback: a minimal but valid OOXML package. A bare document.xml in a
        # ZIP is rejected by Word, and python-docx is absent on 3.15t, so this
        # is the shipped path there — it must include the package parts.

        W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        paragraphs = [
            ("Title", input.proposal.title),
            (None, f"PI: {input.pi_profile.name}"),
            (None, f"Institution: {input.pi_profile.institution}"),
            (None, f"Funder: {input.rfp.funder_id}"),
            (None, self._deadline_line(input)),
        ]
        for _section_id, section in input.proposal.sections.items():
            paragraphs.append(("Heading1", section.title))
            paragraphs.append((None, section.content))

        body = []
        for style, text in paragraphs:
            ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
            body.append(f'<w:p>{ppr}<w:r><w:t xml:space="preserve">{escape(str(text))}</w:t></w:r></w:p>')
        document = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{W}"><w:body>{"".join(body)}</w:body></w:document>'
        )

        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml",
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                        '<Default Extension="xml" ContentType="application/xml"/>'
                        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                        '</Types>')
            zf.writestr("_rels/.rels",
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                        '</Relationships>')
            zf.writestr("word/document.xml", document)
        return buffer.getvalue()

    async def _render_excel(self, input: ExportInput) -> bytes:
        """Render budget to Excel using openpyxl if available."""
        if Workbook is not None:
            wb = Workbook()
            ws = wb.active
            ws.title = "Budget"

            ws["A1"] = "Grant Budget"
            ws["A1"].font = Font(bold=True, size=14)
            ws["A2"] = f"Proposal: {input.proposal.title}"
            ws["A3"] = f"PI: {input.pi_profile.name}"
            ws["A4"] = f"Funder: {input.rfp.funder_id}"

            row = 6
            ws.cell(row=row, column=1, value="Category").font = Font(bold=True)
            ws.cell(row=row, column=2, value="Amount").font = Font(bold=True)
            row += 1

            # Amounts are deliberately blank: nothing in this pipeline computes
            # budget figures, and a hardcoded 0 in every row was a $0 budget
            # claim rather than an unfilled template.
            categories = ["Personnel", "Equipment", "Travel", "Supplies", "Other", "Indirect Costs"]
            first_amount_row = row
            for cat in categories:
                ws.cell(row=row, column=1, value=cat)
                row += 1

            ws.cell(row=row, column=1, value="Total").font = Font(bold=True)
            ws.cell(row=row, column=2, value=f"=SUM(B{first_amount_row}:B{row-1})").font = Font(bold=True)
            row += 2

            ws.cell(row=row, column=1, value=self._budget_note(input))
            ws.cell(row=row + 1, column=1, value=self._ceiling_note(input))

            buffer = BytesIO()
            wb.save(buffer)
            return buffer.getvalue()

        # Fallback: build a real minimal .xlsx (SpreadsheetML in a ZIP). CSV
        # bytes under an .xlsx name are not a workbook — Excel refuses them,
        # and openpyxl is absent on 3.15t, so this is the shipped path there.

        categories = ["Personnel", "Equipment", "Travel", "Supplies", "Other", "Indirect Costs"]
        rows: list[list[Any]] = [
            ["Grant Budget"],
            [f"Proposal: {input.proposal.title}"],
            [f"PI: {input.pi_profile.name}"],
            [f"Funder: {input.rfp.funder_id}"],
            [],
            ["Category", "Amount"],
        ]
        # Blank, not 0: an unfilled row must not read as a $0 allocation.
        rows.extend([[cat] for cat in categories])
        rows.append(["Total"])
        rows.append([])
        rows.append([self._budget_note(input)])
        rows.append([self._ceiling_note(input)])

        def _cell(col: str, row_num: int, value: Any) -> str:
            ref = f"{col}{row_num}"
            if isinstance(value, str):
                return f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'
            return f'<c r="{ref}"><v>{value}</v></c>'

        sheet_rows = []
        for row_num, values in enumerate(rows, start=1):
            cells = "".join(_cell(chr(ord("A") + i), row_num, v) for i, v in enumerate(values))
            sheet_rows.append(f'<row r="{row_num}">{cells}</row>')

        main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        pkg_rel = "http://schemas.openxmlformats.org/package/2006/relationships"
        sheet = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<worksheet xmlns="{main}"><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
        )

        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml",
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                        '<Default Extension="xml" ContentType="application/xml"/>'
                        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                        '</Types>')
            zf.writestr("_rels/.rels",
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        f'<Relationships xmlns="{pkg_rel}">'
                        f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/>'
                        '</Relationships>')
            zf.writestr("xl/workbook.xml",
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        f'<workbook xmlns="{main}" xmlns:r="{rel}">'
                        '<sheets><sheet name="Budget" sheetId="1" r:id="rId1"/></sheets></workbook>')
            zf.writestr("xl/_rels/workbook.xml.rels",
                        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        f'<Relationships xmlns="{pkg_rel}">'
                        f'<Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/>'
                        '</Relationships>')
            zf.writestr("xl/worksheets/sheet1.xml", sheet)
        return buffer.getvalue()

    def _deadline_line(self, input: Any) -> str:
        deadline = getattr(input.rfp, "deadline", None)
        if deadline is None:
            return "Deadline: not stated in the RFP"
        return f"Deadline: {deadline}"

    def _budget_note(self, input: Any) -> str:
        return (
            "Amounts are entered from the budget justification; grantforge does "
            "not generate budget figures."
        )

    def _ceiling_note(self, input: Any) -> str:
        ceiling = getattr(input.rfp, "max_amount", None)
        if ceiling:
            return f"Award ceiling stated in the RFP: ${ceiling:,.0f}"
        return "Award ceiling not stated in the RFP"

    def _get_template(self, funder: str) -> dict[str, Any]:
        return self.TEMPLATES.get(funder.lower(), self.TEMPLATES["foundation"])

    async def health_check(self) -> dict[str, Any]:
        base = await super().health_check()
        base["reportlab"] = "unknown"
        base["python-docx"] = "unknown"
        base["openpyxl"] = "unknown"
        return base