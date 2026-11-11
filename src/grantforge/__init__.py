"""
grantforge — AI-native grant tooling (Scribe v2)
Single binary via Nuitka: discover → assess → draft → review → collaborate → export → submit
"""

__version__ = "2.0.1"
__author__ = "Azazael"

from grantforge.discovery import DiscoveryEngine
from grantforge.eligibility import EligibilityEngine
from grantforge.drafting import DraftingEngine
from grantforge.compliance import ComplianceEngine
from grantforge.collaboration import CollaborationEngine
from grantforge.export import ExportEngine

__all__ = [
    "DiscoveryEngine",
    "EligibilityEngine", 
    "DraftingEngine",
    "ComplianceEngine",
    "CollaborationEngine",
    "ExportEngine",
]