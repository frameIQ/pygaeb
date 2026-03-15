# LLM Classification

pyGAEB can enrich each item with a semantic construction element type using any LLM provider via LiteLLM. Classification is always opt-in — the core parser never requires LLM access.

## Setup

Install the LLM extras:

```bash
pip install pyGAEB[llm]
```

Set your provider's API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# or: export OPENAI_API_KEY=sk-...
```

## Basic Classification

```python
from pygaeb import GAEBParser, LLMClassifier

doc = GAEBParser.parse("tender.X83")
classifier = LLMClassifier(model="anthropic/claude-sonnet-4-6")

# Async
await classifier.enrich(doc)

# Or synchronous
classifier.enrich_sync(doc)
```

After enrichment, each item has a `classification` attribute:

```python
for item in doc.iter_items():
    c = item.classification
    if c:
        print(f"{item.short_text}: {c.trade} / {c.element_type} / {c.sub_type}")
        print(f"  confidence={c.confidence:.2f} flag={c.flag.value}")
```

!!! tip
    `doc.iter_items()` works for both procurement (X80–X89) and trade (X93–X97) documents. For procurement-only code you can still use `doc.award.boq.iter_items()`.

## Cost Estimation

Before running classification, check the estimated cost:

```python
estimate = await classifier.estimate_cost(doc)
print(f"Items to classify: {estimate.items_to_classify}")
print(f"Estimated cost: ${estimate.estimated_cost_usd:.2f}")
print(f"Cached (free): {estimate.cached_items}")
```

## Taxonomy

Classification uses a three-level hierarchy: **Trade > Element Type > Sub-Type**.

| Trade | Element Types |
|-------|--------------|
| **Structural** | Wall, Floor, Roof, Foundation, Column, Beam |
| **Finishes** | Door, Window, Ceiling, Cladding, Flooring |
| **Roofing** | Roof Covering, Insulation, Drainage, Flashing |
| **MEP-Mechanical** | Duct, Air Handling Unit, Fan, Diffuser |
| **MEP-Electrical** | Cable, Panel, Luminaire, Socket, Conduit |
| **MEP-Plumbing** | Pipe, Valve, Pump, Sanitary Fixture |
| **Sitework** | Excavation, Paving, Landscaping, Fence |
| **Preliminaries** | Site Setup, Scaffolding, Welfare, Temp Works |
| **Other** | Unclassifiable |

Each element type has further sub-types (e.g., Door has Single Door, Double Door, Fire Door, Sliding Door, Revolving Door).

Access the taxonomy programmatically:

```python
from pygaeb.classifier.taxonomy import TAXONOMY, get_subtypes

subtypes = get_subtypes("Finishes", "Door")
# ["Single Door", "Double Door", "Fire Door", "Sliding Door", "Revolving Door"]
```

## Confidence Flags

Each classification result carries a `flag` indicating the confidence level:

| Flag | Confidence | Meaning |
|------|-----------|---------|
| `auto-classified` | >= 0.85 | High confidence — safe to use automatically |
| `needs-spot-check` | 0.60–0.84 | Medium confidence — spot-check recommended |
| `needs-review` | < 0.60 | Low confidence — manual review needed |
| `llm-error` | N/A | LLM call failed — item was not classified |
| `manual-override` | N/A | Manually set by user (preserved across re-runs) |

```python
from pygaeb.models.enums import ClassificationFlag

for item in doc.iter_items():
    if item.classification and item.classification.flag == ClassificationFlag.NEEDS_REVIEW:
        print(f"Review needed: {item.short_text}")
```

## Manual Overrides

Override the LLM classification for specific items:

```python
from pygaeb.models.item import ClassificationResult
from pygaeb.models.enums import ClassificationFlag

item = doc.award.boq.get_item("01.02.0030")
item.classification = ClassificationResult(
    trade="Finishes",
    element_type="Door",
    sub_type="Fire Door",
    confidence=1.0,
    flag=ClassificationFlag.MANUAL_OVERRIDE,
)
```

Manual overrides are preserved when re-running classification — the classifier skips items flagged as `MANUAL_OVERRIDE`.

## Supported LLM Providers

pyGAEB uses LiteLLM, so any supported provider works:

```python
# Cloud APIs
LLMClassifier(model="anthropic/claude-sonnet-4-6")
LLMClassifier(model="gpt-4o")
LLMClassifier(model="gemini/gemini-1.5-pro")

# Enterprise endpoints
LLMClassifier(model="azure/gpt-4o")
LLMClassifier(model="bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0")

# Local (air-gapped)
LLMClassifier(model="ollama/llama3")
```

## Concurrency

Classification runs items in parallel for speed:

```python
# Default: 5 concurrent LLM calls
classifier = LLMClassifier(model="gpt-4o")

# Increase for faster throughput
from pygaeb import configure
configure(classifier_concurrency=20)
```

## Caching

By default, classification results are cached in memory for the session. For persistent caching across runs, see the [Caching Guide](caching.md).
