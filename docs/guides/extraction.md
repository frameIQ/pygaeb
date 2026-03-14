# Structured Extraction

After classifying items, you can extract typed attributes into your own Pydantic schemas using LLMs. This lets you turn unstructured German construction text into structured data — for example, extracting door dimensions, fire ratings, and materials from BoQ descriptions.

## Setup

Structured extraction requires the LLM extras:

```bash
pip install pyGAEB[llm]
```

## Basic Usage

Define a Pydantic schema, then extract:

```python
from pydantic import BaseModel, Field
from pygaeb import GAEBParser, LLMClassifier, StructuredExtractor

doc = GAEBParser.parse("tender.X83")

# First, classify items so extraction knows what to look for
classifier = LLMClassifier(model="anthropic/claude-sonnet-4-6")
await classifier.enrich(doc)

# Define your schema
class DoorSpec(BaseModel):
    door_type: str = Field("", description="single, double, sliding")
    width_mm: int | None = Field(None, description="Width in mm")
    fire_rating: str | None = Field(None, description="T30, T60, T90")
    glazing: bool = Field(False, description="Has glass panels")
    material: str = Field("", description="wood, steel, aluminium")

# Extract from all items classified as "Door"
extractor = StructuredExtractor(model="anthropic/claude-sonnet-4-6")
doors = await extractor.extract(doc, schema=DoorSpec, element_type="Door")

for item, spec in doors:
    print(f"{item.oz}: {spec.door_type}, {spec.width_mm}mm, fire={spec.fire_rating}")
```

## Filtering

Control which items are extracted using filter parameters:

```python
# By element type (most common)
doors = await extractor.extract(doc, schema=DoorSpec, element_type="Door")

# By trade (broad)
pipes = await extractor.extract(doc, schema=PipeSpec, trade="MEP-Plumbing")

# By sub-type (narrow)
fire_doors = await extractor.extract(doc, schema=DoorSpec, sub_type="Fire Door")

# Combine filters
exterior = await extractor.extract(
    doc, schema=WallSpec, trade="Structural", element_type="Wall", sub_type="Exterior Wall"
)
```

## Synchronous API

```python
doors = extractor.extract_sync(doc, schema=DoorSpec, element_type="Door")
```

## Built-in Schemas

pyGAEB includes starter schemas for common element types:

```python
from pygaeb.extractor.builtin_schemas import DoorSpec, WindowSpec, WallSpec, PipeSpec
```

### DoorSpec

| Field | Type | Description |
|-------|------|-------------|
| `door_type` | `str` | single, double, sliding |
| `width_mm` | `int \| None` | Width in mm |
| `height_mm` | `int \| None` | Height in mm |
| `fire_rating` | `str \| None` | Fire class (T30, T60, T90) |
| `acoustic_rating_db` | `int \| None` | Sound insulation in dB |
| `surface_finish` | `str \| None` | HPL, painted, veneer, etc. |
| `frame_material` | `str \| None` | Steel, wood, aluminium |
| `glazing` | `bool` | Has glass panels |
| `material` | `str` | Primary material |

### WindowSpec

| Field | Type | Description |
|-------|------|-------------|
| `window_type` | `str` | fixed, casement, tilt-turn |
| `width_mm` | `int \| None` | Width in mm |
| `height_mm` | `int \| None` | Height in mm |
| `u_value` | `float \| None` | U-value W/(m2K) |
| `glazing_type` | `str \| None` | double, triple |
| `frame_material` | `str \| None` | PVC, aluminium, timber |
| `fire_rating` | `str \| None` | Fire class if applicable |
| `sound_insulation_db` | `int \| None` | Sound insulation in dB |
| `opening_direction` | `str \| None` | left, right, top |

### WallSpec and PipeSpec

Similar structured schemas for walls (thickness, material, load-bearing, insulation) and pipes (diameter, material, medium, pressure rating). See the [Extractor Reference](../reference/extractor.md) for full details.

## Custom Schemas

Any Pydantic `BaseModel` works. Tips for best results:

1. **Use `Field(description=...)`** — the LLM reads field descriptions to understand what to extract
2. **Use `None` defaults** for optional fields — the LLM will leave them as `None` when not found
3. **Keep schemas focused** — 5–15 fields per schema works best
4. **Use German-friendly descriptions** — GAEB text is typically in German

```python
class ConcreteSpec(BaseModel):
    """Extracted attributes for concrete work items."""
    strength_class: str = Field("", description="Betongüte, e.g. C25/30, C30/37")
    exposure_class: str | None = Field(None, description="Expositionsklasse, e.g. XC1, XD2")
    thickness_mm: int | None = Field(None, description="Dicke/Stärke in mm")
    reinforcement: bool = Field(False, description="Bewehrung vorhanden")
    formwork: str | None = Field(None, description="Schalungsart")
```

## Extraction Results

Results are stored on the item:

```python
for item, spec in doors:
    # spec is a DoorSpec instance
    print(spec.model_dump())

    # Also stored on the item for later access
    result = item.extractions["DoorSpec"]
    print(result.schema_name)     # "DoorSpec"
    print(result.data)            # dict of extracted values
    print(result.completeness)    # 0.0–1.0 (fraction of non-default fields)
    print(result.cached)          # bool — was this from cache?
```

## Caching

Extraction results are cached the same way as classification. See the [Caching Guide](caching.md) for details on in-memory, SQLite, and custom backends.
