# Contributing to pyGAEB

Thank you for considering contributing to pyGAEB! This guide will help you get started.

## Contributor License Agreement (CLA)

Before your first contribution can be merged, you must sign the
[pyGAEB Contributor License Agreement](CLA.md). It confirms you have the right to
contribute your work and grants FrameIQ a broad licence to your contribution —
including the right to offer the Project under multiple licences (open-source and
commercial). **You keep full ownership of your contributions.**

Signing is automated: when you open your first pull request, the CLA assistant bot
will post a one-time link/comment to sign. You only sign once, and it covers all
your future contributions. Contributing on behalf of a company? See the Corporate
section of [CLA.md](CLA.md).

## Development Setup

```bash
git clone https://github.com/frameiq/pygaeb.git
cd pygaeb
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,llm]"
```

## Running Tests

```bash
pytest -v
```

## Code Quality

We enforce the following in CI — please run these locally before pushing:

```bash
ruff check pygaeb/ tests/
mypy pygaeb/
```

All code must pass ruff with the rules configured in `pyproject.toml` and mypy in strict mode.

## Pull Request Guidelines

1. **Create a branch** from `main` for your changes
2. **Write tests** for any new functionality
3. **Run the full suite** (`pytest -v`, `ruff check`, `mypy`) before opening a PR
4. **Keep PRs focused** — one feature or fix per PR
5. **Update documentation** if you change public API surface

## Reporting Issues

Open an issue on GitHub with:

- A clear title and description
- Minimal reproduction steps (ideally a sample GAEB file or XML snippet)
- Python version and pyGAEB version (`python -c "import pygaeb; print(pygaeb.__version__)"`)
