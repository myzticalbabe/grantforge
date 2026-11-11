# grantforge — AI-Native Grant Tooling (Scribe v2)

**Single binary. Zero dependencies. NPU-accelerated. Dual-model consensus.**

```
grantforge discover "NSF early career quantum computing"
grantforge assess rfp.json profile.json
grantforge draft rfp.json profile.json --output proposal.json
grantforge review proposal.json profile.json
grantforge collaborate proposal.json edit --user alice --section methods --content "We propose..."
grantforge export proposal.json profile.json rpf.json --format pdf,docx,xlsx
```

---

## What It Does

| Command | Purpose | AI Capability |
|---------|---------|---------------|
| `discover` | Semantic funding search, RFP ingestion, funder 990 intel, auto-profiles | mxbai-embed-large-v1 on **NPU** (5.7x faster than CPU) |
| `assess` | Full eligibility verdict per criterion (career stage, citizenship, ESI, prior funding, mechanism limits) | Structured extraction + profile matching |
| `draft` | Checklist-driven section drafting, content library, style guide enforcement, inline AI, voice learning | **Dual-model consensus** (gemma4 reasoning + qwen3 code) |
| `review` | Compliance checks via supervisor_verdict fanout (PMB + Engram + PAMS), DLV dual-ledger audit trail | Multi-memory consensus |
| `collaborate` | Real-time co-editing (Operational Transform), anchor comments, SME info requests, kanban pipeline | Conflict-free collaborative editing |
| `export` | Funder-specific templates (NIH/NSF/DOE/Foundation) → PDF/Word/Excel + complete submission bundle | One-click formatted output |

---

## Architecture

```
grantforge.exe (Nuitka single binary ~200MB)
├── grantforge/
│   ├── discovery/      # NPU embeddings, RFP parsing, funder 990s, auto-profiles
│   ├── eligibility/    # Criterion extraction, per-criterion verdicts
│   ├── drafting/       # Checklist → sections → library → inline AI → voice
│   ├── compliance/     # supervisor_verdict fanout + DLV audit
│   ├── collaboration/  # OT co-editing, comments, requests, kanban
│   └── export/         # NIH/NSF/DOE templates → PDF/Word/Excel
├── llama-server/
│   ├── ov_embed_server.py   # NPU mxbai embeddings (OpenVINO)
│   ├── codegraph_mcp.py     # Tree-sitter codegraph tools
│   └── executor.py          # Unified EngineExecutor plugins
└── DirectMemory/            # Session recording + PMB/Engram/PAMS bridge
```

---

## Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 8 cores | 16+ cores (free-threaded Python 3.14t) |
| RAM | 16 GB | 32+ GB |
| NPU | Intel AI Boost / Arc 140T | Intel Core Ultra (NPU 40+ TOPS) |
| GPU | Optional (OpenVINO GPU fallback) | Arc 140T / discrete for fallback |
| Storage | 5 GB | 20+ GB (models + cache) |

**NPU required for mxbai embeddings at speed.** CPU fallback: 4.7 chunks/s vs NPU 26.9 chunks/s.

---

## Installation

Installable today, no index needed — Madi first, then the tool:

```bash
pip install https://github.com/myzticalbabe/madi/releases/download/v0.1.0/madi-0.1.0-py3-none-any.whl
pip install https://github.com/myzticalbabe/grantforge/releases/download/v2.0.0/grantforge-2.0.0-py3-none-any.whl

# or straight from the repository, with the browser rung
pip install "grantforge[browser] @ git+https://github.com/myzticalbabe/grantforge.git@v2.0.0"
```

From source:

```bash
git clone https://github.com/myzticalbabe/grantforge
cd grantforge
pip install -e ".[dev]"
playwright install chromium          # only for the render rung
```

`pip install grantforge` works once the PyPI trusted publisher exists; the publish
workflow is gated on the repository variable `PYPI_TRUSTED_PUBLISHER` so a tag that
cannot publish leaves a green repository rather than a red X.

---

## Quick Start

```bash
# 1. Start NPU embedding server (separate terminal)
python -m llama_server.unified.ov_embed_server --device NPU --port 18083

# 2. Discover opportunities
grantforge discover "NIH R01 early career cancer immunotherapy" --top 5 --output results.json

# 3. Ingest an RFP
grantforge discover --rfp nih_rfa.pdf --output rfp.json

# 4. Build your profile (auto from ORCID)
grantforge discover --profile orcid:0000-0000-0000-0000 --output profile.json

# 5. Assess eligibility
grantforge assess rfp.json profile.json --output assessment.json

# 6. Draft proposal
grantforge draft rfp.json profile.json --output proposal.json

# 7. Compliance review
grantforge review proposal.json profile.json

# 8. Collaborate (real-time co-editing)
grantforge collaborate proposal.json edit --user alice --section "approach" --content "We will..."

# 9. Export for submission
grantforge export proposal.json profile.json rfp.json --format pdf,docx,xlsx --template nih
```

---

## Configuration

Environment variables (or `.env`):
```bash
# NPU Embedding Server
OV_EMBED_URL=http://127.0.0.1:18083/v1/embeddings
OV_DEVICE=NPU  # or GPU, CPU

# LLM Servers (for drafting/eligibility)
GEMMA4_URL=http://127.0.0.1:18090/v1
QWEN3_URL=http://127.0.0.1:18091/v1

# Memory/Compliance
PMB_HOME=C:/Users/you/.pmb
ENGRAM_PROJECT=my_grants
DIRECTMEMORY_PATH=C:/Users/you/.directmemory

# Playwright
PLAYWRIGHT_BROWSERS_PATH=0  # Use bundled
```

---

## Models

| Model | Purpose | Hardware |
|-------|---------|----------|
| `mxbai-embed-large-v1` | Embeddings (discovery) | **NPU** (OpenVINO) |
| `gemma-4` | Reasoning (drafting, eligibility) | CPU/GPU (llama.cpp) |
| `qwen3` | Code/structure (drafting, compliance) | CPU/GPU (llama.cpp) |

**Dual-model consensus**: Both models must agree on key findings; disagreements flagged for human review.

---

## Compliance & Audit

Every decision recorded to **DLV dual-ledger**:
- **DirectMemory** (WAL, session-scoped)
- **.audit/anchors.jsonl** (Merkle roots, tamper-evident)

```bash
# Verify audit trail
grantforge review --audit-verify proposal.json
```

---

## Development

```bash
# Run tests
pytest tests/ -v

# Type check
mypy src/grantforge

# Lint
ruff check src/grantforge

# Contract tests (per engine)
pytest tests/contracts/ -v
```

### Engine Contract Tests

Each engine has contract tests verifying:
- Input/output schema compliance
- Error handling
- Health check responses
- Performance budgets (<5s discovery, <3s eligibility, <10s draft)

---

## License

Apache-2.0 — See [LICENSE](LICENSE)

---

## Citation

```bibtex
@software{grantforge,
  title = {grantforge: AI-Native Grant Tooling},
  author = {Azazael},
  year = {2026},
  version = {2.0.0},
  url = {https://github.com/azazael/grantforge}
}
```

---

**Built on Azazael stack**: DirectMemory, PMB, Engram, PAMS, ComplianceOrchestrator, llama.cpp, OpenVINO, Nuitka.