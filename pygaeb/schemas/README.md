# GAEB XSD Schema Files

Official GAEB XSD schema files are **not bundled** with pyGAEB due to licensing
restrictions.

## Obtaining Schema Files

XSD files can be obtained from [gaeb.de](https://www.gaeb.de/) (the official
GAEB standards body).

## Expected Directory Layout

Place schema files in the following structure:

```
gaeb-schemas/
├── v20/
├── v21/
├── v30/
├── v31/
├── v32/
└── v33/
```

## Usage

```python
doc = GAEBParser.parse("tender.X83", xsd_dir="/path/to/gaeb-schemas/v33/")
```

If no `xsd_dir` is provided, XSD validation is skipped silently.
