# Version Conversion

pyGAEB can convert GAEB files between any DA XML version — from 2.0 through 3.3. This enables upgrading legacy files, normalizing mixed-version archives, and producing downgraded output for compatibility with older software.

## Quick Start

```python
from pygaeb import GAEBConverter, SourceVersion

report = GAEBConverter.convert(
    "old_tender.D83",
    "modern_tender.X83",
    target_version=SourceVersion.DA_XML_33,
)

print(f"Converted {report.items_converted} items")
print(f"Source: DA XML {report.source_version.value}")
print(f"Target: DA XML {report.target_version.value}")

if report.has_data_loss:
    for field in report.fields_dropped:
        print(f"  Warning: {field}")
```

## Supported Conversions

pyGAEB supports writing to all DA XML versions:

| Target Version | Namespace | Element Language |
|---------------|-----------|------------------|
| DA XML 3.3 | `DA86/3.3` | English |
| DA XML 3.2 | `DA86/3.2` | English |
| DA XML 3.1 | `DA86/3.1` | English |
| DA XML 3.0 | `200407` | English |
| DA XML 2.1 | `200407` | German |
| DA XML 2.0 | `200407` | German |

Combined with the parser (which reads all versions), this gives full N-to-N conversion.

## Upgrade (2.x to 3.3)

Upgrading from DA XML 2.x to 3.x is **lossless** — all data is preserved:

```python
report = GAEBConverter.convert(
    "legacy.D83", "modern.X83",
    target_version=SourceVersion.DA_XML_33,
)
assert not report.has_data_loss
```

German element names (`<Leistungsverzeichnis>`, `<Position>`, `<Menge>`) are automatically translated to English (`<BoQ>`, `<Item>`, `<Qty>`), and the namespace is updated.

## Downgrade (3.3 to older)

Downgrading may drop fields that don't exist in the target version:

```python
report = GAEBConverter.convert(
    "modern.X83", "compat.X83",
    target_version=SourceVersion.DA_XML_32,
)

for warning in report.fields_dropped:
    print(warning)
    # "Item 01.0010: bim_guid dropped (not supported in DA XML 3.2)"
```

### What gets dropped per version

| Field | 3.3 | 3.2 | 3.1 | 3.0 | 2.x |
|-------|-----|-----|-----|-----|-----|
| `bim_guid` | Yes | No | No | No | No |
| `attachments` | Yes | Yes | Yes | No | No |
| `change_order_number` | Yes | Yes | Yes | No | No |

The `ConversionReport` always tells you exactly what was dropped.

## Cross-Family Conversion (3.x to 2.x)

Converting from 3.x to 2.x translates all element names to German:

```python
report = GAEBConverter.convert(
    "tender.X83", "tender.D83",
    target_version=SourceVersion.DA_XML_20,
)

# Output contains German tags:
# <Vergabe>, <Leistungsverzeichnis>, <Position>, <Menge>, etc.
```

## Using GAEBWriter Directly

If you already have a parsed `GAEBDocument`, use `GAEBWriter.write()` with the `target_version` parameter:

```python
from pygaeb import GAEBParser, GAEBWriter, SourceVersion

doc = GAEBParser.parse("input.X83")

# Write to specific version
warnings = GAEBWriter.write(
    doc, "output_v32.X83",
    target_version=SourceVersion.DA_XML_32,
)

# Write to DA XML 2.x (German output)
warnings = GAEBWriter.write(
    doc, "output_v20.D83",
    target_version=SourceVersion.DA_XML_20,
)

for w in warnings:
    print(w)
```

## In-Memory Conversion

For web APIs or pipelines where you don't need to write to disk:

```python
# GAEBConverter — parse + convert in one call
xml_bytes, report = GAEBConverter.convert_bytes(
    "input.X83",
    target_version=SourceVersion.DA_XML_32,
)

# GAEBWriter — convert an already-parsed document
xml_bytes, warnings = GAEBWriter.to_bytes(
    doc,
    target_version=SourceVersion.DA_XML_20,
)
```

## Phase Override

Combine version conversion with phase override to change both version and exchange phase in one step:

```python
from pygaeb import GAEBConverter, SourceVersion, ExchangePhase

report = GAEBConverter.convert(
    "tender.X83", "bid.X84",
    target_version=SourceVersion.DA_XML_32,
    target_phase=ExchangePhase.X84,
)
```

## Conversion Report

Every conversion returns a `ConversionReport` with:

```python
report.source_version     # SourceVersion — detected input version
report.target_version     # SourceVersion — requested output version
report.source_phase       # ExchangePhase — original phase
report.target_phase       # ExchangePhase — output phase
report.items_converted    # int — total items written
report.fields_dropped     # list[str] — fields dropped for target version
report.warnings           # list[str] — all warnings
report.is_upgrade         # bool — target > source version
report.is_downgrade       # bool — target < source version
report.is_same_family     # bool — both in 3.x or both in 2.x
report.has_data_loss       # bool — True if any fields were dropped
```
