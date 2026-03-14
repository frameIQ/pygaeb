"""Tests for the GAEB XML writer and round-trip."""



from pygaeb.models.enums import ExchangePhase
from pygaeb.parser import GAEBParser
from pygaeb.writer import GAEBWriter


class TestGAEBWriter:
    def test_write_creates_file(self, sample_document, tmp_path):
        output = tmp_path / "output.X83"
        GAEBWriter.write(sample_document, output)
        assert output.exists()
        content = output.read_text(encoding="utf-8")
        assert "<?xml" in content
        assert "GAEB" in content

    def test_write_preserves_award_info(self, sample_document, tmp_path):
        output = tmp_path / "output.X83"
        GAEBWriter.write(sample_document, output)
        content = output.read_text(encoding="utf-8")
        assert "PRJ-001" in content
        assert "Test Project" in content
        assert "EUR" in content

    def test_write_preserves_items(self, sample_document, tmp_path):
        output = tmp_path / "output.X83"
        GAEBWriter.write(sample_document, output)
        content = output.read_text(encoding="utf-8")
        assert "Mauerwerk Innenwand" in content
        assert "45.50" in content

    def test_round_trip_v33(self, sample_v33_file, tmp_path):
        doc = GAEBParser.parse(sample_v33_file)
        output = tmp_path / "roundtrip.X83"
        GAEBWriter.write(doc, output)

        doc2 = GAEBParser.parse(output)
        assert doc2.award.project_no == doc.award.project_no
        assert doc2.award.currency == doc.award.currency

        items1 = list(doc.award.boq.iter_items())
        items2 = list(doc2.award.boq.iter_items())
        assert len(items1) == len(items2)

    def test_write_with_phase_override(self, sample_document, tmp_path):
        output = tmp_path / "bid.X84"
        GAEBWriter.write(sample_document, output, phase=ExchangePhase.X84)
        assert output.exists()


class TestExport:
    def test_csv_export(self, sample_document, tmp_path):
        from pygaeb.convert import to_csv

        output = tmp_path / "items.csv"
        to_csv(sample_document, output)
        assert output.exists()
        content = output.read_text(encoding="utf-8")
        assert "oz" in content
        assert "short_text" in content
        assert "Mauerwerk" in content

    def test_json_export(self, sample_document, tmp_path):
        import json

        from pygaeb.convert import to_json

        output = tmp_path / "boq.json"
        to_json(sample_document, output)
        assert output.exists()
        data = json.loads(output.read_text(encoding="utf-8"))
        assert "source_version" in data
        assert "award" in data
