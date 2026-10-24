# PDF Export

`to_pdf` prints a GAEB document the way AVA programs print an LV, ready to read, send or archive.

```bash
pip install pyGAEB[pdf]
```

```python
from pygaeb import GAEBParser
from pygaeb.convert.to_pdf import to_pdf

doc = GAEBParser.parse("tender.X84")
to_pdf(doc, "tender.pdf")
```

## What gets printed

For procurement documents (X80–X89):

| Part | Printed as |
|---|---|
| Lots and categories | Headings with their number and label, in document order; a category's own items come before its subcategories |
| Items | Full OZ, the complete short text in bold, then the long text, wrapped to the description column |
| Quantity, unit, prices | Menge, ME, EP and GB on the item's last line, in German number format (`1.170,500`, `53.257,75`) |
| Item types | A marker line such as *Pauschalposition* or *Bedarfsposition ohne GB* |
| Priced items that are not summed | *Nur Einh.-Preis* in the total column (Bedarfs- and Alternativpositionen) |
| Markup items | Their percentage in the unit price column (`10,00 %`), never as an amount |
| Sums | A subtotal after each category, a subtotal per lot when there are several, and the grand total |
| Page breaks | A carry-forward line (*Übertrag*) at the foot of each page and the head of the next |

Sums and carry-forward lines appear only when the document carries item totals, so an unpriced X83 prints without them. Numbers are never rounded below the precision the document carries: a unit price of `12.345` prints as `12,345`.

Other document kinds (trade, cost, quantity determination) print a flat item list with the same columns.

## Style

```python
from pygaeb.convert.to_pdf import PdfStyle, to_pdf

to_pdf(doc, "tender-en.pdf", style=PdfStyle(locale="en"))       # English labels, 1,170.500
to_pdf(doc, "short.pdf", style=PdfStyle(long_text=False))       # short texts only
to_pdf(doc, "wide.pdf", style=PdfStyle(page_size=(841.89, 595.28), font_size=9))  # A4 landscape
```

| Field | Default | Meaning |
|---|---|---|
| `locale` | `"de"` | Labels and number format: `"de"` or `"en"` |
| `page_size` | A4 portrait | Width and height in points |
| `margin` | 1.5 cm | Page margin in points |
| `font`, `font_bold`, `font_italic` | Helvetica | Font names known to reportlab |
| `font_size`, `title_size` | 8, 14 | Point sizes |
| `leading` | 1.3 | Line height as a multiple of the font size |
| `long_text` | `True` | Print long texts |
| `carry_forward` | `True` | Print carry-forward lines at page breaks |
| `columns` | `(2.6, 8.8, 2.0, 1.2, 1.8, 2.2)` | Relative widths of the OZ, text, quantity, unit, unit price and total columns |

The standard PDF fonts cover Western European text, including umlauts and the euro sign. For other scripts, register a TrueType font with reportlab and pass its name.

## Tracing printed text back to the document

`on_text` is called once for every string drawn, in drawing order. Each `PdfTextRun` carries the text, its `PdfTextRole`, the page, the baseline position and width in points (origin at the bottom-left of the page), the font, and the item, category or lot it came from.

```python
from pygaeb.convert.to_pdf import PdfTextRole, to_pdf

runs = []
to_pdf(doc, "tender.pdf", on_text=runs.append)

for run in runs:
    if run.role is PdfTextRole.TOTAL_PRICE:
        print(run.page, run.item.full_oz, run.text, round(run.x), round(run.y))
```

All text reaches the page through the same function, so nothing appears in the PDF without being reported. That makes the callback useful for linking a page back to its items, building a search index, or checking in tests exactly what was printed where.
