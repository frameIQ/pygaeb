# Word, HTML and Markdown Export

Three more ways to put an LV in front of people or programs. All of them print the same content as the [PDF printout](pdf-export.md), because they share one walk through the document: the hierarchy, full OZ, short and long texts, item-type markers, *Nur Einh.-Preis* for priced items that are not summed, markup rates, subtotals and the grand total. German labels and number format are the default; `locale="en"` switches both.

| Export | Use it for | Extra install |
|---|---|---|
| `to_docx` | An editable Word document to adjust and send | `pip install pyGAEB[docx]` |
| `to_html` | Showing an LV in a web page or app | none |
| `to_markdown` | Reading in plain text, or giving an LV to an LLM | none |

## Word

```python
from pygaeb import GAEBParser
from pygaeb.convert import to_docx

doc = GAEBParser.parse("tender.X84")
to_docx(doc, "tender.docx")
```

An A4 document with the printout's six columns (OZ, description, quantity, unit, unit price, total). The header row repeats on every page. Word paginates the document itself, so there are no carry-forward lines.

## HTML

```python
from pygaeb.convert import to_html

to_html(doc, "tender.html")                  # a complete page with its own styles
fragment = to_html(doc, standalone=False)    # a <section class="lv"> to embed
```

Every string from the document is escaped, so a GAEB file cannot inject markup into your page. The table rows carry classes to style against:

| Row | Classes |
|---|---|
| Lot and category headings | `lv-heading lv-lot` / `lv-heading lv-category`, plus `depth-N` |
| Positions | `lv-position depth-N`, with `data-oz` (the full OZ) and `data-id` (the GAEB item ID, when present) |
| Sums | `lv-total lv-subtotal`, `lv-total lv-lot-subtotal`, `lv-total lv-grand-total` |

Unit-price cells of markups have the class `rate`, and total cells that hold *Nur Einh.-Preis* the class `unit-price-only`.

## Markdown

```python
from pygaeb.convert import to_markdown

text = to_markdown(doc)                       # returns the Markdown
to_markdown(doc, "tender.md", locale="en")    # and writes it, in English
```

Lots and categories become headings, each position a bold line with its long text and one line of marker and amounts:

```markdown
### 01 Erdarbeiten

**01.0010 Baustelleneinrichtung**

Einrichten, Vorhalten und Räumen der Baustelle.

*Pauschalposition* · Menge 1,000 psch · EP 4.800,00 · GB 4.800,00

**Summe 01 Erdarbeiten: 23.841,71**
```

Characters that Markdown would read as formatting (`*`, `_`, `[`, a leading `#`, …) are escaped, so document text stays literal.

Pass `long_text=False` to any of the three exports to leave the long texts out.

## From the command line

`pygaeb export` writes every format. The output is named after the input file unless `-o` names it:

```bash
pygaeb export tender.X83 -f pdf            # tender.pdf
pygaeb export tender.X83 -f docx           # tender.docx
pygaeb export tender.X83 -f html -o lv.html
pygaeb export tender.X83 -f md             # tender.md
```

`-f` takes `json`, `csv`, `xlsx`, `pdf`, `docx`, `html` or `md`. When a format needs an optional extra that is not installed (`pdf`, `docx`, `excel`), the command says which one to install.
