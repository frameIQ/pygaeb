"""Tests for GAEB version conversion and GAEBWriter target_version support."""

from __future__ import annotations

from decimal import Decimal

import pytest

from pygaeb.converter import ConversionReport, GAEBConverter
from pygaeb.models.boq import BoQ, BoQBody, BoQCtgy, Lot
from pygaeb.models.document import AwardInfo, GAEBDocument, GAEBInfo
from pygaeb.models.enums import ExchangePhase, SourceVersion
from pygaeb.models.item import Attachment, Item
from pygaeb.parser import GAEBParser
from pygaeb.writer import GAEBWriter
from pygaeb.writer.version_registry import VERSION_REGISTRY, WRITABLE_VERSIONS


class TestVersionRegistry:
    def test_all_da_xml_versions_present(self):
        expected = {
            SourceVersion.DA_XML_20, SourceVersion.DA_XML_21,
            SourceVersion.DA_XML_30, SourceVersion.DA_XML_31,
            SourceVersion.DA_XML_32, SourceVersion.DA_XML_33,
        }
        assert expected == set(VERSION_REGISTRY.keys())

    def test_gaeb90_not_writable(self):
        assert SourceVersion.GAEB_90 not in WRITABLE_VERSIONS

    def test_v33_is_full_featured(self):
        meta = VERSION_REGISTRY[SourceVersion.DA_XML_33]
        assert meta.supports_bim_guid is True
        assert meta.supports_attachments is True
        assert meta.supports_change_order is True
        assert meta.lang == "en"

    def test_v30_lacks_attachments_and_bim(self):
        meta = VERSION_REGISTRY[SourceVersion.DA_XML_30]
        assert meta.supports_bim_guid is False
        assert meta.supports_attachments is False
        assert meta.supports_change_order is False

    def test_v2x_uses_german(self):
        for v in (SourceVersion.DA_XML_20, SourceVersion.DA_XML_21):
            assert VERSION_REGISTRY[v].lang == "de"

    def test_namespace_differs_per_version(self):
        ns33 = VERSION_REGISTRY[SourceVersion.DA_XML_33].namespace
        ns32 = VERSION_REGISTRY[SourceVersion.DA_XML_32].namespace
        ns20 = VERSION_REGISTRY[SourceVersion.DA_XML_20].namespace
        assert ns33 != ns32
        assert ns33 != ns20


class TestGAEBWriterTargetVersion:
    def test_write_v33_default(self, sample_document, tmp_path):
        output = tmp_path / "out.X83"
        warnings = GAEBWriter.write(sample_document, output)
        content = output.read_text(encoding="utf-8")
        assert "3.3" in content
        assert "DA86/3.3" in content
        assert len(warnings) == 0

    def test_write_v32(self, sample_document, tmp_path):
        output = tmp_path / "out.X83"
        warnings = GAEBWriter.write(
            sample_document, output, target_version=SourceVersion.DA_XML_32,
        )
        content = output.read_text(encoding="utf-8")
        assert "DA86/3.2" in content
        assert "<Version>3.2</Version>" in content
        assert len(warnings) == 0

    def test_write_v31(self, sample_document, tmp_path):
        output = tmp_path / "out.X83"
        GAEBWriter.write(
            sample_document, output, target_version=SourceVersion.DA_XML_31,
        )
        content = output.read_text(encoding="utf-8")
        assert "DA86/3.1" in content
        assert "<Version>3.1</Version>" in content

    def test_write_v30(self, sample_document, tmp_path):
        output = tmp_path / "out.X83"
        GAEBWriter.write(
            sample_document, output, target_version=SourceVersion.DA_XML_30,
        )
        content = output.read_text(encoding="utf-8")
        assert "200407" in content
        assert "<Version>3.0</Version>" in content

    def test_write_v20_produces_german_tags(self, sample_document, tmp_path):
        output = tmp_path / "out.D83"
        GAEBWriter.write(
            sample_document, output, target_version=SourceVersion.DA_XML_20,
        )
        content = output.read_text(encoding="utf-8")
        assert "<Vergabe>" in content
        assert "<VergabeInfo>" in content
        assert "<Leistungsverzeichnis>" in content
        assert "<Positionsliste>" in content
        assert "<Position " in content
        assert "<Kurztext>" in content
        assert "<Menge>" in content
        assert "<Einheitspreis>" in content
        assert "<Gesamtbetrag>" in content
        assert "<Version>2.0</Version>" in content

    def test_write_v21_german(self, sample_document, tmp_path):
        output = tmp_path / "out.D83"
        GAEBWriter.write(
            sample_document, output, target_version=SourceVersion.DA_XML_21,
        )
        content = output.read_text(encoding="utf-8")
        assert "<Version>2.1</Version>" in content
        assert "<Vergabe>" in content

    def test_bim_guid_dropped_in_v32(self, tmp_path):
        item = Item(
            oz="01.0010", short_text="BIM item",
            qty=Decimal("1"), unit="Stk",
            bim_guid="abc-123-def",
        )
        doc = _make_doc([item])
        output = tmp_path / "out.X83"
        warnings = GAEBWriter.write(
            doc, output, target_version=SourceVersion.DA_XML_32,
        )
        content = output.read_text(encoding="utf-8")
        assert "abc-123-def" not in content
        assert any("bim_guid" in w and "dropped" in w for w in warnings)

    def test_attachments_dropped_in_v30(self, tmp_path):
        item = Item(
            oz="01.0010", short_text="With attachment",
            qty=Decimal("1"), unit="Stk",
            attachments=[Attachment(filename="plan.pdf", mime_type="application/pdf", data=b"pdf")],
        )
        doc = _make_doc([item])
        output = tmp_path / "out.X83"
        warnings = GAEBWriter.write(
            doc, output, target_version=SourceVersion.DA_XML_30,
        )
        content = output.read_text(encoding="utf-8")
        assert "plan.pdf" not in content
        assert any("attachment" in w.lower() and "dropped" in w.lower() for w in warnings)

    def test_change_order_dropped_in_v20(self, tmp_path):
        item = Item(
            oz="01.0010", short_text="Change order",
            qty=Decimal("1"), unit="Stk",
            change_order_number="CO-001",
        )
        doc = _make_doc([item])
        output = tmp_path / "out.D83"
        warnings = GAEBWriter.write(
            doc, output, target_version=SourceVersion.DA_XML_20,
        )
        content = output.read_text(encoding="utf-8")
        assert "CO-001" not in content
        assert any("change_order_number" in w and "dropped" in w for w in warnings)

    def test_invalid_target_version_raises(self, sample_document, tmp_path):
        output = tmp_path / "out.X83"
        with pytest.raises(ValueError, match="Cannot write"):
            GAEBWriter.write(
                sample_document, output, target_version=SourceVersion.GAEB_90,
            )

    def test_to_bytes_v33(self, sample_document):
        xml_bytes, warnings = GAEBWriter.to_bytes(sample_document)
        assert b"DA86/3.3" in xml_bytes
        assert len(warnings) == 0

    def test_to_bytes_v20_german(self, sample_document):
        xml_bytes, _warnings = GAEBWriter.to_bytes(
            sample_document, target_version=SourceVersion.DA_XML_20,
        )
        text = xml_bytes.decode("utf-8")
        assert "<Vergabe>" in text
        assert "<Version>2.0</Version>" in text


class TestGAEBConverterFile:
    def test_convert_v33_to_v33_roundtrip(self, sample_v33_file, tmp_path):
        output = tmp_path / "roundtrip.X83"
        report = GAEBConverter.convert(sample_v33_file, output)
        assert report.source_version == SourceVersion.DA_XML_33
        assert report.target_version == SourceVersion.DA_XML_33
        assert report.items_converted == 3
        assert not report.has_data_loss

        doc2 = GAEBParser.parse(output)
        assert doc2.award.project_no == "PRJ-001"
        assert doc2.item_count == 3

    def test_convert_v20_to_v33(self, sample_v20_file, tmp_path):
        output = tmp_path / "upgraded.X83"
        report = GAEBConverter.convert(
            sample_v20_file, output, target_version=SourceVersion.DA_XML_33,
        )
        assert report.source_version == SourceVersion.DA_XML_20
        assert report.target_version == SourceVersion.DA_XML_33
        assert report.is_upgrade
        assert not report.is_downgrade
        assert report.items_converted == 1
        assert not report.has_data_loss

        doc2 = GAEBParser.parse(output)
        assert doc2.source_version == SourceVersion.DA_XML_33
        assert doc2.item_count == 1

    def test_convert_v33_to_v32_downgrade(self, sample_v33_file, tmp_path):
        output = tmp_path / "downgraded.X83"
        report = GAEBConverter.convert(
            sample_v33_file, output, target_version=SourceVersion.DA_XML_32,
        )
        assert report.is_downgrade
        assert report.is_same_family

        doc2 = GAEBParser.parse(output)
        assert doc2.item_count == 3

    def test_convert_v33_to_v20_cross_family(self, sample_v33_file, tmp_path):
        output = tmp_path / "legacy.D83"
        report = GAEBConverter.convert(
            sample_v33_file, output, target_version=SourceVersion.DA_XML_20,
        )
        assert report.is_downgrade
        assert not report.is_same_family

        content = output.read_text(encoding="utf-8")
        assert "<Vergabe>" in content
        assert "<Version>2.0</Version>" in content

    def test_convert_with_phase_override(self, sample_v33_file, tmp_path):
        output = tmp_path / "bid.X84"
        report = GAEBConverter.convert(
            sample_v33_file, output, target_phase=ExchangePhase.X84,
        )
        assert report.target_phase == ExchangePhase.X84
        assert output.exists()

    def test_convert_from_bytes(self, tmp_path):
        from tests.conftest import SAMPLE_V33_XML
        raw = SAMPLE_V33_XML.encode("utf-8")
        output = tmp_path / "from_bytes.X83"
        report = GAEBConverter.convert(raw, output)
        assert report.items_converted == 3
        assert output.exists()

    def test_convert_invalid_target_raises(self, sample_v33_file, tmp_path):
        with pytest.raises(ValueError, match="Cannot convert"):
            GAEBConverter.convert(
                sample_v33_file, tmp_path / "out.X83",
                target_version=SourceVersion.GAEB_90,
            )


class TestGAEBConverterBytes:
    def test_convert_bytes_v33(self, sample_v33_file):
        xml_bytes, report = GAEBConverter.convert_bytes(sample_v33_file)
        assert b"DA86/3.3" in xml_bytes
        assert report.items_converted == 3

    def test_convert_bytes_v20(self, sample_v33_file):
        xml_bytes, report = GAEBConverter.convert_bytes(
            sample_v33_file, target_version=SourceVersion.DA_XML_20,
        )
        text = xml_bytes.decode("utf-8")
        assert "<Vergabe>" in text
        assert report.target_version == SourceVersion.DA_XML_20

    def test_convert_bytes_from_raw(self):
        from tests.conftest import SAMPLE_V33_XML
        xml_bytes, report = GAEBConverter.convert_bytes(
            SAMPLE_V33_XML.encode("utf-8"),
            target_version=SourceVersion.DA_XML_32,
        )
        assert b"DA86/3.2" in xml_bytes
        assert report.items_converted == 3


class TestConversionReport:
    def test_upgrade_detection(self):
        report = ConversionReport(
            source_version=SourceVersion.DA_XML_20,
            target_version=SourceVersion.DA_XML_33,
            source_phase=ExchangePhase.D83,
            target_phase=ExchangePhase.X83,
            items_converted=5,
        )
        assert report.is_upgrade
        assert not report.is_downgrade

    def test_downgrade_detection(self):
        report = ConversionReport(
            source_version=SourceVersion.DA_XML_33,
            target_version=SourceVersion.DA_XML_20,
            source_phase=ExchangePhase.X83,
            target_phase=ExchangePhase.D83,
            items_converted=5,
        )
        assert report.is_downgrade
        assert not report.is_upgrade

    def test_same_family(self):
        report = ConversionReport(
            source_version=SourceVersion.DA_XML_33,
            target_version=SourceVersion.DA_XML_31,
            source_phase=ExchangePhase.X83,
            target_phase=ExchangePhase.X83,
        )
        assert report.is_same_family

    def test_cross_family(self):
        report = ConversionReport(
            source_version=SourceVersion.DA_XML_33,
            target_version=SourceVersion.DA_XML_20,
            source_phase=ExchangePhase.X83,
            target_phase=ExchangePhase.D83,
        )
        assert not report.is_same_family

    def test_has_data_loss(self):
        report = ConversionReport(
            source_version=SourceVersion.DA_XML_33,
            target_version=SourceVersion.DA_XML_30,
            source_phase=ExchangePhase.X83,
            target_phase=ExchangePhase.X83,
            fields_dropped=["bim_guid dropped"],
        )
        assert report.has_data_loss

    def test_no_data_loss(self):
        report = ConversionReport(
            source_version=SourceVersion.DA_XML_20,
            target_version=SourceVersion.DA_XML_33,
            source_phase=ExchangePhase.D83,
            target_phase=ExchangePhase.X83,
        )
        assert not report.has_data_loss


class TestRoundTrips:
    """Parse → write → re-parse and verify data integrity across versions."""

    def test_v33_write_v32_reparse(self, sample_v33_file, tmp_path):
        doc = GAEBParser.parse(sample_v33_file)
        output = tmp_path / "v32.X83"
        GAEBWriter.write(doc, output, target_version=SourceVersion.DA_XML_32)
        doc2 = GAEBParser.parse(output)
        assert doc2.award.project_no == doc.award.project_no
        assert doc2.item_count == doc.item_count
        items1 = list(doc.award.boq.iter_items())
        items2 = list(doc2.award.boq.iter_items())
        for i1, i2 in zip(items1, items2):
            assert i1.short_text == i2.short_text
            assert i1.qty == i2.qty

    def test_v20_write_v33_reparse(self, sample_v20_file, tmp_path):
        doc = GAEBParser.parse(sample_v20_file)
        output = tmp_path / "v33.X83"
        GAEBWriter.write(doc, output, target_version=SourceVersion.DA_XML_33)
        doc2 = GAEBParser.parse(output)
        assert doc2.source_version == SourceVersion.DA_XML_33
        assert doc2.item_count == doc.item_count
        items1 = list(doc.award.boq.iter_items())
        items2 = list(doc2.award.boq.iter_items())
        assert items1[0].short_text == items2[0].short_text

    def test_v33_write_v20_reparse(self, sample_v33_file, tmp_path):
        doc = GAEBParser.parse(sample_v33_file)
        output = tmp_path / "legacy.D83"
        GAEBWriter.write(doc, output, target_version=SourceVersion.DA_XML_20)
        doc2 = GAEBParser.parse(output)
        assert doc2.item_count == doc.item_count


def _make_doc(items: list[Item]) -> GAEBDocument:
    """Helper to build a minimal GAEBDocument with the given items."""
    ctgy = BoQCtgy(rno="01", label="Test", items=items)
    lot = Lot(rno="1", label="Default", body=BoQBody(categories=[ctgy]))
    return GAEBDocument(
        source_version=SourceVersion.DA_XML_33,
        exchange_phase=ExchangePhase.X83,
        gaeb_info=GAEBInfo(version="3.3"),
        award=AwardInfo(currency="EUR", boq=BoQ(lots=[lot])),
    )
