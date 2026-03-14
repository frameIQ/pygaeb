# Custom & Vendor Tags

GAEB files in the wild often contain vendor-specific tags, software extensions, or custom elements that go beyond the official DA XML schema. pyGAEB lets you access **any** XML element — including unknown ones — via raw element retention and XPath queries.

## Enabling Raw XML Access

By default, pyGAEB discards the raw XML tree after parsing to save memory. To retain it, pass `keep_xml=True`:

```python
from pygaeb import GAEBParser

doc = GAEBParser.parse("tender.X83", keep_xml=True)
```

This works with all parse methods:

```python
doc = GAEBParser.parse_bytes(raw, filename="tender.X83", keep_xml=True)
doc = GAEBParser.parse_string(xml_text, keep_xml=True)
```

## Accessing Custom Tags on Items

When `keep_xml=True`, every `Item`, `BoQCtgy`, `AwardInfo`, and `GAEBInfo` object has a `source_element` attribute containing the original lxml `_Element`:

```python
for item in doc.award.boq.iter_items():
    el = item.source_element

    # Access a vendor-specific tag (namespaced)
    ns = "{http://www.gaeb.de/GAEB_DA_XML/DA86/3.3}"
    cost_code = el.find(f"{ns}VendorCostCode")
    if cost_code is not None:
        print(f"{item.oz}: {cost_code.text}")
```

!!! tip "Namespace prefix"
    GAEB DA XML elements are namespaced. When using `el.find()`, you must include the full namespace URI in braces. Use `doc.raw_namespace` to get it dynamically:

    ```python
    ns = f"{{{doc.raw_namespace}}}" if doc.raw_namespace else ""
    el.find(f"{ns}CustomTag")
    ```

## XPath Queries

For querying across the entire document tree, use `doc.xpath()`. The document namespace is available as the `g:` prefix:

```python
# Find all VendorCostCode values
codes = doc.xpath("//g:VendorCostCode/text()")
print(codes)  # ["RC-001", "RC-002", ...]

# Find items with a specific attribute
items = doc.xpath("//g:Item[@RNoPart='001']")

# Get totals from BoQ sections
totals = doc.xpath("//g:Totals/g:TotalGross/text()")
```

!!! note "Namespace handling"
    If the file has no namespace (rare), XPath expressions work without the `g:` prefix:

    ```python
    doc.xpath("//Item/VendorCostCode/text()")
    ```

## DocumentAPI Helpers

The `DocumentAPI` class provides convenience methods for common custom tag operations:

```python
from pygaeb import DocumentAPI

api = DocumentAPI(doc)

# XPath on the whole document
results = api.xpath("//g:VendorCostCode/text()")

# Get a custom tag's text from a specific item
for item in api.iter_items():
    ns = f"{{{doc.raw_namespace}}}"
    val = api.custom_tag(item, f"{ns}VendorCostCode")
    if val:
        print(f"{item.oz}: {val}")
```

`custom_tag()` returns `None` if the tag doesn't exist or if `keep_xml` was not enabled — it never raises.

## Accessing Other Model Elements

Raw elements are available on all major model types:

```python
doc = GAEBParser.parse("file.X83", keep_xml=True)

# GAEBInfo
doc.gaeb_info.source_element  # <GAEBInfo> element

# AwardInfo
doc.award.source_element      # <Award> element

# Categories
for _, _, ctgy in doc.award.boq.iter_hierarchy():
    if ctgy and ctgy.source_element is not None:
        # Access category-level custom tags
        pass
```

## Real-World Example

A file from a German AVA software might include custom cost tracking tags:

```xml
<Item RNoPart="0010">
  <ShortText>Mauerwerk KS 240mm</ShortText>
  <Qty>100</Qty>
  <QU>m2</QU>
  <UP>45.50</UP>
  <IT>4550.00</IT>
  <!-- Vendor extensions -->
  <VendorCostCode>RC-001</VendorCostCode>
  <CustomNote>Priority item</CustomNote>
</Item>
```

Extract these without modifying the parser:

```python
doc = GAEBParser.parse("vendor_file.X83", keep_xml=True)
ns = f"{{{doc.raw_namespace}}}"

for item in doc.award.boq.iter_items():
    el = item.source_element
    code = el.find(f"{ns}VendorCostCode")
    note = el.find(f"{ns}CustomNote")
    print(f"{item.oz}: code={code.text if code is not None else 'N/A'}, "
          f"note={note.text if note is not None else 'N/A'}")
```

## Memory Considerations

When `keep_xml=False` (the default), the lxml tree is garbage-collected after parsing. With `keep_xml=True`, the entire XML tree remains in memory alongside the Pydantic models. For large files (10,000+ items), this roughly doubles memory usage.

| Mode | Memory | `source_element` | `xpath()` |
|------|--------|-------------------|-----------|
| `keep_xml=False` | Normal | `None` | Raises `RuntimeError` |
| `keep_xml=True` | ~2x | lxml `_Element` | Full XPath support |

For most use cases, the memory overhead is negligible. If you're processing many large files in a pipeline, parse with `keep_xml=False` for standard data and only re-parse specific files with `keep_xml=True` when custom tag access is needed.
