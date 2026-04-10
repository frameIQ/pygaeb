# pyGAEB

**Python-Bibliothek zum Parsen, Validieren, Klassifizieren und Schreiben von GAEB DA XML Dateien — mit LLM-gestützter Positionsklassifizierung.**

[![CI](https://github.com/frameIQ/pygaeb/actions/workflows/test.yml/badge.svg)](https://github.com/frameIQ/pygaeb/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/frameIQ/pygaeb/branch/main/graph/badge.svg)](https://codecov.io/gh/frameIQ/pygaeb)
[![PyPI version](https://img.shields.io/badge/version-1.12.0-blue.svg)](https://pypi.org/project/pyGAEB/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

> **[English version](README.md)**

pyGAEB verarbeitet GAEB DA XML Dateien (Versionen 2.0 bis 3.3) und erzeugt ein einheitliches Pydantic-v2-Datenmodell — unabhängig von der Eingangsversion. Die Bibliothek unterstützt das gesamte GAEB-Austauschphasenspektrum:

- **Vergabe** (X80–X89) — Leistungsverzeichnis, Angebot, Auftragserteilung, Abrechnung
- **Handel** (X93–X97) — Materialbestellungen zwischen Auftragnehmer und Lieferant
- **Kosten & Kalkulation** (X50–X52) — Elementkostenrechnung, Kostenermittlung, Kalkulationsansätze
- **Mengenermittlung** (X31) — Aufmaß nach REB 23.003

Eine optionale LLM-Klassifizierungsschicht ordnet jede LV-Position semantisch einem Bau-Elementtyp zu — über [LiteLLM](https://github.com/BerriAI/litellm) mit Zugang zu über 100 KI-Anbietern.

## Merkmale

- **Multiversions-Unterstützung** — DA XML 2.0, 2.1, 3.0, 3.1, 3.2, 3.3 — automatische Erkennung
- **Alle Austauschphasen** — Vergabe, Handel, Kosten & Kalkulation, Mengenermittlung
- **Sicherheitsgehärtet** — XXE-Schutz, Billion-Laughs-Abwehr, Dateigrößenbegrenzung, Rekursionstiefenlimit
- **Erweiterbar** — Eigene Validierungsregeln, Post-Parse-Hooks, Rohdatenerfassung, eigene LLM-Taxonomie
- **LLM-Klassifizierung** — 100+ Anbieter via LiteLLM mit Kostenvoranschlag und persistentem Caching
- **Phasenübergreifende Validierung** — X83→X84 Strukturidentität, X86→X89 EP-Abgleich, X86→X88 Nachtragsverfolgung
- **Round-Trip** — Einlesen → Bearbeiten → Zurückschreiben in jede DA-XML-Version
- **Versionskonvertierung** — Upgrade/Downgrade zwischen DA XML 2.0–3.3

## Installation

```bash
# Kern-Parser + Writer + Export (keine LLM-Abhängigkeiten)
pip install pyGAEB

# Mit LLM-Klassifizierung (100+ Anbieter via LiteLLM)
pip install pyGAEB[llm]
```

## Schnellstart

### Beliebige GAEB-Datei einlesen

```python
from pygaeb import GAEBParser

doc = GAEBParser.parse("ausschreibung.X83")    # DA XML 3.x
doc = GAEBParser.parse("altformat.D83")         # DA XML 2.x — gleicher Aufruf

print(doc.source_version)                       # SourceVersion.DA_XML_33
print(doc.exchange_phase)                       # ExchangePhase.X83
print(doc.grand_total)                          # Decimal("1234567.89")
```

### LV-Positionen durchlaufen

Funktioniert für alle Dokumentarten — Vergabe, Handel, Kosten und Mengenermittlung:

```python
for item in doc.iter_items():
    print(item.oz)              # "01.02.0030"  (Ordnungszahl)
    print(item.short_text)      # "Mauerwerk der Innenwand…"  (Kurztext)
    print(item.qty)             # Decimal("1170.000")  (Menge)
    print(item.unit)            # "m2"  (Einheit)
    print(item.unit_price)      # Decimal("45.50")  (Einheitspreis)
    print(item.total_price)     # Decimal("53235.00")  (Gesamtbetrag)
    print(item.item_type)       # ItemType.NORMAL
```

### Validierung

```python
from pygaeb import GAEBParser, ValidationMode

# Tolerant (Standard) — Warnungen sammeln, weiter parsen
doc = GAEBParser.parse("ausschreibung.X83")
for issue in doc.validation_results:
    print(issue.severity, issue.message)

# Strikt — beim ersten Fehler abbrechen
doc = GAEBParser.parse("ausschreibung.X83", validation=ValidationMode.STRICT)
```

### Eigene Validierungsregeln

Projektspezifische Prüfungen registrieren:

```python
from pygaeb import register_validator, clear_validators
from pygaeb.models.item import ValidationResult
from pygaeb.models.enums import ValidationSeverity

def einheit_pflicht(doc):
    fehler = []
    for item in doc.iter_items():
        if not item.unit:
            fehler.append(
                ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    message=f"{item.oz}: Einheit fehlt",
                )
            )
    return fehler

register_validator(einheit_pflicht)
doc = GAEBParser.parse("ausschreibung.X83")
# Ergebnisse liegen in doc.validation_results

# Oder pro Aufruf (wird nicht global registriert):
doc = GAEBParser.parse("ausschreibung.X83", extra_validators=[einheit_pflicht])
```

### Schreiben / Round-Trip

```python
from pygaeb import GAEBWriter, ExchangePhase
from decimal import Decimal

doc = GAEBParser.parse("ausschreibung.X83")
pos = doc.award.boq.get_item("01.02.0030")
pos.unit_price = Decimal("48.00")

GAEBWriter.write(doc, "angebot.X84", phase=ExchangePhase.X84)
```

### Versionskonvertierung

```python
from pygaeb import GAEBConverter, SourceVersion

# Upgrade 2.x → 3.3
report = GAEBConverter.convert("altformat.D83", "modern.X83")

# Downgrade 3.3 → 3.2 für Kompatibilität mit älterer AVA-Software
report = GAEBConverter.convert(
    "ausschreibung.X83", "kompatibel.X83",
    target_version=SourceVersion.DA_XML_32,
)
print(f"{report.items_converted} Positionen konvertiert, Datenverlust: {report.has_data_loss}")
```

### Export nach JSON / CSV

```python
from pygaeb.convert import to_json, to_csv

to_json(doc, "lv.json")        # Vollständiger LV-Baum (verschachtelt)
to_csv(doc, "positionen.csv")  # Flache Positionsliste mit Klassifizierungsspalten
```

### Handelsphasen (X93–X97)

```python
doc = GAEBParser.parse("bestellung.X96")
print(doc.document_kind)    # DocumentKind.TRADE
print(doc.is_trade)         # True

for item in doc.order.items:
    print(item.art_no, item.short_text, item.net_price)

print(doc.order.supplier_info.address.name)  # Lieferant
```

### Kosten & Kalkulation (X50–X52)

```python
doc = GAEBParser.parse("kostenberechnung.X50")
print(doc.document_kind)    # DocumentKind.COST

for elem in doc.elemental_costing.body.iter_cost_elements():
    print(elem.ele_no, elem.short_text, elem.total_cost)
```

### Mengenermittlung / Aufmaß (X31)

```python
doc = GAEBParser.parse("aufmass.X31")
print(doc.document_kind)    # DocumentKind.QUANTITY

for item in doc.qty_determination.boq.iter_items():
    print(item.oz, item.qty_determ_items)
```

### Finanzzusammenfassung & Projektdaten

```python
doc = GAEBParser.parse("abrechnung.X86")

# LV-Gesamtsummen
summen = doc.award.boq.info.totals
print(summen.total_net, summen.total_gross, summen.vat_amount)

# MwSt.-Aufschlüsselung je Steuersatz
for teil in summen.vat_parts:
    print(f"{teil.vat_pcnt}%: netto {teil.net_amount} → brutto {teil.gross_amount}")

# Projektmetadaten
print(doc.award.prj_id, doc.award.description, doc.award.currency_label)
```

### LLM-Klassifizierung

```python
from pygaeb import LLMClassifier

# Standard: In-Memory-Cache (kein Festplattenzugriff)
classifier = LLMClassifier(model="anthropic/claude-sonnet-4-6")
# classifier = LLMClassifier(model="gpt-4o")
# classifier = LLMClassifier(model="ollama/llama3")  # lokal, kostenlos, datensicher

# Persistent: SQLite-Cache (überlebt Neustarts)
from pygaeb import SQLiteCache
classifier = LLMClassifier(cache=SQLiteCache("~/.pygaeb/cache"))

# Eigene Taxonomie und Prompt
classifier = LLMClassifier(
    model="openai/gpt-4o",
    taxonomy={"Elektro": {"Kabeltrasse": ["Leiter", "Lochblech"]}},
    prompt_template="Du bist ein Experte für die Klassifizierung von TGA-Positionen...",
)

# Kosten vorab prüfen
estimate = await classifier.estimate_cost(doc)
print(f"{estimate.items_to_classify} Positionen, ca. ${estimate.estimated_cost_usd:.2f}")

# Alle Positionen klassifizieren
await classifier.enrich(doc)

# Oder synchron
classifier.enrich_sync(doc)

for item in doc.iter_items():
    if item.classification:
        print(item.oz, item.classification.element_type, item.classification.confidence)
```

### Strukturierte Extraktion — Eigene Schemas

Nach der Klassifizierung typisierte Attribute in eigene Pydantic-Schemas extrahieren:

```python
from pydantic import BaseModel, Field
from typing import Optional
from pygaeb import StructuredExtractor

class TuerSpec(BaseModel):
    tuerart: str = Field("", description="Einfach-, Doppel-, Schiebetür")
    breite_mm: Optional[int] = Field(None, description="Breite in mm")
    brandschutz: Optional[str] = Field(None, description="T30, T60, T90")
    verglasung: bool = Field(False, description="Mit Glasausschnitten")
    werkstoff: str = Field("", description="Holz, Stahl, Aluminium")

extractor = StructuredExtractor(model="anthropic/claude-sonnet-4-6")

# Aus allen als „Door" klassifizierten Positionen extrahieren
tueren = await extractor.extract(doc, schema=TuerSpec, element_type="Door")
for pos, spec in tueren:
    print(pos.oz, spec.tuerart, spec.brandschutz, spec.breite_mm)
```

### Herstellerspezifische XML-Elemente

Viele AVA-Programme fügen proprietäre Tags in die GAEB-Datei ein. pyGAEB bietet drei Zugangswege:

```python
# 1. Post-Parse-Hook — Herstellerdaten während des Parsens extrahieren
def ava_codes_extrahieren(item, el):
    if el is None:
        return
    ns = {"g": "http://www.gaeb.de/GAEB_DA_XML/DA86/3.3"}
    codes = el.findall(".//g:VendorCostCode", ns)
    if codes:
        item.raw_data = item.raw_data or {}
        item.raw_data["ava_codes"] = [c.text for c in codes]

doc = GAEBParser.parse("datei.X83", post_parse_hook=ava_codes_extrahieren)

# 2. Unbekannte Elemente automatisch erfassen
doc = GAEBParser.parse("datei.X83", collect_raw_data=True)

# 3. XPath-Zugriff auf den gesamten XML-Baum
doc = GAEBParser.parse("datei.X83", keep_xml=True)
codes = doc.xpath("//g:VendorCostCode/text()")
doc.discard_xml()  # Speicher freigeben
```

### Phasenübergreifende Validierung

```python
from pygaeb import GAEBParser, CrossPhaseValidator

# Ausschreibung → Angebot: Strukturidentität
ausschreibung = GAEBParser.parse("ausschreibung.X83")
angebot = GAEBParser.parse("angebot.X84")
probleme = CrossPhaseValidator.check(source=ausschreibung, response=angebot)

# Vertrag → Rechnung: Einheitspreise müssen übereinstimmen
vertrag = GAEBParser.parse("vertrag.X86")
rechnung = GAEBParser.parse("rechnung.X89")
probleme = CrossPhaseValidator.check(source=vertrag, response=rechnung)

# Vertrag → Nachtrag: Nachverfolgbarkeit über Auftragsnummer
nachtrag = GAEBParser.parse("nachtrag.X88")
probleme = CrossPhaseValidator.check(source=vertrag, response=nachtrag)

for p in probleme:
    print(p.severity, p.message)
```

## Unterstützte Versionen & Austauschphasen

| Version | Parser-Track | Status |
|---------|-------------|--------|
| DA XML 2.0 | Track A (deutsche Elemente) | v1.0 |
| DA XML 2.1 | Track A (deutsche Elemente) | v1.0 |
| DA XML 3.0 | Track B (englische Elemente) | v1.0 |
| DA XML 3.1 | Track B (englische Elemente) | v1.0 |
| DA XML 3.2 | Track B (englische Elemente) | v1.0 |
| DA XML 3.3 | Track B (englische Elemente) | v1.0 |
| GAEB 90 | Track C (Festformat) | Geplant |

| Phase | Beschreibung | Seit |
|-------|-------------|------|
| X31 | Mengenermittlung / Aufmaß | v1.4.0 |
| X50, X51, X52 | Kosten & Kalkulation | v1.3.0 |
| X80–X86 | Vergabe (Ausschreibung, Angebot, Auftrag) | v1.0.0 |
| X88 | Nachtrag / Nachtragsangebot | v1.12.0 |
| X89, X89B | Abrechnung / erweiterte Abrechnung | v1.0.0 |
| X93, X94, X96, X97 | Handel (Materialbestellung) | v1.2.0 |

## Konfiguration

```python
from pygaeb import configure

configure(
    default_model="ollama/llama3",        # LLM-Modell für Klassifizierung
    classifier_concurrency=10,            # Parallele LLM-Aufrufe
    xsd_dir="/opt/gaeb-schemas",          # Optionale XSD-Validierung
    log_level="DEBUG",                    # Wird auf pygaeb.*-Logger angewandt
    max_file_size_mb=200,                 # Maximale Dateigröße in MB
)
```

Oder über Umgebungsvariablen:

```bash
export PYGAEB_DEFAULT_MODEL=ollama/llama3
export PYGAEB_XSD_DIR=/opt/gaeb-schemas
export PYGAEB_LOG_LEVEL=DEBUG
export PYGAEB_MAX_FILE_SIZE_MB=200
```

## Sicherheit

pyGAEB enthält seit v1.6.0 folgende Sicherheitsmaßnahmen:

- **XXE-Schutz** — Alle XML-Parser verwenden `resolve_entities=False` und `no_network=True`
- **Billion-Laughs-Abwehr** — Entity-Expansion-Bomben werden blockiert
- **Dateigrößenlimit** — Konfigurierbares Limit (Standard 100 MB) verhindert Speicherüberlauf
- **Rekursionstiefenlimit** — Hierarchie-Durchläufe auf 50 Ebenen begrenzt
- **Begrenztes Caching** — `InMemoryCache` mit LRU-Verdrängung (Standard 10.000 Einträge)

## Dokumentation

Die vollständige Dokumentation ist auf [Read the Docs](https://pygaeb.readthedocs.io/) verfügbar (Englisch).

- [Schnellstart](https://pygaeb.readthedocs.io/getting-started/quickstart/)
- [Parsing-Leitfaden](https://pygaeb.readthedocs.io/guides/parsing/)
- [Handelsphasen](https://pygaeb.readthedocs.io/guides/trade-phases/)
- [Kosten & Kalkulation](https://pygaeb.readthedocs.io/guides/cost-phases/)
- [Mengenermittlung](https://pygaeb.readthedocs.io/guides/quantity-phases/)
- [Erweiterbarkeit](https://pygaeb.readthedocs.io/guides/extensibility/)
- [Klassifizierung](https://pygaeb.readthedocs.io/guides/classification/)
- [Versionskonvertierung](https://pygaeb.readthedocs.io/guides/conversion/)
- [API-Referenz](https://pygaeb.readthedocs.io/reference/)

## Lizenz

MIT — siehe [LICENSE](LICENSE).
