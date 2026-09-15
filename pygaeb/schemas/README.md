# GAEB XSD Schema Files

Official GAEB XSD schema files are **not bundled** with pyGAEB due to licensing
restrictions.

## Obtaining Schema Files

XSD files can be obtained from [gaeb.de](https://www.gaeb.de/) (the official
GAEB standards body). A release ships one schema per exchange phase plus a
shared library file that the phase files include:

```
GAEB_DA_XML_81_3.3_2021-05.xsd
GAEB_DA_XML_83_3.3_2021-05.xsd
…
GAEB_DA_XML_Lib_3.3_2021-05.xsd
```

## Expected Directory Layout

Either keep the distribution flat, or place each version in its own folder.
pyGAEB picks the file by version **and exchange phase** (an X83 is checked
against `GAEB_DA_XML_83_…`), so keep the official file names and the `Lib`
file next to them.

```
gaeb-schemas/
├── GAEB_DA_XML_83_3.3_2021-05.xsd     # flat …
├── GAEB_DA_XML_Lib_3.3_2021-05.xsd
└── v32/                               # … or per version
    ├── GAEB_DA_XML_83_3.2_2013-10.xsd
    └── GAEB_DA_XML_Lib_3.2_2013-10.xsd
```

## Usage

```python
doc = GAEBParser.parse("tender.X83", xsd_dir="/path/to/gaeb-schemas")
result = GAEBWriter.validate_against_xsd(doc, phase=ExchangePhase.X84,
                                         xsd_dir="/path/to/gaeb-schemas")
```

Or set `PYGAEB_XSD_DIR`. If no directory is configured, or no schema matches
the document's version and phase, validation is skipped with an `INFO` result.
