# Contributing to pyGAEB

Thank you for considering contributing to pyGAEB! This guide will help you get started.

## Licence Agreement

By submitting a pull request you agree that your contributions are licensed under the MIT License and that the project maintainers retain the right to relicence the project under alternative terms.

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
