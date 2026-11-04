"""
grantforge CLI — Main entry point for grantforge.exe
Commands: discover, assess, draft, review, collaborate, export, submit
"""

from __future__ import annotations
import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from grantforge import (
    DiscoveryEngine,
    EligibilityEngine,
    DraftingEngine,
    ComplianceEngine,
    CollaborationEngine,
    ExportEngine,
)
from grantforge.schemas import (
    Profile, RFP, Funder, Proposal, 
    FunderType, GrantMechanism, ExportFormat
)

app = typer.Typer(
    name="grantforge",
    help="AI-native grant tooling: discover → assess → draft → review → collaborate → export → submit",
    rich_markup_mode="rich",
)
console = Console()

# Global engines (initialized lazily)
_discovery: DiscoveryEngine | None = None
_eligibility: EligibilityEngine | None = None
_drafting: DraftingEngine | None = None
_compliance: ComplianceEngine | None = None
_collaboration: CollaborationEngine | None = None
_export: ExportEngine | None = None


def get_discovery() -> DiscoveryEngine:
    global _discovery
    if _discovery is None:
        _discovery = DiscoveryEngine()
    return _discovery


def get_eligibility() -> EligibilityEngine:
    global _eligibility
    if _eligibility is None:
        _eligibility = EligibilityEngine()
    return _eligibility


def get_drafting() -> DraftingEngine:
    global _drafting
    if _drafting is None:
        _drafting = DraftingEngine()
    return _drafting


def get_compliance() -> ComplianceEngine:
    global _compliance
    if _compliance is None:
        _compliance = ComplianceEngine()
    return _compliance


def get_collaboration() -> CollaborationEngine:
    global _collaboration
    if _collaboration is None:
        _collaboration = CollaborationEngine()
    return _collaboration


def get_export() -> ExportEngine:
    global _export
    if _export is None:
        _export = ExportEngine()
    return _export


@app.command()
def discover(
    query: Annotated[str, typer.Argument(help="Search query for funding opportunities")] = "",
    rfp_file: Annotated[Path | None, typer.Option("--rfp", help="RFP PDF/text file to ingest")] = None,
    funder_ein: Annotated[str | None, typer.Option("--funder", help="Funder EIN for intelligence")] = None,
    top_k: Annotated[int, typer.Option("--top", help="Number of results")] = 10,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output JSON file")] = None,
):
    """Discover funding opportunities, ingest RFPs, get funder intelligence, build profiles."""
    engine = get_discovery()
    
    if rfp_file:
        text = rfp_file.read_text(encoding="utf-8")
        result = asyncio.run(engine.execute(
            engine.__annotations__["execute"].__args__[0](
                rfp_text=text, top_k=top_k
            )
        ))
    elif funder_ein:
        result = asyncio.run(engine.execute(
            engine.__annotations__["execute"].__args__[0](
                funder_ein=funder_ein
            )
        ))
    elif query:
        result = asyncio.run(engine.execute(
            engine.__annotations__["execute"].__args__[0](
                query=query, top_k=top_k
            )
        ))
    else:
        console.print("[red]Provide --rfp, --funder, or a search query[/red]")
        raise typer.Exit(1)

    if output:
        output.write_text(result.model_dump_json(indent=2))
        console.print(f"[green]Results written to {output}[/green]")
    else:
        console.print_json(result.model_dump_json(indent=2))


@app.command()
def assess(
    rfp_file: Annotated[Path, typer.Argument(help="RFP file (JSON)")],
    profile_file: Annotated[Path, typer.Argument(help="Profile file (JSON)")],
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output JSON file")] = None,
):
    """Assess eligibility for a profile against an RFP."""
    engine = get_eligibility()
    
    rfp = RFP.model_validate_json(rfp_file.read_text())
    profile = Profile.model_validate_json(profile_file.read_text())
    
    result = asyncio.run(engine.execute(
        engine.__annotations__["execute"].__args__[0](rfp=rfp, profile=profile)
    ))
    
    if output:
        output.write_text(result.model_dump_json(indent=2))
        console.print(f"[green]Assessment written to {output}[/green]")
    else:
        console.print_json(result.model_dump_json(indent=2))
    
    # Print summary
    if result.assessment:
        table = Table(title="Eligibility Assessment")
        table.add_column("Criterion")
        table.add_column("Verdict")
        table.add_column("Reason")
        for check in result.assessment.checks:
            table.add_row(
                check.category.value,
                check.verdict.value,
                check.reason
            )
        console.print(table)
        console.print(f"\n[bold]Overall: {result.assessment.overall.value}[/bold]")


@app.command()
def draft(
    rfp_file: Annotated[Path, typer.Argument(help="RFP file (JSON)")],
    profile_file: Annotated[Path, typer.Argument(help="Profile file (JSON)")],
    proposal_file: Annotated[Path | None, typer.Option("--proposal", "-p", help="Existing proposal to modify")] = None,
    section: Annotated[str | None, typer.Option("--section", "-s", help="Section ID to draft/revise")] = None,
    instruction: Annotated[str | None, typer.Option("--instruction", "-i", help="Instruction: draft, revise, expand, condense")] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output proposal JSON file")] = None,
):
    """Draft or revise proposal sections from RFP + profile."""
    engine = get_drafting()
    
    rfp = RFP.model_validate_json(rfp_file.read_text())
    profile = Profile.model_validate_json(profile_file.read_text())
    proposal = Proposal.model_validate_json(proposal_file.read_text()) if proposal_file else None
    
    result = asyncio.run(engine.execute(
        engine.__annotations__["execute"].__args__[0](
            rfp=rfp,
            profile=profile,
            proposal=proposal,
            section_id=section,
            instruction=instruction,
        )
    ))
    
    if output and result.proposal:
        output.write_text(result.proposal.model_dump_json(indent=2))
        console.print(f"[green]Proposal written to {output}[/green]")
    elif result.section:
        console.print(f"[bold]{result.section.title}[/bold]")
        console.print(result.section.content)
    else:
        console.print_json(result.model_dump_json(indent=2))


@app.command()
def review(
    proposal_file: Annotated[Path, typer.Argument(help="Proposal file (JSON)")],
    profile_file: Annotated[Path, typer.Argument(help="PI profile file (JSON)")],
    checks: Annotated[list[str], typer.Option("--check", help="Check types to run")] = ["eligibility", "budget", "format", "ethics", "coi"],
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output JSON file")] = None,
):
    """Run compliance review on proposal."""
    engine = get_compliance()
    
    proposal = Proposal.model_validate_json(proposal_file.read_text())
    profile = Profile.model_validate_json(profile_file.read_text())
    
    result = asyncio.run(engine.execute(
        engine.__annotations__["execute"].__args__[0](
            proposal=proposal,
            pi_profile=profile,
            check_types=checks,
        )
    ))
    
    if output:
        output.write_text(result.model_dump_json(indent=2))
        console.print(f"[green]Review written to {output}[/green]")
    else:
        console.print_json(result.model_dump_json(indent=2))
    
    if result.checks:
        table = Table(title="Compliance Checks")
        table.add_column("Check")
        table.add_column("Pass")
        table.add_column("Verdict")
        for k, v in result.checks.items():
            table.add_row(k, "✅" if v.get("pass") else "❌", v.get("verdict", "-"))
        console.print(table)
        console.print(f"\n[bold]Overall: {'PASS' if result.overall_pass else 'FAIL'}[/bold]")


@app.command()
def collaborate(
    proposal_file: Annotated[Path, typer.Argument(help="Proposal file (JSON)")],
    action: Annotated[str, typer.Argument(help="Action: edit, comment, request, assign, move")],
    user: Annotated[str, typer.Option("--user", "-u", help="User ID")],
    section: Annotated[str | None, typer.Option("--section", "-s", help="Section ID")] = None,
    content: Annotated[str | None, typer.Option("--content", "-c", help="Edit content or comment text")] = None,
    target: Annotated[str | None, typer.Option("--target", "-t", help="Target user for request/assign")] = None,
    position: Annotated[int | None, typer.Option("--position", help="Position for edit")] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output proposal JSON file")] = None,
):
    """Collaborate on proposal: co-edit, comment, request info, assign, move."""
    engine = get_collaboration()
    
    proposal = Proposal.model_validate_json(proposal_file.read_text())
    
    result = asyncio.run(engine.execute(
        engine.__annotations__["execute"].__args__[0](
            proposal=proposal,
            action=action,
            user_id=user,
            section_id=section,
            content=content,
            target_user=target,
            position=position,
        )
    ))
    
    if output and result.proposal:
        output.write_text(result.proposal.model_dump_json(indent=2))
        console.print(f"[green]Proposal written to {output}[/green]")
    else:
        console.print_json(result.model_dump_json(indent=2))


@app.command()
def export(
    proposal_file: Annotated[Path, typer.Argument(help="Proposal file (JSON)")],
    profile_file: Annotated[Path, typer.Argument(help="PI profile file (JSON)")],
    rfp_file: Annotated[Path, typer.Argument(help="RFP file (JSON)")],
    formats: Annotated[list[ExportFormat], typer.Option("--format", "-f", help="Export formats")] = [ExportFormat.PDF, ExportFormat.WORD, ExportFormat.EXCEL],
    template: Annotated[str | None, typer.Option("--template", "-t", help="Funder template: nih, nsf, doe, foundation")] = None,
    out_dir: Annotated[Path, typer.Option("--out-dir", "-d", help="Output directory")] = Path("./export"),
):
    """Export proposal to PDF, Word, Excel, or complete submission bundle."""
    engine = get_export()
    
    proposal = Proposal.model_validate_json(proposal_file.read_text())
    profile = Profile.model_validate_json(profile_file.read_text())
    rfp = RFP.model_validate_json(rfp_file.read_text())
    
    out_dir.mkdir(parents=True, exist_ok=True)
    
    result = asyncio.run(engine.execute(
        engine.__annotations__["execute"].__args__[0](
            proposal=proposal,
            pi_profile=profile,
            rfp=rfp,
            formats=formats,
            funder_template=template,
        )
    ))
    
    if result.bundle:
        # Write all files
        for filename, content in result.files.items():
            (out_dir / filename).write_bytes(content)
        
        # Write manifest
        (out_dir / "MANIFEST.json").write_text(
            json.dumps(result.bundle.manifest, indent=2)
        )
        
        console.print(f"[green]Export complete: {out_dir}[/green]")
        for f in out_dir.iterdir():
            console.print(f"  {f.name} ({f.stat().st_size} bytes)")
    else:
        console.print("[red]Export failed[/red]")


@app.command()
def health():
    """Check health of all engines."""
    async def check_all():
        engines = [
            ("discovery", get_discovery()),
            ("eligibility", get_eligibility()),
            ("drafting", get_drafting()),
            ("compliance", get_compliance()),
            ("collaboration", get_collaboration()),
            ("export", get_export()),
        ]
        
        table = Table(title="Engine Health")
        table.add_column("Engine")
        table.add_column("Status")
        table.add_column("Details")
        
        for name, engine in engines:
            result = await engine.health_check()
            table.add_row(
                name,
                "[green]healthy[/green]" if result.get("status") == "healthy" else "[red]unhealthy[/red]",
                str(result)
            )
        
        console.print(table)
    
    asyncio.run(check_all())


@app.command()
def version():
    """Show grantforge version."""
    from grantforge import __version__
    console.print(f"grantforge v{__version__}")


if __name__ == "__main__":
    app()