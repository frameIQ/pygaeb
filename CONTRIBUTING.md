# Contributing to pyGAEB

Thank you for considering contributing to pyGAEB!

## Development Setup

```bash
# Clone the repository
git clone https://github.com/frameiq/pygaeb.git
cd pygaeb

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install in development mode with all extras
pip install -e ".[llm,dev]"

# Run tests
pytest

# Run type checks
mypy pygaeb

# Run linter
ruff check pygaeb
```

## Guidelines

- All public API functions and classes must have type annotations
- Use `Decimal` for all monetary and quantity values — never `float`
- New parser features need corresponding test cases
- Follow the existing code style (enforced by ruff)
- Add entries to CHANGELOG.md for user-facing changes

## Test Corpus

If you have access to real GAEB files, contributions to the test corpus are
especially valuable. Please ensure files do not contain confidential project data
before submitting.

## Architecture

See `pygaeb_roadmap.md` for the complete development roadmap and architecture
documentation.
