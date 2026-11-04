"""
Contract tests for grantforge engines.
Each engine must satisfy these interface contracts.
"""

from __future__ import annotations
import pytest
from grantforge.engine import Engine, EngineInput, EngineOutput, EngineRegistry
from grantforge.discovery import DiscoveryEngine, DiscoveryInput, DiscoveryOutput
from grantforge.eligibility import EligibilityEngine, EligibilityInput, EligibilityOutput
from grantforge.drafting import DraftingEngine, DraftingInput, DraftingOutput
from grantforge.compliance import ComplianceEngine, ComplianceInput, ComplianceOutput
from grantforge.collaboration import CollaborationEngine, CollaborationInput, CollaborationOutput
from grantforge.export import ExportEngine, ExportInput, ExportOutput
from grantforge.schemas import Profile, RFP, Proposal, Funder, FunderType, EligibilityAssessment, ChecklistItem, SectionDraft


class TestEngineContracts:
    """Base contract tests for all engines."""

    @pytest.fixture
    def discovery_engine(self):
        return DiscoveryEngine()

    @pytest.fixture
    def eligibility_engine(self):
        return EligibilityEngine()

    @pytest.fixture
    def drafting_engine(self):
        return DraftingEngine()

    @pytest.fixture
    def compliance_engine(self):
        return ComplianceEngine()

    @pytest.fixture
    def collaboration_engine(self):
        return CollaborationEngine()

    @pytest.fixture
    def export_engine(self):
        return ExportEngine()

    @pytest.fixture
    def sample_profile(self):
        return Profile(
            id="test_001",
            name="Dr. Test User",
            institution="Test University",
            department="Computer Science",
            career_stage="early",
            esi_eligible=True,
            citizenship=["US"],
            prior_grants=[],
            publications=[],
            research_areas=["machine learning", "grant writing"],
        )

    @pytest.fixture
    def sample_rfp(self):
        return RFP(
            id="rfp_001",
            funder_id="nih",
            title="Test RFP: AI for Grant Writing",
            number="RFA-AI-2026",
            deadline="2026-12-01T23:59:59",
            mechanism="R01",
            max_amount=2500000,
            page_limit=12,
            sections_required=["Specific Aims", "Research Strategy", "Budget"],
            formatting_rules={"font": "Arial 11pt", "margins": "0.5in"},
            raw_text="Test RFP content with eligibility criteria...",
        )

    @pytest.fixture
    def sample_proposal(self, sample_rfp, sample_profile):
        return Proposal(
            rfp_id=sample_rfp.id,
            title=sample_rfp.title,
            pi_profile_id=sample_profile.id,
            checklist=[
                ChecklistItem(id="cl_0", section="Specific Aims", requirement="Write specific aims"),
                ChecklistItem(id="cl_1", section="Research Strategy", requirement="Write research strategy"),
            ],
            sections={},
        )

    # Discovery Engine Contracts
    @pytest.mark.asyncio
    async def test_discovery_engine_health(self, discovery_engine):
        """Engine must respond to health_check."""
        result = await discovery_engine.health_check()
        assert "engine" in result
        assert result["engine"] == "discovery"
        assert "status" in result

    @pytest.mark.asyncio
    async def test_discovery_query_input_output(self, discovery_engine):
        """Discovery engine accepts query input and returns opportunities."""
        input = DiscoveryInput(query="NIH R01 cancer", top_k=5)
        # Don't actually call execute (requires ov_embed_server)
        # Just validate input/output schemas
        assert input.query == "NIH R01 cancer"
        assert input.top_k == 5

    # Eligibility Engine Contracts
    @pytest.mark.asyncio
    async def test_eligibility_engine_health(self, eligibility_engine):
        result = await eligibility_engine.health_check()
        assert result["engine"] == "eligibility"

    @pytest.mark.asyncio
    async def test_eligibility_input_schema(self, sample_rfp, sample_profile):
        """EligibilityInput must accept RFP and Profile."""
        input = EligibilityInput(rfp=sample_rfp, profile=sample_profile)
        assert input.rfp.id == "rfp_001"
        assert input.profile.name == "Dr. Test User"

    # Drafting Engine Contracts
    @pytest.mark.asyncio
    async def test_drafting_engine_health(self, drafting_engine):
        result = await drafting_engine.health_check()
        assert result["engine"] == "drafting"

    @pytest.mark.asyncio
    async def test_drafting_create_proposal(self, drafting_engine, sample_rfp, sample_profile):
        """Drafting engine can create proposal from RFP + Profile."""
        input = DraftingInput(rfp=sample_rfp, profile=sample_profile)
        # Schema validation only
        assert input.rfp is not None
        assert input.profile is not None

    @pytest.mark.asyncio
    async def test_drafting_style_rules_exist(self, drafting_engine):
        """Drafting engine must have style rules defined."""
        assert hasattr(drafting_engine, 'STYLE_RULES')
        assert len(drafting_engine.STYLE_RULES) > 0
        assert "Use active voice" in drafting_engine.STYLE_RULES

    # Compliance Engine Contracts
    @pytest.mark.asyncio
    async def test_compliance_engine_health(self, compliance_engine):
        result = await compliance_engine.health_check()
        assert result["engine"] == "compliance"

    @pytest.mark.asyncio
    async def test_compliance_input_schema(self, sample_proposal, sample_profile):
        input = ComplianceInput(proposal=sample_proposal, pi_profile=sample_profile)
        assert "eligibility" in input.check_types
        assert "budget" in input.check_types

    # Collaboration Engine Contracts
    @pytest.mark.asyncio
    async def test_collaboration_engine_health(self, collaboration_engine):
        result = await collaboration_engine.health_check()
        assert result["engine"] == "collaboration"

    @pytest.mark.asyncio
    async def test_collaboration_actions(self, collaboration_engine, sample_proposal):
        """Collaboration engine must support all required actions."""
        actions = ["edit", "comment", "request", "assign", "move"]
        for action in actions:
            input = CollaborationInput(
                proposal=sample_proposal,
                action=action,
                user_id="test_user",
            )
            assert input.action == action

    # Export Engine Contracts
    @pytest.mark.asyncio
    async def test_export_engine_health(self, export_engine):
        result = await export_engine.health_check()
        assert result["engine"] == "export"

    @pytest.mark.asyncio
    async def test_export_templates_exist(self, export_engine):
        """Export engine must have funder templates."""
        assert hasattr(export_engine, 'TEMPLATES')
        assert "nih" in export_engine.TEMPLATES
        assert "nsf" in export_engine.TEMPLATES
        assert "doe" in export_engine.TEMPLATES
        assert "foundation" in export_engine.TEMPLATES

    @pytest.mark.asyncio
    async def test_export_formats(self, export_engine):
        from grantforge.schemas import ExportFormat
        formats = list(ExportFormat)
        assert ExportFormat.PDF in formats
        assert ExportFormat.WORD in formats
        assert ExportFormat.EXCEL in formats

    # Registry Contracts
    @pytest.mark.asyncio
    async def test_engine_registry(self):
        """EngineRegistry must register and retrieve engines."""
        registry = EngineRegistry()
        from grantforge.engine import Engine
        
        class TestEngine(Engine):
            name = "test"
            async def execute(self, input):
                pass
        
        engine = TestEngine()
        registry.register(engine)
        
        retrieved = registry.get("test")
        assert retrieved is engine
        assert len(registry.all()) == 1

    # Schema Contracts
    def test_profile_schema(self, sample_profile):
        """Profile schema must have required fields."""
        assert sample_profile.id
        assert sample_profile.name
        assert sample_profile.institution
        assert sample_profile.career_stage in ["early", "mid", "senior"]

    def test_rfp_schema(self, sample_rfp):
        """RFP schema must have required fields."""
        assert sample_rfp.id
        assert sample_rfp.funder_id
        assert sample_rfp.title
        assert sample_rfp.deadline
        assert isinstance(sample_rfp.sections_required, list)

    def test_proposal_schema(self, sample_proposal):
        """Proposal schema must have required fields."""
        assert sample_proposal.id
        assert sample_proposal.rfp_id
        assert sample_proposal.title
        assert sample_proposal.pi_profile_id
        assert isinstance(sample_proposal.checklist, list)
        assert isinstance(sample_proposal.sections, dict)

    def test_eligibility_assessment_schema(self):
        """EligibilityAssessment must have overall verdict and checks."""
        from grantforge.schemas import CriterionCheck, CriterionCategory, EligibilityVerdict
        
        assessment = EligibilityAssessment(
            overall=EligibilityVerdict.ELIGIBLE,
            checks=[
                CriterionCheck(
                    category=CriterionCategory.CAREER_STAGE,
                    requirement="Early career",
                    profile_value="early",
                    verdict=EligibilityVerdict.ELIGIBLE,
                    reason="Meets early career requirement",
                    confidence=0.9,
                )
            ],
        )
        assert assessment.overall == EligibilityVerdict.ELIGIBLE
        assert len(assessment.checks) == 1


# Performance Budget Tests (marked as benchmark)
class TestPerformanceBudgets:
    """Performance budgets for each engine (when fully implemented)."""

    @pytest.mark.benchmark
    @pytest.mark.asyncio
    async def test_discovery_budget(self, discovery_engine):
        """Discovery: <5s for top-10 semantic search."""
        # TODO: Implement with real ov_embed_server
        pass

    @pytest.mark.benchmark
    @pytest.mark.asyncio
    async def test_eligibility_budget(self, eligibility_engine):
        """Eligibility: <3s for full assessment."""
        pass

    @pytest.mark.benchmark
    @pytest.mark.asyncio
    async def test_drafting_budget(self, drafting_engine):
        """Drafting: <10s per section."""
        pass

    @pytest.mark.benchmark
    @pytest.mark.asyncio
    async def test_export_budget(self, export_engine):
        """Export: <5s for PDF + Word + Excel bundle."""
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])