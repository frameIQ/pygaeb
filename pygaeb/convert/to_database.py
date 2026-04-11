"""Database export for GAEB documents using SQLAlchemy Core.

Exports a parsed GAEBDocument into normalized relational tables that can
be persisted to SQLite, PostgreSQL, MySQL, etc. via any SQLAlchemy engine.

The schema is intentionally simple and read-optimized — three tables:

  - ``gaeb_document``: one row per parsed document
  - ``gaeb_lot``: lots within documents
  - ``gaeb_item``: items with denormalized lot/category references

Usage::

    from sqlalchemy import create_engine
    from pygaeb import GAEBParser
    from pygaeb.convert.to_database import to_database, create_schema

    engine = create_engine("sqlite:///gaeb.db")
    create_schema(engine)

    doc = GAEBParser.parse("tender.X83")
    doc_id = to_database(doc, engine)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pygaeb.models.document import GAEBDocument

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.sql.schema import MetaData, Table


def _get_metadata() -> tuple[MetaData, Table, Table, Table]:
    """Lazy-import sqlalchemy and build the schema."""
    try:
        from sqlalchemy import (
            Column,
            DateTime,
            Integer,
            MetaData,
            Numeric,
            String,
            Table,
            Text,
        )
    except ImportError as e:
        raise ImportError(
            "Database export requires sqlalchemy. "
            "Install with: pip install sqlalchemy"
        ) from e

    metadata = MetaData()

    documents = Table(
        "gaeb_document", metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("source_file", String(500)),
        Column("source_version", String(10)),
        Column("exchange_phase", String(10)),
        Column("project_no", String(100)),
        Column("project_name", String(500)),
        Column("currency", String(10)),
        Column("grand_total", Numeric(15, 2)),
        Column("item_count", Integer),
        Column("imported_at", DateTime),
    )

    lots = Table(
        "gaeb_lot", metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("document_id", Integer, nullable=False),
        Column("rno", String(20)),
        Column("label", String(500)),
        Column("subtotal", Numeric(15, 2)),
    )

    items = Table(
        "gaeb_item", metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("document_id", Integer, nullable=False),
        Column("lot_rno", String(20)),
        Column("oz", String(50)),
        Column("short_text", Text),
        Column("qty", Numeric(15, 3)),
        Column("unit", String(20)),
        Column("unit_price", Numeric(15, 3)),
        Column("total_price", Numeric(15, 2)),
        Column("item_type", String(30)),
    )

    return metadata, documents, lots, items


def create_schema(engine: Engine) -> None:
    """Create the GAEB tables on the given SQLAlchemy engine.

    Idempotent — uses ``checkfirst=True`` so it won't recreate
    existing tables.
    """
    metadata, _, _, _ = _get_metadata()
    metadata.create_all(engine, checkfirst=True)


def to_database(doc: GAEBDocument, engine: Engine) -> int:
    """Insert a GAEBDocument into the database.

    Returns:
        The newly inserted document's ``id``.

    Raises:
        ImportError: If sqlalchemy is not installed.
    """
    from datetime import datetime

    _, documents, lots, items_t = _get_metadata()

    with engine.begin() as conn:
        result = conn.execute(
            documents.insert().values(
                source_file=doc.source_file,
                source_version=doc.source_version.value,
                exchange_phase=doc.exchange_phase.value,
                project_no=doc.award.project_no if doc.is_procurement else None,
                project_name=doc.award.project_name if doc.is_procurement else None,
                currency=doc.award.currency if doc.is_procurement else None,
                grand_total=doc.grand_total,
                item_count=doc.item_count,
                imported_at=datetime.now(),
            )
        )
        doc_id = result.inserted_primary_key[0]

        if doc.is_procurement:
            for lot in doc.award.boq.lots:
                conn.execute(
                    lots.insert().values(
                        document_id=doc_id,
                        rno=lot.rno,
                        label=lot.label,
                        subtotal=lot.subtotal,
                    )
                )
                for item in lot.iter_items():
                    conn.execute(
                        items_t.insert().values(
                            document_id=doc_id,
                            lot_rno=lot.rno,
                            oz=item.oz,
                            short_text=item.short_text,
                            qty=item.qty,
                            unit=item.unit,
                            unit_price=item.unit_price,
                            total_price=item.total_price,
                            item_type=item.item_type.value,
                        )
                    )
        else:
            for item in doc.iter_items():
                conn.execute(
                    items_t.insert().values(
                        document_id=doc_id,
                        lot_rno=None,
                        oz=getattr(item, "oz", "") or getattr(item, "ele_no", ""),
                        short_text=getattr(item, "short_text", ""),
                        qty=getattr(item, "qty", None),
                        unit=getattr(item, "unit", None),
                        unit_price=getattr(item, "unit_price", None),
                        total_price=getattr(item, "total_price", None),
                        item_type="other",
                    )
                )

    return int(doc_id)


__all__ = ["create_schema", "to_database"]
