# Installation

## Core Library

The core library handles parsing, validation, writing, and export with no LLM dependencies:

```bash
pip install pyGAEB
```

This installs the parser, writer, validator, and JSON/CSV export — everything you need to work with GAEB files programmatically.

## With LLM Classification

To use the LLM-powered classification and structured extraction features, install the `llm` extra:

```bash
pip install pyGAEB[llm]
```

This adds [LiteLLM](https://github.com/BerriAI/litellm) (100+ LLM providers) and [Instructor](https://github.com/jxnl/instructor) (structured LLM output).

## Development Setup

For contributing or running the test suite:

```bash
git clone https://github.com/frameiq/pygaeb.git
cd pygaeb
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,llm]"
```

Run the tests:

```bash
pytest -v
```

## Building Documentation Locally

```bash
pip install -e ".[docs]"
mkdocs serve
```

Then open [http://localhost:8000](http://localhost:8000).

## Requirements

- **Python 3.9+**
- Core dependencies: `lxml`, `pydantic` v2, `beautifulsoup4`, `ftfy`, `charset-normalizer`
- LLM extras: `litellm`, `instructor`

## LLM Provider Setup

pyGAEB uses LiteLLM under the hood, so any provider that LiteLLM supports works out of the box. Set the appropriate API key as an environment variable:

```bash
# Anthropic
export ANTHROPIC_API_KEY=sk-ant-...

# OpenAI
export OPENAI_API_KEY=sk-...

# Local (Ollama) — no key needed
ollama pull llama3
```

Then pass the model name when creating a classifier:

```python
from pygaeb import LLMClassifier

classifier = LLMClassifier(model="anthropic/claude-sonnet-4-6")
# or: LLMClassifier(model="gpt-4o")
# or: LLMClassifier(model="ollama/llama3")  # local, free, private
```

See the [LiteLLM docs](https://docs.litellm.ai/docs/providers) for the full provider list.
