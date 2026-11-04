"""
grantforge config — model/output paths, service endpoints, funder templates.

Every value is read from the environment at import time. No credentials are
kept here: the endpoints are local services, and a key belongs in the
environment of whoever runs them, not in a module constant.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any

# Default paths (relative to CWD, overridable via env)
DEFAULT_MODEL_DIR = Path(os.environ.get("GRANTFORGE_MODEL_DIR", "models"))
DEFAULT_OUTPUT_DIR = Path(os.environ.get("GRANTFORGE_OUTPUT_DIR", "output"))
DEFAULT_TEMPLATE_DIR = Path(os.environ.get("GRANTFORGE_TEMPLATE_DIR", "templates"))

# Model endpoints
OV_EMBED_URL = os.environ.get("GRANTFORGE_OV_EMBED_URL", "http://127.0.0.1:18083/v1/embeddings")
LLM_URL = os.environ.get("GRANTFORGE_LLM_URL", "http://127.0.0.1:18090/v1/chat/completions")

# Funder templates
FUNDER_TEMPLATES = ["nih", "nsf", "doe", "foundation"]

# Export formats
DEFAULT_EXPORT_FORMATS = ["pdf", "docx", "xlsx"]


def get_config() -> dict[str, Any]:
    """Return the current configuration."""
    return {
        "model_dir": str(DEFAULT_MODEL_DIR),
        "output_dir": str(DEFAULT_OUTPUT_DIR),
        "template_dir": str(DEFAULT_TEMPLATE_DIR),
        "ov_embed_url": OV_EMBED_URL,
        "llm_url": LLM_URL,
        "funder_templates": FUNDER_TEMPLATES,
        "export_formats": DEFAULT_EXPORT_FORMATS,
    }