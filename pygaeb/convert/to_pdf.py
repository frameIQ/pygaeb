"""PDF export for GAEB documents.

Generates a printable PDF report of the BoQ structure with totals.
Uses reportlab as an optional dependency.

Usage::

    from pygaeb import GAEBParser
    from pygaeb.convert.to_pdf import to_pdf

    doc = GAEBParser.parse("tender.X83")
    to_pdf(doc, "tender.pdf")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pygaeb.models.document import GAEBDocument


def to_pdf(doc: GAEBDocument, path: str | Path, title: str | None = None) -> None:
    """Render a GAEB document as a printable PDF.

    Args:
        doc: The document to render.
        path: Output PDF file path.
        title: Optional document title (defaults to project name).

    Raises:
        ImportError: If ``reportlab`` is not installed.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as e:
        raise ImportError(
            "PDF export requires reportlab. "
            "Install with: pip install reportlab"
        ) from e

    out_path = Path(path)
    pdf = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title=title or "GAEB Document",
    )

    styles = getSampleStyleSheet()
    story: list[Any] = []

    doc_title = title or (
        doc.award.project_name if doc.is_procurement else "GAEB Document"
    )
    story.append(Paragraph(str(doc_title or "GAEB Document"), styles["Title"]))
    story.append(Spacer(1, 0.3 * cm))

    meta_lines = [
        f"<b>Version:</b> DA XML {doc.source_version.value}",
        f"<b>Phase:</b> {doc.exchange_phase.value}",
        f"<b>Items:</b> {doc.item_count}",
    ]
    if doc.is_procurement:
        if doc.award.project_no:
            meta_lines.append(f"<b>Project:</b> {doc.award.project_no}")
        if doc.grand_total:
            meta_lines.append(
                f"<b>Total:</b> {doc.grand_total:,.2f} {doc.award.currency}"
            )
    for line in meta_lines:
        story.append(Paragraph(line, styles["Normal"]))
    story.append(Spacer(1, 0.5 * cm))

    headers = ["OZ", "Description", "Qty", "Unit", "Unit Price", "Total"]
    data: list[list[str]] = [headers]

    for item in doc.iter_items():
        oz = getattr(item, "oz", "") or ""
        text = (getattr(item, "short_text", "") or "")[:60]
        qty = getattr(item, "qty", None)
        unit = getattr(item, "unit", "") or ""
        up = getattr(item, "unit_price", None)
        tp = getattr(item, "total_price", None)
        data.append([
            str(oz),
            str(text),
            f"{qty:,.3f}" if qty is not None else "",
            str(unit),
            f"{up:,.2f}" if up is not None else "",
            f"{tp:,.2f}" if tp is not None else "",
        ])

    if doc.grand_total:
        data.append([
            "", "Grand total", "", "", "",
            f"{doc.grand_total:,.2f}",
        ])

    table = Table(
        data,
        colWidths=[2 * cm, 7 * cm, 2 * cm, 1.5 * cm, 2.5 * cm, 2.5 * cm],
        repeatRows=1,
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eeeeee")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    story.append(table)

    pdf.build(story)


__all__ = ["to_pdf"]
