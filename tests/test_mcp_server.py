"""Tests for the MCP server.

Most of these never touch the filesystem or the MCP SDK: the tool surface is
built from plain functions over a ``GAEBDocument``, so it can be driven directly.

The two load-bearing tests are ``TestGetItem.test_attachment_bytes_never_leak``
and the whole of ``TestContextBounds`` — together they are the executable form of
the context-safety contract.
"""

from __future__ import annotations  # noqa: I001

import inspect
import json
import sys
import threading
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

import pytest

from pygaeb.config import configure, get_settings, reset_settings
from pygaeb.mcp.handles import DocumentCache
from pygaeb.mcp.safety import resolve_roots, resolve_within_roots
from pygaeb.mcp.tools import ToolContext, build_tools
from pygaeb.mcp.views import LONG_TEXT_PREVIEW_CHARS, SHORT_TEXT_CHARS, bound, paginate
from pygaeb.models.boq import BoQ, BoQBody, BoQCtgy, Lot
from pygaeb.models.document import AwardInfo, GAEBDocument, GAEBInfo
from pygaeb.models.enums import ExchangePhase, ItemType, SourceVersion, ValidationMode
from pygaeb.models.item import Attachment, BidderPrice, Item, RichText

from tests.conftest import SAMPLE_V33_XML

# ── Builders ───────────────────────────────────────────────────────────


def _doc(items: list[Item], phase: ExchangePhase = ExchangePhase.X83) -> GAEBDocument:
    ctgy = BoQCtgy(rno="01", label="Rohbau", items=items)
    lot = Lot(rno="1", label="Default", body=BoQBody(categories=[ctgy]))
    return GAEBDocument(
        source_version=SourceVersion.DA_XML_33,
        exchange_phase=phase,
        gaeb_info=GAEBInfo(version="3.3"),
        award=AwardInfo(project_name="Test", currency="EUR", boq=BoQ(lots=[lot])),
    )


def _make_procurement_doc() -> GAEBDocument:
    return _doc(
        [
            Item(
                oz="0010",
                oz_path=["01"],
                short_text="Mauerwerk Innenwand",
                qty=Decimal("100"),
                unit="m2",
                unit_price=Decimal("45.50"),
                total_price=Decimal("4550.00"),
                item_type=ItemType.NORMAL,
            ),
            Item(
                oz="0020",
                oz_path=["01"],
                short_text="Estrich",
                qty=Decimal("50"),
                unit="m2",
                unit_price=Decimal("30.00"),
                total_price=Decimal("1500.00"),
                item_type=ItemType.NORMAL,
            ),
        ]
    )


def _make_huge_doc(n: int = 5000) -> GAEBDocument:
    """An adversarial document: many items, long prose, and a giant outlier."""
    items = [
        Item(
            oz=f"{i:04d}",
            oz_path=["01"],
            short_text=f"Position {i} " + "Beschreibung " * 20,
            qty=Decimal(i + 1),
            unit="m2",
            unit_price=Decimal("10.00"),
            total_price=Decimal((i + 1) * 10),
            item_type=ItemType.NORMAL,
            long_text=RichText.from_plain("Leistungsbeschreibung. " * 25),
        )
        for i in range(n)
    ]
    items[0].long_text = RichText.from_plain("Sehr langer Text. " * 12_000)
    return _doc(items)


def _make_qty_doc() -> GAEBDocument:
    """A real X31 document. Note ``award.boq`` is an empty BoQ, never None."""
    from pygaeb.models.quantity import (
        QtyBoQ,
        QtyBoQBody,
        QtyBoQCtgy,
        QtyDetermination,
        QtyItem,
    )

    return GAEBDocument(
        source_version=SourceVersion.DA_XML_33,
        exchange_phase=ExchangePhase.X31,
        gaeb_info=GAEBInfo(version="3.3"),
        award=AwardInfo(),
        qty_determination=QtyDetermination(
            boq=QtyBoQ(
                body=QtyBoQBody(
                    categories=[QtyBoQCtgy(rno="01", items=[QtyItem(oz="0010", qty=Decimal("5"))])]
                )
            )
        ),
    )


def _make_doc_with_attachment() -> GAEBDocument:
    return _doc(
        [
            Item(
                oz="0010",
                oz_path=["01"],
                short_text="Item with a large attachment",
                qty=Decimal("1"),
                unit="Stk",
                unit_price=Decimal("100.00"),
                total_price=Decimal("100.00"),
                attachments=[
                    Attachment(
                        filename="plan.pdf",
                        mime_type="application/pdf",
                        data=b"\xde\xad\xbe\xef" * 250_000,  # 1 MB
                    )
                ],
            )
        ]
    )


def _ctx(doc: GAEBDocument, tmp_path: Path, **kw: object) -> ToolContext:
    """A ToolContext with *doc* pre-seeded under a known handle."""
    cache = DocumentCache()
    cache.put("doc_test", tmp_path / "tender.X83", doc)
    return ToolContext(cache=cache, roots=[tmp_path.resolve()], **kw)  # type: ignore[arg-type]


def _tools(ctx: ToolContext) -> dict[str, object]:
    return {t.__name__: t for t in build_tools(ctx)}


async def _call(tool: object, **kwargs: object) -> dict:
    """Invoke a tool regardless of whether it is sync or async."""
    result = tool(**kwargs)  # type: ignore[operator]
    if inspect.isawaitable(result):
        result = await result
    return result  # type: ignore[return-value]


@pytest.fixture(autouse=True)
def _reset_settings():
    yield
    reset_settings()


# ── Path safety ────────────────────────────────────────────────────────


class TestPathSafety:
    def test_accepts_file_inside_root(self, tmp_path: Path):
        f = tmp_path / "tender.X83"
        f.write_text(SAMPLE_V33_XML)
        assert resolve_within_roots(str(f), [tmp_path.resolve()]) == f.resolve()

    def test_rejects_path_outside_root(self, tmp_path: Path):
        outside = tmp_path.parent / "outside.X83"
        outside.write_text(SAMPLE_V33_XML)
        inner = tmp_path / "inner"
        inner.mkdir()
        with pytest.raises(ValueError, match="outside the allowed roots"):
            resolve_within_roots(str(outside), [inner.resolve()])

    def test_rejects_traversal(self, tmp_path: Path):
        root = tmp_path / "root"
        root.mkdir()
        (tmp_path / "secret.X83").write_text(SAMPLE_V33_XML)
        with pytest.raises(ValueError, match="outside the allowed roots"):
            resolve_within_roots(str(root / ".." / "secret.X83"), [root.resolve()])

    def test_rejects_symlink_escaping_root(self, tmp_path: Path):
        root = tmp_path / "root"
        root.mkdir()
        target = tmp_path / "elsewhere.X83"
        target.write_text(SAMPLE_V33_XML)
        link = root / "link.X83"
        link.symlink_to(target)
        # resolve() runs before containment, so the symlink is followed then rejected.
        with pytest.raises(ValueError, match="outside the allowed roots"):
            resolve_within_roots(str(link), [root.resolve()])

    def test_rejects_unknown_extension(self, tmp_path: Path):
        f = tmp_path / "passwd.txt"
        f.write_text("root:x:0:0")
        with pytest.raises(ValueError, match="Unrecognised GAEB extension"):
            resolve_within_roots(str(f), [tmp_path.resolve()])

    def test_allow_any_extension_overrides(self, tmp_path: Path):
        f = tmp_path / "weird.dat"
        f.write_text("x")
        assert resolve_within_roots(
            str(f), [tmp_path.resolve()], allow_any_extension=True
        ) == f.resolve()

    def test_accepts_p_and_d_extensions(self, tmp_path: Path):
        for name in ("a.P83", "b.d83", "c.X86ZE", "d.xml"):
            f = tmp_path / name
            f.write_text("x")
            assert resolve_within_roots(str(f), [tmp_path.resolve()]) == f.resolve()

    def test_rejects_missing_file(self, tmp_path: Path):
        with pytest.raises(ValueError, match="does not exist"):
            resolve_within_roots(str(tmp_path / "nope.X83"), [tmp_path.resolve()])

    def test_rejects_oversized_file(self, tmp_path: Path):
        f = tmp_path / "big.X83"
        f.write_bytes(b"x" * (2 * 1024 * 1024))
        configure(max_file_size_mb=1)
        with pytest.raises(ValueError, match="over the 1 MB limit"):
            resolve_within_roots(str(f), [tmp_path.resolve()])

    def test_resolve_roots_rejects_missing_dir(self, tmp_path: Path):
        with pytest.raises(ValueError, match="not an existing directory"):
            resolve_roots([str(tmp_path / "nope")])


# ── Handle cache ───────────────────────────────────────────────────────


class TestHandleCache:
    async def test_same_file_same_handle_and_parses_once(self, tmp_path: Path, monkeypatch):
        f = tmp_path / "tender.X83"
        f.write_text(SAMPLE_V33_XML)
        ctx = ToolContext(cache=DocumentCache(), roots=[tmp_path.resolve()])
        open_document = _tools(ctx)["open_document"]

        calls = {"n": 0}
        from pygaeb.parser import gaeb_parser

        real = gaeb_parser.GAEBParser.parse

        def counting(*a, **k):
            calls["n"] += 1
            return real(*a, **k)

        monkeypatch.setattr(gaeb_parser.GAEBParser, "parse", staticmethod(counting))

        first = await open_document(path=str(f))  # type: ignore[operator]
        second = await open_document(path=str(f))  # type: ignore[operator]

        assert first["handle"] == second["handle"]
        assert first["cached"] is False
        assert second["cached"] is True
        assert calls["n"] == 1, "second open must not re-parse"

    async def test_cached_open_refreshes_lru(self, tmp_path: Path):
        """A document kept hot via open_document must not be the eviction victim."""
        for name in ("a", "b", "c"):
            (tmp_path / f"{name}.X83").write_text(SAMPLE_V33_XML + f"<!-- {name} -->")
        ctx = ToolContext(cache=DocumentCache(max_documents=2), roots=[tmp_path.resolve()])
        open_document = _tools(ctx)["open_document"]

        handle_a = (await open_document(path=str(tmp_path / "a.X83")))["handle"]  # type: ignore[operator]
        handle_b = (await open_document(path=str(tmp_path / "b.X83")))["handle"]  # type: ignore[operator]

        # Re-open a via the cached path — this must refresh its recency.
        again = await open_document(path=str(tmp_path / "a.X83"))  # type: ignore[operator]
        assert again["cached"] is True

        await open_document(path=str(tmp_path / "c.X83"))  # type: ignore[operator]
        assert handle_a in ctx.cache, "recently re-opened document was evicted"
        assert handle_b not in ctx.cache, "the actual LRU document should have been evicted"

    def test_mtime_change_yields_new_handle(self, tmp_path: Path):
        f = tmp_path / "tender.X83"
        f.write_text(SAMPLE_V33_XML)
        before = DocumentCache.derive_handle(f, ValidationMode.LENIENT)
        f.write_text(SAMPLE_V33_XML + "\n<!-- touched -->")
        after = DocumentCache.derive_handle(f, ValidationMode.LENIENT)
        assert before != after

    def test_validation_mode_is_part_of_the_key(self, tmp_path: Path):
        f = tmp_path / "tender.X83"
        f.write_text(SAMPLE_V33_XML)
        lenient = DocumentCache.derive_handle(f, ValidationMode.LENIENT)
        strict = DocumentCache.derive_handle(f, ValidationMode.STRICT)
        assert lenient != strict

    def test_unknown_handle_message_is_actionable(self, tmp_path: Path):
        cache = DocumentCache()
        with pytest.raises(ValueError, match="Unknown or expired handle"):
            cache.get("doc_nope")

    def test_evicted_handle_error_names_the_file(self, tmp_path: Path):
        cache = DocumentCache(max_documents=1)
        cache.put("doc_a", tmp_path / "a.X83", _make_procurement_doc())
        cache.put("doc_b", tmp_path / "b.X83", _make_procurement_doc())
        with pytest.raises(ValueError, match=r"a\.X83"):
            cache.get("doc_a")

    def test_evicts_by_count_lru(self, tmp_path: Path):
        cache = DocumentCache(max_documents=2)
        for name in ("a", "b", "c"):
            cache.put(f"doc_{name}", tmp_path / f"{name}.X83", _make_procurement_doc())
        assert len(cache) == 2
        assert "doc_a" not in cache
        assert "doc_c" in cache

    def test_evicts_by_megabytes(self, tmp_path: Path):
        cache = DocumentCache(max_documents=100, max_cache_mb=0)
        cache.put("doc_a", tmp_path / "a.X83", _make_procurement_doc())
        cache.put("doc_b", tmp_path / "b.X83", _make_procurement_doc())
        # Newest survives even when it alone exceeds the budget.
        assert len(cache) == 1
        assert "doc_b" in cache

    def test_get_refreshes_lru_position(self, tmp_path: Path):
        cache = DocumentCache(max_documents=2)
        cache.put("doc_a", tmp_path / "a.X83", _make_procurement_doc())
        cache.put("doc_b", tmp_path / "b.X83", _make_procurement_doc())
        cache.get("doc_a")  # a is now most-recent
        cache.put("doc_c", tmp_path / "c.X83", _make_procurement_doc())
        assert "doc_a" in cache
        assert "doc_b" not in cache

    def test_tree_rejects_non_procurement(self, tmp_path: Path):
        cache = DocumentCache()
        entry = cache.put("doc_q", tmp_path / "q.X31", _make_qty_doc())
        with pytest.raises(ValueError, match="no bill-of-quantities structure"):
            _ = entry.tree


# ── open_document ──────────────────────────────────────────────────────


class TestOpenDocument:
    async def test_summary_shape_and_decimal_strings(self, tmp_path: Path):
        f = tmp_path / "tender.X83"
        f.write_text(SAMPLE_V33_XML)
        ctx = ToolContext(cache=DocumentCache(), roots=[tmp_path.resolve()])
        result = await _tools(ctx)["open_document"](path=str(f))  # type: ignore[operator]

        for key in ("handle", "exchange_phase", "document_kind", "item_count", "quality"):
            assert key in result
        assert result["handle"].startswith("doc_")
        assert isinstance(result["grand_total"], str), "Decimals must not become floats"
        assert set(result["validation_counts"]) == {"error", "warning", "info"}

    def test_lot_labels_are_capped(self, tmp_path: Path):
        doc = _make_procurement_doc()
        doc.award.boq.lots = [
            Lot(rno=str(i), label=f"Lot {i}", body=BoQBody()) for i in range(50)
        ]
        ctx = _ctx(doc, tmp_path)
        entry = ctx.cache.get("doc_test")
        from pygaeb.mcp import views

        summary = views.document_summary(entry.doc, "doc_test", "x.X83", cached=False)
        assert len(summary["lot_labels"]) == 20
        assert summary["lot_labels_truncated"] is True
        assert summary["lot_count"] == 50


# ── list_structure ─────────────────────────────────────────────────────


class TestListStructure:
    def test_returns_direct_children_with_counts(self, tmp_path: Path):
        ctx = _ctx(_make_procurement_doc(), tmp_path)
        result = _tools(ctx)["list_structure"](handle="doc_test")  # type: ignore[operator]
        assert result["parent"]["kind"] == "root"
        assert [n["kind"] for n in result["nodes"]] == ["lot"]
        assert result["nodes"][0]["item_count"] == 2

    def test_unknown_rno_raises(self, tmp_path: Path):
        ctx = _ctx(_make_procurement_doc(), tmp_path)
        with pytest.raises(ValueError, match="No category or lot with rno"):
            _tools(ctx)["list_structure"](handle="doc_test", rno="99")  # type: ignore[operator]

    def test_pagination(self, tmp_path: Path):
        ctx = _ctx(_make_huge_doc(120), tmp_path)
        result = _tools(ctx)["list_structure"](  # type: ignore[operator]
            handle="doc_test", rno="01", limit=10
        )
        assert len(result["nodes"]) == 10
        assert result["total_matched"] == 120
        assert result["has_more"] is True


# ── list_items ─────────────────────────────────────────────────────────


class TestListItems:
    def test_sort_total_desc(self, tmp_path: Path):
        ctx = _ctx(_make_procurement_doc(), tmp_path)
        result = _tools(ctx)["list_items"](handle="doc_test", sort="total_desc")  # type: ignore[operator]
        totals = [Decimal(i["total_price"]) for i in result["items"]]
        assert totals == sorted(totals, reverse=True)

    def test_text_filter(self, tmp_path: Path):
        ctx = _ctx(_make_procurement_doc(), tmp_path)
        result = _tools(ctx)["list_items"](handle="doc_test", text_contains="estrich")  # type: ignore[operator]
        assert result["total_matched"] == 1
        assert result["items"][0]["short_text"] == "Estrich"

    def test_total_range_filter(self, tmp_path: Path):
        ctx = _ctx(_make_procurement_doc(), tmp_path)
        result = _tools(ctx)["list_items"](handle="doc_test", min_total=2000)  # type: ignore[operator]
        assert result["total_matched"] == 1

    def test_nan_and_infinity_filters_rejected_cleanly(self, tmp_path: Path):
        """NaN would poison Decimal comparisons with a raw InvalidOperation."""
        ctx = _ctx(_make_procurement_doc(), tmp_path)
        tool = _tools(ctx)["list_items"]
        for evil in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValueError, match="finite"):
                tool(handle="doc_test", min_total=evil)  # type: ignore[operator]

    def test_total_matched_exceeds_page(self, tmp_path: Path):
        ctx = _ctx(_make_huge_doc(500), tmp_path)
        result = _tools(ctx)["list_items"](handle="doc_test", limit=10)  # type: ignore[operator]
        assert len(result["items"]) == 10
        assert result["total_matched"] == 500
        assert result["has_more"] is True

    def test_sum_and_pct(self, tmp_path: Path):
        ctx = _ctx(_make_procurement_doc(), tmp_path)
        result = _tools(ctx)["list_items"](handle="doc_test")  # type: ignore[operator]
        assert result["sum_of_matched_totals"] == "6050.00"
        assert result["pct_of_grand_total"] == 100.0

    def test_rows_omit_long_text(self, tmp_path: Path):
        ctx = _ctx(_make_huge_doc(3), tmp_path)
        result = _tools(ctx)["list_items"](handle="doc_test")  # type: ignore[operator]
        row = result["items"][0]
        assert "long_text" not in row
        assert "long_text_preview" not in row
        assert row["has_long_text"] is True
        assert row["long_text_chars"] > 0

    def test_short_text_clipped_with_true_length(self, tmp_path: Path):
        ctx = _ctx(_make_huge_doc(3), tmp_path)
        result = _tools(ctx)["list_items"](handle="doc_test")  # type: ignore[operator]
        row = result["items"][0]
        assert len(row["short_text"]) == SHORT_TEXT_CHARS
        assert row["short_text_chars"] > SHORT_TEXT_CHARS

    def test_alternative_items_excluded_from_sum_vob(self, tmp_path: Path):
        """VOB/A: alternative positions carry prices but are not contract value."""
        doc = _doc(
            [
                Item(
                    oz="0010",
                    oz_path=["01"],
                    short_text="Normalposition",
                    total_price=Decimal("100.00"),
                    item_type=ItemType.NORMAL,
                ),
                Item(
                    oz="0020",
                    oz_path=["01"],
                    short_text="Alternativposition",
                    total_price=Decimal("50.00"),
                    item_type=ItemType.ALTERNATIVE,
                ),
            ]
        )
        ctx = _ctx(doc, tmp_path)
        result = _tools(ctx)["list_items"](handle="doc_test")  # type: ignore[operator]

        # Sum must match the library's own affects_total convention...
        assert result["sum_of_matched_totals"] == "100.00"
        assert result["pct_of_grand_total"] == 100.0
        # ...and each row must say whether it counted, so the model can see why.
        by_oz = {r["oz"]: r for r in result["items"]}
        assert by_oz["01.0010"]["affects_total"] is True
        assert by_oz["01.0020"]["affects_total"] is False


# ── get_item ───────────────────────────────────────────────────────────


class TestGetItem:
    def test_attachment_bytes_never_leak(self, tmp_path: Path):
        """The regression guard for the worst failure mode in the design."""
        ctx = _ctx(_make_doc_with_attachment(), tmp_path)
        payload = _tools(ctx)["get_item"](handle="doc_test", oz="0010")  # type: ignore[operator]
        encoded = json.dumps(payload)

        assert payload["attachments"] == [
            {"filename": "plan.pdf", "mime_type": "application/pdf", "size_bytes": 1_000_000}
        ]
        assert "data" not in encoded
        assert "deadbeef" not in encoded.lower()
        assert len(encoded) < 2_000

    def test_long_text_is_previewed_not_dumped(self, tmp_path: Path):
        ctx = _ctx(_make_huge_doc(3), tmp_path)
        payload = _tools(ctx)["get_item"](handle="doc_test", oz="0000")  # type: ignore[operator]
        assert len(payload["long_text_preview"]) == LONG_TEXT_PREVIEW_CHARS
        assert payload["long_text_chars"] > 200_000, "true length must still be reported"

    def test_unknown_oz_raises(self, tmp_path: Path):
        ctx = _ctx(_make_procurement_doc(), tmp_path)
        with pytest.raises(ValueError, match="No item with OZ"):
            _tools(ctx)["get_item"](handle="doc_test", oz="9999")  # type: ignore[operator]


# ── get_item_long_text ─────────────────────────────────────────────────


class TestLongTextPaging:
    def test_windows_and_has_more(self, tmp_path: Path):
        ctx = _ctx(_make_huge_doc(3), tmp_path)
        tool = _tools(ctx)["get_item_long_text"]
        first = tool(handle="doc_test", oz="0000", limit=1000)  # type: ignore[operator]
        assert len(first["text"]) == 1000
        assert first["offset"] == 0
        assert first["has_more"] is True

        total = first["total_chars"]
        last = tool(handle="doc_test", oz="0000", offset=total - 10, limit=1000)  # type: ignore[operator]
        assert last["has_more"] is False
        assert len(last["text"]) == 10

    def test_windows_are_contiguous(self, tmp_path: Path):
        ctx = _ctx(_make_huge_doc(3), tmp_path)
        tool = _tools(ctx)["get_item_long_text"]
        a = tool(handle="doc_test", oz="0000", offset=0, limit=100)  # type: ignore[operator]
        b = tool(handle="doc_test", oz="0000", offset=100, limit=100)  # type: ignore[operator]
        assert a["text"] != b["text"]
        assert len(a["text"] + b["text"]) == 200


# ── search_items ───────────────────────────────────────────────────────


class TestSearchItems:
    async def test_finds_in_short_text_with_snippet(self, tmp_path: Path):
        ctx = _ctx(_make_procurement_doc(), tmp_path)
        result = await _tools(ctx)["search_items"](handle="doc_test", query="Estrich")  # type: ignore[operator]
        assert result["total_matched"] == 1
        match = result["matches"][0]
        assert match["field"] == "short_text"
        assert "Estrich" in match["snippet"]

    async def test_finds_in_long_text_and_snippet_is_bounded(self, tmp_path: Path):
        doc = _make_procurement_doc()
        doc.award.boq.lots[0].body.categories[0].items[0].long_text = RichText.from_plain(
            "Vorbemerkung. " * 5000 + "ASBEST festgestellt. " + "Nachwort. " * 5000
        )
        ctx = _ctx(doc, tmp_path)
        result = await _tools(ctx)["search_items"](handle="doc_test", query="asbest")  # type: ignore[operator]
        match = result["matches"][0]
        assert match["field"] == "long_text"
        assert "ASBEST" in match["snippet"]
        assert len(match["snippet"]) < 300, "snippet must be a window, not the field"

    async def test_no_matches(self, tmp_path: Path):
        ctx = _ctx(_make_procurement_doc(), tmp_path)
        result = await _tools(ctx)["search_items"](handle="doc_test", query="zzzz")  # type: ignore[operator]
        assert result["total_matched"] == 0
        assert result["matches"] == []


# ── list_validation_issues ─────────────────────────────────────────────


class TestValidationIssues:
    def test_counts_always_present_and_filter_works(self, tmp_path: Path):
        doc = _make_procurement_doc()
        doc.add_warning("w1")
        doc.add_warning("w2")
        doc.add_error("e1")
        ctx = _ctx(doc, tmp_path)
        tool = _tools(ctx)["list_validation_issues"]

        every = tool(handle="doc_test")  # type: ignore[operator]
        assert every["counts"] == {"error": 1, "warning": 2, "info": 0}
        assert every["total_matched"] == 3

        errors = tool(handle="doc_test", severity="ERROR")  # type: ignore[operator]
        assert errors["total_matched"] == 1
        assert errors["counts"] == {"error": 1, "warning": 2, "info": 0}, "counts stay complete"


# ── compare_documents ──────────────────────────────────────────────────


class TestCompareDocuments:
    async def test_reports_counts_and_changes(self, tmp_path: Path):
        a = _make_procurement_doc()
        b = _make_procurement_doc()
        b.award.boq.lots[0].body.categories[0].items[0].unit_price = Decimal("99.00")
        b.award.boq.lots[0].body.categories[0].items[0].total_price = Decimal("9900.00")

        cache = DocumentCache()
        cache.put("doc_a", tmp_path / "a.X83", a)
        cache.put("doc_b", tmp_path / "b.X83", b)
        ctx = ToolContext(cache=cache, roots=[tmp_path.resolve()])

        result = await _tools(ctx)["compare_documents"](handle_a="doc_a", handle_b="doc_b")  # type: ignore[operator]
        assert result["summary"]["has_changes"] is True
        assert result["counts"]["modified"] == 1
        assert result["changes"][0]["kind"] == "modified"
        assert isinstance(result["summary"]["financial_impact"], str)

    async def test_non_procurement_raises_valueerror_not_typeerror(self, tmp_path: Path):
        cache = DocumentCache()
        cache.put("doc_a", tmp_path / "a.X83", _make_procurement_doc())
        cache.put("doc_b", tmp_path / "b.X31", _make_qty_doc())
        ctx = ToolContext(cache=cache, roots=[tmp_path.resolve()])

        with pytest.raises(ValueError, match="two procurement documents"):
            await _tools(ctx)["compare_documents"](handle_a="doc_a", handle_b="doc_b")  # type: ignore[operator]

    async def test_diff_computed_once_across_pages(self, tmp_path: Path, monkeypatch):
        """Paging through changes must not re-run the diff engine."""
        from pygaeb.diff.boq_diff import BoQDiff

        a = _make_procurement_doc()
        b = _make_procurement_doc()
        b.award.boq.lots[0].body.categories[0].items[0].total_price = Decimal("9999.00")

        cache = DocumentCache()
        cache.put("doc_a", tmp_path / "a.X83", a)
        cache.put("doc_b", tmp_path / "b.X83", b)
        ctx = ToolContext(cache=cache, roots=[tmp_path.resolve()])
        compare = _tools(ctx)["compare_documents"]

        calls = {"n": 0}
        real = BoQDiff.compare

        def counting(*args, **kwargs):
            calls["n"] += 1
            return real(*args, **kwargs)

        monkeypatch.setattr(BoQDiff, "compare", staticmethod(counting))

        page1 = await compare(handle_a="doc_a", handle_b="doc_b", limit=1, offset=0)  # type: ignore[operator]
        page2 = await compare(handle_a="doc_a", handle_b="doc_b", limit=1, offset=1)  # type: ignore[operator]

        assert calls["n"] == 1, "diff must be cached per handle pair"
        assert page1["total_matched"] == page2["total_matched"]


# ── Context bounds — the spec ──────────────────────────────────────────


class TestContextBounds:
    """Every tool, against an adversarial document, must stay under the budget."""

    CALLS: ClassVar[list[tuple[str, dict]]] = [
        ("list_structure", {"handle": "doc_test"}),
        ("list_structure", {"handle": "doc_test", "rno": "01", "limit": 200}),
        ("list_items", {"handle": "doc_test"}),
        ("list_items", {"handle": "doc_test", "limit": 200}),
        ("list_items", {"handle": "doc_test", "sort": "total_desc", "limit": 200}),
        ("get_item", {"handle": "doc_test", "oz": "0000"}),
        ("get_item_long_text", {"handle": "doc_test", "oz": "0000"}),
        ("get_item_long_text", {"handle": "doc_test", "oz": "0000", "limit": 20_000}),
        ("search_items", {"handle": "doc_test", "query": "Beschreibung", "limit": 200}),
        ("list_validation_issues", {"handle": "doc_test", "limit": 200}),
    ]

    @pytest.mark.parametrize("name,kwargs", CALLS)
    async def test_response_fits_budget(self, name: str, kwargs: dict, tmp_path: Path):
        ctx = _ctx(_make_huge_doc(5000), tmp_path)
        result = await _call(_tools(ctx)[name], **kwargs)
        encoded = json.dumps(result, ensure_ascii=False)
        budget = get_settings().mcp_max_response_chars
        assert len(encoded) <= budget, f"{name} returned {len(encoded)} chars, budget {budget}"

    def test_no_attachment_bytes_in_any_response(self, tmp_path: Path):
        ctx = _ctx(_make_doc_with_attachment(), tmp_path)
        tools = _tools(ctx)
        for name in ("list_items", "get_item", "list_structure"):
            kwargs = {"handle": "doc_test"}
            if name == "get_item":
                kwargs["oz"] = "0010"
            encoded = json.dumps(tools[name](**kwargs))  # type: ignore[operator]
            assert "deadbeef" not in encoded.lower()

    def test_bound_drops_entries_and_flags(self):
        configure(mcp_max_response_chars=200)
        payload = bound({"items": [{"x": "y" * 20} for _ in range(50)]})
        assert payload["truncated"] is True
        assert payload["truncated_reason"] == "response_size"
        assert len(payload["items"]) < 50

    def test_bound_leaves_small_payloads_alone(self):
        payload = bound({"a": 1})
        assert "truncated" not in payload

    def test_paginate_clamps_to_max_page_size(self):
        configure(mcp_max_page_size=5)
        page, total, has_more = paginate(list(range(100)), 0, 1000)
        assert len(page) == 5
        assert total == 100
        assert has_more is True


# ── analyze_bids ───────────────────────────────────────────────────────


def _make_x82_doc() -> GAEBDocument:
    """A Preisspiegel: two items, each priced by two bidders."""

    def _priced(oz: str, alpha_up: str, beta_up: str, qty: str) -> Item:
        q = Decimal(qty)
        return Item(
            oz=oz,
            oz_path=["01"],
            short_text=f"Position {oz}",
            qty=q,
            unit="m2",
            item_type=ItemType.NORMAL,
            bidder_prices=[
                BidderPrice(
                    bidder_name="Alpha",
                    unit_price=Decimal(alpha_up),
                    total_price=Decimal(alpha_up) * q,
                ),
                BidderPrice(
                    bidder_name="Beta",
                    unit_price=Decimal(beta_up),
                    total_price=Decimal(beta_up) * q,
                ),
            ],
        )

    doc = _doc(
        [_priced("0010", "40.00", "60.00", "10"), _priced("0020", "10.00", "12.00", "5")],
        phase=ExchangePhase.X82,
    )
    return doc


class TestAnalyzeBids:
    async def test_x82_ranking_and_lowest_bidder(self, tmp_path: Path):
        ctx = _ctx(_make_x82_doc(), tmp_path)
        result = await _tools(ctx)["analyze_bids"](tender_handle="doc_test")  # type: ignore[operator]

        # Alpha: 40*10 + 10*5 = 450; Beta: 60*10 + 12*5 = 660.
        assert result["lowest_bidder"] == "Alpha"
        assert result["bidder_count"] == 2
        assert [r["rank"] for r in result["ranking"]] == [1, 2]
        assert result["ranking"][0] == {"bidder": "Alpha", "grand_total": "450.00", "rank": 1}

    async def test_spread_decimals_are_strings_counts_are_ints(self, tmp_path: Path):
        ctx = _ctx(_make_x82_doc(), tmp_path)
        result = await _tools(ctx)["analyze_bids"](  # type: ignore[operator]
            tender_handle="doc_test", spread_for=["0010"]
        )
        spread = result["spreads"]["0010"]
        assert spread["min"] == "40.00"
        assert spread["max"] == "60.00"
        assert spread["spread"] == "20.00"
        assert isinstance(spread["count"], int), "counts must stay numbers, not strings"

    async def test_x84_path_with_bid_handles(self, tmp_path: Path):
        tender = _make_procurement_doc()
        bid = _make_procurement_doc()
        cache = DocumentCache()
        cache.put("doc_t", tmp_path / "t.X83", tender)
        cache.put("doc_bid", tmp_path / "bid.X84", bid)
        ctx = ToolContext(cache=cache, roots=[tmp_path.resolve()])

        result = await _tools(ctx)["analyze_bids"](  # type: ignore[operator]
            tender_handle="doc_t", bids=[{"name": "Bidder A", "handle": "doc_bid"}]
        )
        assert result["bidder_count"] == 1
        assert result["lowest_bidder"] == "Bidder A"

    async def test_incomplete_bid_entry_raises(self, tmp_path: Path):
        ctx = _ctx(_make_procurement_doc(), tmp_path)
        with pytest.raises(ValueError, match="both 'name' and 'handle'"):
            await _tools(ctx)["analyze_bids"](  # type: ignore[operator]
                tender_handle="doc_test", bids=[{"name": "A"}]
            )


# ── Event-loop safety ──────────────────────────────────────────────────


class TestEventLoopSafety:
    """The SDK calls sync tools directly on the event loop; heavy work must not."""

    HEAVY: ClassVar[list[str]] = [
        "open_document",
        "search_items",
        "compare_documents",
        "analyze_bids",
        "export_document",
        "convert_document",
    ]
    LIGHT: ClassVar[list[str]] = [
        "list_structure",
        "list_items",
        "get_item",
        "get_item_long_text",
        "list_validation_issues",
    ]

    def test_heavy_tools_are_async_light_tools_are_not(self, tmp_path: Path):
        ctx = _ctx(
            _make_procurement_doc(), tmp_path, allow_write=True, output_dir=tmp_path.resolve()
        )
        tools = _tools(ctx)
        for name in self.HEAVY:
            assert inspect.iscoroutinefunction(tools[name]), f"{name} must be async"
        for name in self.LIGHT:
            assert not inspect.iscoroutinefunction(tools[name]), (
                f"{name} is sync by design — async without an await point buys nothing"
            )

    async def test_parse_runs_off_the_event_loop(self, tmp_path: Path, monkeypatch):
        """The regression guard for H1: parsing must happen in a worker thread."""
        f = tmp_path / "tender.X83"
        f.write_text(SAMPLE_V33_XML)
        ctx = ToolContext(cache=DocumentCache(), roots=[tmp_path.resolve()])

        from pygaeb.parser import gaeb_parser

        seen: dict[str, threading.Thread] = {}
        real = gaeb_parser.GAEBParser.parse

        def spy(*args, **kwargs):
            seen["thread"] = threading.current_thread()
            return real(*args, **kwargs)

        monkeypatch.setattr(gaeb_parser.GAEBParser, "parse", staticmethod(spy))
        await _tools(ctx)["open_document"](path=str(f))  # type: ignore[operator]

        assert seen["thread"] is not threading.main_thread(), (
            "parse ran on the event-loop thread — a large file would stall the server"
        )


# ── Cross-kind tolerance ───────────────────────────────────────────────


class TestKindTolerance:
    def test_list_items_survives_quantity_document(self, tmp_path: Path):
        """QtyItem has no short_text/unit/item_type — projections must not crash."""
        from pygaeb.models.quantity import QtyBoQ, QtyBoQBody, QtyBoQCtgy, QtyDetermination, QtyItem

        qty_doc = GAEBDocument(
            source_version=SourceVersion.DA_XML_33,
            exchange_phase=ExchangePhase.X31,
            gaeb_info=GAEBInfo(version="3.3"),
            award=AwardInfo(),
            qty_determination=QtyDetermination(
                boq=QtyBoQ(
                    body=QtyBoQBody(
                        categories=[
                            QtyBoQCtgy(rno="01", items=[QtyItem(oz="0010", qty=Decimal("5"))])
                        ]
                    )
                )
            ),
        )
        ctx = _ctx(qty_doc, tmp_path)
        result = _tools(ctx)["list_items"](handle="doc_test")  # type: ignore[operator]
        row = result["items"][0]
        assert row["oz"] == "0010"
        assert row["qty"] == "5"
        assert row["short_text"] == ""
        assert row["item_type"] is None


# ── Write gating ───────────────────────────────────────────────────────


class TestWriteTools:
    def test_absent_by_default(self, tmp_path: Path):
        names = {t.__name__ for t in build_tools(_ctx(_make_procurement_doc(), tmp_path))}
        assert "export_document" not in names
        assert "convert_document" not in names
        assert len(names) == 9

    def test_present_when_enabled(self, tmp_path: Path):
        ctx = _ctx(
            _make_procurement_doc(), tmp_path, allow_write=True, output_dir=tmp_path.resolve()
        )
        names = {t.__name__ for t in build_tools(ctx)}
        assert {"export_document", "convert_document"} <= names
        assert len(names) == 11

    async def test_export_writes_and_returns_path_only(self, tmp_path: Path):
        out = tmp_path / "out"
        out.mkdir()
        ctx = _ctx(_make_procurement_doc(), tmp_path, allow_write=True, output_dir=out.resolve())
        result = await _tools(ctx)["export_document"](  # type: ignore[operator]
            handle="doc_test", output_path=str(out / "x.json"), format="json"
        )
        assert Path(result["path"]).exists()
        assert result["bytes_written"] > 0
        assert "content" not in result

    async def test_export_outside_output_dir_rejected(self, tmp_path: Path):
        out = tmp_path / "out"
        out.mkdir()
        ctx = _ctx(_make_procurement_doc(), tmp_path, allow_write=True, output_dir=out.resolve())
        with pytest.raises(ValueError, match="outside the allowed roots"):
            await _tools(ctx)["export_document"](  # type: ignore[operator]
                handle="doc_test", output_path=str(tmp_path / "escape.json"), format="json"
            )


# ── SDK boundary ───────────────────────────────────────────────────────


class TestImportGuard:
    def test_helpful_error_without_the_extra(self, monkeypatch):
        import pygaeb.mcp.server as server_mod

        monkeypatch.setitem(sys.modules, "mcp", None)
        monkeypatch.setitem(sys.modules, "mcp.server", None)
        monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", None)
        with pytest.raises(ImportError, match=r"pip install pyGAEB\[mcp\]"):
            server_mod._ensure_mcp()

    def test_sdk_free_modules_do_not_import_mcp(self):
        for mod in ("pygaeb.mcp.views", "pygaeb.mcp.handles", "pygaeb.mcp.safety",
                    "pygaeb.mcp.tools", "pygaeb.mcp.prompts"):
            source = Path(mod.replace(".", "/") + ".py").read_text()
            assert "from mcp" not in source and "import mcp" not in source, (
                f"{mod} must stay SDK-free"
            )


class TestPackageShadowing:
    def test_pygaeb_mcp_does_not_shadow_the_sdk(self):
        """`pygaeb/mcp/` sits next to the `mcp` SDK; absolute imports must win."""
        import mcp
        import mcp.server.fastmcp as sdk

        import pygaeb.mcp as ours

        # The bare name `mcp` must resolve to the SDK, not to pygaeb.mcp.
        assert mcp.__name__ == "mcp"
        assert ours.__name__ == "pygaeb.mcp"
        assert Path(sdk.__file__).parent != Path(ours.__file__).parent
        assert hasattr(sdk, "FastMCP")


class TestServerRegistration:
    def test_registers_nine_tools_with_descriptions(self, tmp_path: Path):
        import asyncio

        from pygaeb.mcp.server import create_server

        server = create_server(roots=[str(tmp_path)])
        tools = asyncio.run(server.list_tools())
        assert len(tools) == 9
        assert all((t.description or "").strip() for t in tools)
        assert all(t.inputSchema["type"] == "object" for t in tools)

    def test_registers_prompts(self, tmp_path: Path):
        import asyncio

        from pygaeb.mcp.server import create_server

        server = create_server(roots=[str(tmp_path)])
        names = {p.name for p in asyncio.run(server.list_prompts())}
        assert names == {"tender_review", "compare_tenders", "bid_evaluation"}

    def test_tool_annotations_distinguish_read_from_write(self, tmp_path: Path):
        """Clients gate confirmation prompts on these hints — they must be set."""
        import asyncio

        from pygaeb.mcp.server import create_server

        out = tmp_path / "out"
        out.mkdir()
        server = create_server(
            roots=[str(tmp_path)], allow_write=True, output_dir=str(out)
        )
        tools = asyncio.run(server.list_tools())
        assert len(tools) == 11

        for tool in tools:
            assert tool.annotations is not None, f"{tool.name} has no annotations"
            if tool.name in ("export_document", "convert_document"):
                assert tool.annotations.readOnlyHint is False
                # Honest: writes may overwrite an existing file in --output-dir.
                assert tool.annotations.destructiveHint is True
            else:
                assert tool.annotations.readOnlyHint is True, f"{tool.name} must be read-only"
                assert tool.annotations.idempotentHint is True

    def test_write_without_output_dir_raises(self, tmp_path: Path):
        from pygaeb.mcp.server import create_server

        with pytest.raises(ValueError, match="need an output directory"):
            create_server(roots=[str(tmp_path)], allow_write=True)


class TestLazyImport:
    def test_create_server_is_lazily_exported(self):
        from pygaeb import create_server as lazy
        from pygaeb.mcp.server import create_server as direct

        assert lazy is direct
