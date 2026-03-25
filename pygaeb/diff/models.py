"""Typed result models for BoQ document comparison."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Significance(str, Enum):
    """How important a change is in a construction context."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DiffMode(str, Enum):
    """Controls how strictly the diff validates document compatibility."""

    DEFAULT = "default"
    STRICT = "strict"
    FORCE = "force"


class FieldChange(BaseModel):
    """A single field-level change between two items."""

    field: str
    old_value: Any = None
    new_value: Any = None
    significance: Significance = Significance.MEDIUM
    absolute_delta: Decimal | None = None
    percent_delta: float | None = None

    @property
    def is_numeric(self) -> bool:
        return self.absolute_delta is not None


class ItemAdded(BaseModel):
    """An item present in document B but not in A."""

    oz: str = ""
    short_text: str = ""
    lot_rno: str = ""
    category_rno: str = ""
    total_price: Decimal | None = None


class ItemRemoved(BaseModel):
    """An item present in document A but not in B."""

    oz: str = ""
    short_text: str = ""
    lot_rno: str = ""
    category_rno: str = ""
    total_price: Decimal | None = None


class ItemModified(BaseModel):
    """An item present in both documents with field-level changes."""

    oz: str = ""
    short_text_a: str = ""
    short_text_b: str = ""
    lot_rno: str = ""
    changes: list[FieldChange] = Field(default_factory=list)

    @property
    def max_significance(self) -> Significance:
        if not self.changes:
            return Significance.LOW
        order = [Significance.CRITICAL, Significance.HIGH, Significance.MEDIUM, Significance.LOW]
        for sig in order:
            if any(c.significance == sig for c in self.changes):
                return sig
        return Significance.LOW

    def filter_changes(self, min_significance: Significance) -> list[FieldChange]:
        """Return only changes at or above the given significance level."""
        order = [Significance.CRITICAL, Significance.HIGH, Significance.MEDIUM, Significance.LOW]
        threshold = order.index(min_significance)
        return [c for c in self.changes if order.index(c.significance) <= threshold]


class SectionChange(BaseModel):
    """A category/section that was added or removed."""

    rno: str = ""
    label: str = ""
    lot_rno: str = ""
    item_count: int = 0


class SectionRenamed(BaseModel):
    """A category/section whose label changed."""

    rno: str = ""
    old_label: str = ""
    new_label: str = ""
    lot_rno: str = ""


class ItemMoved(BaseModel):
    """An item that exists in both documents but under different categories."""

    oz: str = ""
    short_text: str = ""
    old_category_rno: str = ""
    new_category_rno: str = ""
    old_lot_rno: str = ""
    new_lot_rno: str = ""


class ItemDiffSummary(BaseModel):
    """Summary of all item-level changes."""

    added: list[ItemAdded] = Field(default_factory=list)
    removed: list[ItemRemoved] = Field(default_factory=list)
    modified: list[ItemModified] = Field(default_factory=list)
    unchanged_count: int = 0

    def filter_modified(
        self, min_significance: Significance = Significance.LOW
    ) -> list[ItemModified]:
        """Return only modified items with at least one change at or above the threshold."""
        order = [Significance.CRITICAL, Significance.HIGH, Significance.MEDIUM, Significance.LOW]
        threshold = order.index(min_significance)
        return [
            m for m in self.modified
            if any(order.index(c.significance) <= threshold for c in m.changes)
        ]


class StructureDiffSummary(BaseModel):
    """Summary of structural (category/section) changes."""

    sections_added: list[SectionChange] = Field(default_factory=list)
    sections_removed: list[SectionChange] = Field(default_factory=list)
    sections_renamed: list[SectionRenamed] = Field(default_factory=list)
    items_moved: list[ItemMoved] = Field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(
            self.sections_added
            or self.sections_removed
            or self.sections_renamed
            or self.items_moved
        )


class MetadataChange(BaseModel):
    """A single metadata field change."""

    field: str
    old_value: Any = None
    new_value: Any = None


class DiffDocInfo(BaseModel):
    """Snapshot of a document's identity for the diff result."""

    source_version: str = ""
    exchange_phase: str = ""
    project_no: str | None = None
    project_name: str | None = None
    currency: str | None = None
    item_count: int = 0
    grand_total: Decimal | None = None


class DiffSummary(BaseModel):
    """Top-level summary of the comparison."""

    has_changes: bool = False
    total_changes: int = 0
    items_added: int = 0
    items_removed: int = 0
    items_modified: int = 0
    items_unchanged: int = 0
    match_ratio: float = 0.0
    is_likely_same_project: bool = True
    financial_impact: Decimal | None = None
    max_significance: Significance = Significance.LOW


class DiffResult(BaseModel):
    """Complete result of comparing two GAEB documents."""

    doc_a: DiffDocInfo = Field(default_factory=DiffDocInfo)
    doc_b: DiffDocInfo = Field(default_factory=DiffDocInfo)
    summary: DiffSummary = Field(default_factory=DiffSummary)
    items: ItemDiffSummary = Field(default_factory=ItemDiffSummary)
    structure: StructureDiffSummary = Field(default_factory=StructureDiffSummary)
    metadata: list[MetadataChange] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
