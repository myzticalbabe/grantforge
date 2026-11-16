# grantforge

GrantForge — a Python command-line toolkit for the grant proposal workflow: discover, assess, draft, review, collaborate, export.

[![CI](https://github.com/myzticalbabe/grantforge/actions/workflows/ci.yml/badge.svg)](https://github.com/myzticalbabe/grantforge/actions/workflows/ci.yml)
[![Pages Deploy](https://github.com/myzticalbabe/grantforge/actions/workflows/pages-deploy.yml/badge.svg)](https://github.com/myzticalbabe/grantforge/actions/workflows/pages-deploy.yml)
[![License: SOUL FORGE](https://img.shields.io/badge/License-SOUL_FORGE-violet.svg)](LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/myzticalbabe/grantforge)](https://github.com/myzticalbabe/grantforge/releases)
[![GitHub stars](https://img.shields.io/github/stars/myzticalbabe/grantforge?style=social)](https://github.com/myzticalbabe/grantforge/stargazers)

---

## Overview

GrantForge turns an RFP and a candidate profile into a reviewed, exportable proposal
bundle. Six engines do the work:

| Command | Engine | What it does |
|---|---|---|
| `discover` | Discovery | Search funding opportunities, ingest an RFP, look up funder intelligence, build a profile |
| `assess` | Eligibility | Score a profile against an RFP's criteria and return a verdict with reasons |
| `draft` | Drafting | Compose proposal sections from the RFP and the profile |
| `review` | Compliance | Run eligibility, budget, format, ethics and conflict-of-interest checks over a proposal |
| `collaborate` | Collaboration | Edit, comment, request information, assign and reorder proposal sections |
| `export` | Export | Render a proposal to PDF, Word and Excel, plus a submission bundle and manifest |

`python -m grantforge health` probes every engine and prints what is and is not wired
up. GrantForge was split out of [AZAZAEL](https://github.com/myzticalbabe/azazael)
for independent development.

### What it does not do

- **It does not call a language model.** The drafting composer is deterministic
  (`deterministic_scaffold_no_model`): it lays out the sections the RFP asks for and
  marks the gaps for a human to fill in. Draft output is a labelled scaffold, not
  submission-ready prose.
- **It does not submit anything.** There is no `submit` command and nothing is sent to
  a funder. Export writes files to a directory you choose.
- **It does not decide eligibility for you.** The assessment is a rules pass over the
  RFP's own criteria, and it prints the reason for every check so a person can verify
  it.
- The machine-learning dependencies declared in `pyproject.toml` (`torch`,
  `transformers`, `sentence-transformers`, `faiss-cpu`, `llama-cpp-python`) are not
  yet wired into the engines — see the `TODO` notes in
  `src/grantforge/discovery/__init__.py`.
- The discovery engine matches your query against a small built-in catalogue of
  funders by keyword. It says which funder's stated domain overlaps your query; it
  does not say a call is open, because it has no database of open calls.

### Who it is for

- Researchers and research offices who write and submit grant proposals and want a
  repeatable, reviewable draft-and-check workflow instead of a blank document.
- Educators and students who want to read or extend a small, readable pipeline: every
  engine is a plain Python class over a documented contract in
  `src/grantforge/engine.py`, and the test suite is the specification.
- Anyone deciding whether deterministic, auditable tooling fits proposal work better
  than a black-box generator. That trade-off is stated above rather than hidden.

## Installation

Requires **Python 3.13 or newer** (`pyproject.toml` declares `requires-python = ">=3.13"`).

```bash
git clone https://github.com/myzticalbabe/grantforge.git
cd grantforge
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install "git+https://github.com/myzticalbabe/madi.git@v0.1.0"   # not on PyPI yet
pip install -e ".[test]"
```

Install the `madi` line **before** `pip install -e ".[test]"` — `madi` is not on PyPI,
so the resolver cannot satisfy it on its own and the editable install fails with
`No matching distribution found for madi`.

## Usage

```bash
python -m grantforge --help          # or: grantforge --help, after install
python -m grantforge health          # probe every engine
python -m grantforge version
```

Each command takes JSON files in and writes JSON files out:

```bash
grantforge assess rfp.json profile.json -o assessment.json
grantforge draft rfp.json profile.json -o proposal.json
grantforge review proposal.json profile.json
grantforge export proposal.json profile.json rfp.json --out-dir ./export
```

## Running the tests

```bash
python -m pytest tests/ -q
```

This is the same command CI runs. `tests/conftest.py` puts `src/` first on
`sys.path`, so the suite exercises your working tree even without installing the
package.

## Architecture

See [Domain Atlas](https://myzticalbabe.github.io) for interactive visualization.

## License

This project is licensed under the **SOUL FORGE License v1.0** — see [LICENSE](LICENSE) for details.

> *"Code is crystallized intention. Tend the fire."*

## Related Repositories

| Repo | Description |
|------|-------------|
| [azazael](https://github.com/myzticalbabe/azazael) | Monorepo: worm registry, cluster system, agent harness |
| [EveUnleashed](https://github.com/myzticalbabe/EveUnleashed) | Gamora, Lucy, Jaeger, Berzerker AIO native on 3.16t |
| [eliza](https://github.com/myzticalbabe/eliza) | Companion runtime: shards, adopted trees |
| [codex-video-engine](https://github.com/myzticalbabe/codex-video-engine) | CODEX Studio desktop app + video engine |
| [ecosystem-orchestrator](https://github.com/myzticalbabe/ecosystem-orchestrator) | ML platform install/orchestration |
| [scribe](https://github.com/myzticalbabe/scribe) | Documentation generation |
| [persephone-sync](https://github.com/myzticalbabe/persephone-sync) | Cross-platform env sync |
| [hydra-mlcluster](https://github.com/myzticalbabe/hydra-mlcluster) | Adaptive ML cluster processing |
| [flaming-sword](https://github.com/myzticalbabe/flaming-sword) | Defensive instrument: sentinel, compliance, formal verification |
| [shardex](https://github.com/myzticalbabe/shardex) | Shard execution engine |
| [krampus](https://github.com/myzticalbabe/krampus) | Composition: MellifluousML, Madi, Gamora, Eve, Lilith |
| [azazael-core](https://github.com/myzticalbabe/azazael-core) | Installable, interpreter-agnostic repackaging |
| [grantforge](https://github.com/myzticalbabe/grantforge) | AI-native grant tooling |
| [madi](https://github.com/myzticalbabe/madi) | Browsing instrument: fetch, challenge taxonomy, scorer |
| [jaeger](https://github.com/myzticalbabe/jaeger) | Durable spans, JSONL ledger, stdlib only |
| [cradle](https://github.com/myzticalbabe/cradle) | Composition over FLAMING SWORD, REAPER, GRIMOIRE |
| [esquire-admissibility](https://github.com/myzticalbabe/esquire-admissibility) | AI-evidence admissibility gates |
| [nurse-ratchet](https://github.com/myzticalbabe/nurse-ratchet) | Behavioural package: person state modelled |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Links

- **Monorepo**: https://github.com/myzticalbabe/azazael
- **Landing Hub**: https://myzticalbabe.github.io
- **Domain Atlas**: https://myzticalbabe.github.io/index.html
- **Issues**: https://github.com/myzticalbabe/grantforge/issues
- **Discussions**: https://github.com/myzticalbabe/grantforge/discussions