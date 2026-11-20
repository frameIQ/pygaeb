# Extensibility

pyGAEB v1.7.0 introduces five extension points that let you tailor parsing, validation, and classification to your project without forking the library.

## Custom Validators

Register project-specific validation rules that run after the built-in pipeline. This rule checks procurement items and skips other document kinds:

```python
from pygaeb import GAEBParser, register_validator, clear_validators
from pygaeb.models.item import ValidationResult
from pygaeb.models.enums import ValidationSeverity

def require_unit(doc):
    """Require a quantity unit on procurement items."""
    if not doc.is_procurement:
        return []
    issues = []
    for item in doc.iter_items():
        if not item.unit:
            issues.append(
                ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    message=f"{item.full_oz}: missing unit",
                )
            )
    return issues

register_validator(require_unit)
doc = GAEBParser.parse("tender.X83")
# require_unit results are now in doc.validation_results
```

Per-call validators are also supported — they are not added to the global registry:

```python
doc = GAEBParser.parse("tender.X83", extra_validators=[require_unit])
```

Call `clear_validators()` to remove all globally registered validators (useful in tests).

## Post-Parse Hook

The `post_parse_hook` callback is called with `(item, source_element)` for every parsed item. Use it to extract vendor-specific XML elements into `item.raw_data`:

```python
def extract_vendor_codes(item, el):
    if el is None:
        return
    ns = {"g": "http://www.gaeb.de/GAEB_DA_XML/DA86/3.3"}
    codes = el.findall(".//g:VendorCostCode", ns)
    if codes:
        item.raw_data = item.raw_data or {}
        item.raw_data["vendor_codes"] = [c.text for c in codes]

doc = GAEBParser.parse("file.X83", post_parse_hook=extract_vendor_codes)
```

If `keep_xml=False` (the default), pyGAEB auto-enables XML retention for the hook, then discards it afterwards to free memory.

## Collect Unknown XML Elements

Set `collect_raw_data=True` to put the XML child elements the parser did not read into each item's `raw_data`:

```python
doc = GAEBParser.parse("file.X83", collect_raw_data=True)
for item in doc.iter_items():
    if item.raw_data:
        print(f"{item.oz}: extra fields = {item.raw_data}")
```

This is useful for discovering vendor extensions, and standard elements pyGAEB does not model yet (such as `ALNGroupNo` or `HourIt`), without writing a custom hook.

It works for every XML document kind: tender and award items (`Item`), trade order items (`OrderItem`), cost elements (`CostElement`) and quantity items (`QtyItem`). The parsers record every element they read, so `raw_data` holds exactly the rest. Each value is:

- the element's text for a plain element (`None` when it is empty);
- the whole element as an XML string when it has child elements;
- a list when the element appears more than once.

XML comments are never collected. GAEB 90 files are not XML, so there is nothing to collect from them. `raw_data` is left out of `model_dump()` and the JSON export.

## Custom Taxonomy and Prompt for LLM Classification

Override the built-in trade taxonomy and/or the system prompt per classifier instance:

```python
from pygaeb import LLMClassifier

my_taxonomy = {
    "Electrical": {"Cable Tray": ["Ladder", "Perforated"], "Panel": ["MCC", "DB"]},
    "HVAC": {"AHU": ["Rooftop", "Indoor"], "Duct": ["Galvanised", "Flexible"]},
}

my_prompt = "You are a specialist classifying MEP items. Use these trades: ..."

classifier = LLMClassifier(
    model="openai/gpt-4o",
    taxonomy=my_taxonomy,
    prompt_template=my_prompt,
)
await classifier.enrich(doc)
```

You can also register reusable prompt templates:

```python
from pygaeb import register_prompt

register_prompt("mep-v1", "You are classifying MEP items...")

classifier = LLMClassifier(prompt_version="mep-v1")
```

## Lifecycle Events

Subscribe to events for audit trails, metrics or webhooks. A callback receives one `dict` payload; an exception in a callback is logged and never breaks the parse or write.

```python
from pygaeb import EventType, on_event

def audit(payload):
    print(f"wrote {payload['file']}: {payload['warning_count']} warnings")

on_event(EventType.WRITE_COMPLETED, audit)
```

| Event | Fires | Payload |
|-------|-------|---------|
| `PARSE_STARTED` | Before a parse reads anything | `file` |
| `PARSE_COMPLETED` | After the document is built and validated | `file`, `item_count`, `version`, `phase`, `validation_count` |
| `PARSE_FAILED` | When a parse raises, before the exception propagates | `file`, `error` (exception class), `message` |
| `VALIDATION_FAILED` | When validation finds errors, in lenient and strict mode | `file`, `error_count`, `first_error`, `mode` |
| `WRITE_STARTED` | Before `GAEBWriter.write` or `to_bytes` builds the XML | `file` (`None` for `to_bytes`), `phase`, `version`, `item_count` |
| `WRITE_COMPLETED` | After the file or bytes are produced | as `WRITE_STARTED`, plus `warning_count`, `data_loss`, and `size` for `to_bytes` |
| `CLASSIFICATION_COMPLETED` | When `LLMClassifier.enrich` finishes | `model`, `item_count`, `unique_texts`, `cache_hits`, `llm_calls`, `errors` |

`file` for `parse_bytes` and `parse_string` is the filename hint. A strict parse that fails validation emits `VALIDATION_FAILED`, then `PARSE_FAILED`. `cache_hits` and `llm_calls` count unique texts, not items. `validate_against_xsd` emits no write events.

Subscribers are process-wide: in a multi-tenant application, a callback hears every tenant's parses and writes. Remove them with `off_event` or `clear_subscribers`.

## Configuring Log Level

The `log_level` setting is now applied to the `pygaeb` logger automatically:

```python
from pygaeb import configure

configure(log_level="DEBUG")
# All pygaeb.* loggers now emit DEBUG messages
```

You can also set it via environment variable:

```bash
export PYGAEB_LOG_LEVEL=DEBUG
```
