# Contributing

Thanks for taking an interest in GrantForge. It is part of the
[Azazael](https://github.com/myzticalbabe) ecosystem, a set of repositories for
education and research tooling.

## What this project is

GrantForge is a Python command-line toolkit for the proposal-writing workflow:
discover funding opportunities, assess eligibility against an RFP, draft proposal
sections, run a compliance review, co-edit a proposal, and export the result to PDF,
Word or Excel. The engines are deterministic and rule-based — see the
[Overview](README.md#overview) for exactly what does and does not work today.

## Before you start

- Read the project `README.md` for what the repository actually does and how to run it.
- Search the existing issues and pull requests — the change you want may already be
  discussed.
- For anything larger than a typo or a one-line fix, open an issue first so the design
  can be agreed before code is written.

## Setup

GrantForge requires **Python 3.13 or newer** (`pyproject.toml` declares
`requires-python = ">=3.13"`).

```bash
git clone https://github.com/myzticalbabe/grantforge.git
cd grantforge
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e ".[test]"
```

`madi` — the browsing instrument GrantForge depends on — is not on PyPI yet, so the
resolver cannot see it. Install it from its repository first, exactly as CI does:

```bash
pip install "git+https://github.com/myzticalbabe/madi.git@v0.1.0"
```

Run that line **before** `pip install -e ".[test]"`. Without it the install fails
with `No matching distribution found for madi`.

## Running it

```bash
python -m grantforge --help      # or: grantforge --help, after install
python -m grantforge health      # probe every engine and print a table
python -m grantforge version
```

## Running the tests

```bash
python -m pytest tests/ -q
```

That is the same command CI runs (`.github/workflows/ci.yml`). The suite is
self-contained: `tests/conftest.py` puts `src/` at the front of `sys.path`, so you do
not need an installed copy for the tests to exercise your working tree.

## Checks CI runs

The `ci` workflow (`.github/workflows/ci.yml`) does three things, in order:

1. installs the package and its test extras;
2. runs `python -m pytest tests/ -v --tb=short`;
3. runs a type check when `pyproject.toml` declares `basedpyright` or `pyright`.

If a check cannot run in your environment, say so in the pull request instead of
deleting the step. A removed step is a check that no longer exists.

## Ways to contribute that are not code

- Report a bug with a minimal reproduction.
- Improve the documentation or add an example.
- Report an accessibility problem (keyboard traps, missing text alternatives,
  unreadable contrast).
- Review a pull request and say what confused you — that is real feedback.

## Making a change

1. Fork the repository and create a branch: `git checkout -b fix/short-description`.
2. Keep the change focused. Unrelated refactors belong in a separate pull request.
3. Match the surrounding style; do not reformat whole files to make a small fix.
4. Run `python -m pytest tests/ -q` before you open the pull request.
5. Write a commit message that explains *why* the change was made.
6. Open the pull request and fill in the template.

## Reporting bugs

Open an issue using the **Bug report** template in this repository. A good report
contains:

- what you expected to happen and what happened instead;
- the exact command, page, or input that triggers it;
- the full error output, not a paraphrase;
- your operating system, Python version, and the GrantForge version
  (`python -m grantforge version`).

Security vulnerabilities must **not** be filed as issues. Follow
[SECURITY.md](SECURITY.md) instead.

## Learner-facing content

This repository is a command-line toolkit and holds no learner-facing web material
today. If a change adds documentation examples, a page, or any material intended for
students — including girls aged 8–13 who are new to computing — then:

- keep the reading level age-appropriate and define any new term the first time it is
  used;
- keep the layout keyboard-navigable and give every image or canvas a text alternative;
- avoid examples that assume prior exposure to programming.

## Code of conduct

Participation is covered by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Be kind; assume
good faith. Reports can be made privately — see the enforcement section for the
private channel.

## Licence

By contributing you agree that your contribution is licensed under the same licence as
the repository: the **SOUL FORGE License v1.0**. See [LICENSE](LICENSE).
