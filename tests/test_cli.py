"""Tests for the pygaeb CLI tool.

Covers all 6 commands: info, validate, convert, diff, export.
Uses Click's CliRunner for isolated testing without real subprocess calls.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from click.testing import CliRunner

from pygaeb.cli import main

# ── Fixtures ─────────────────────────────────────────────────────────

_SAMPLE_X86 = dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA86/3.3">
      <GAEBInfo><Version>3.3</Version></GAEBInfo>
      <Award>
        <AwardInfo>
          <Prj>PRJ-CLI</Prj>
          <PrjName>CLI Testprojekt</PrjName>
          <Cur>EUR</Cur>
        </AwardInfo>
        <BoQ><BoQBody>
          <BoQCtgy RNoPart="01"><LblTx>Rohbau</LblTx>
            <Itemlist>
              <Item RNoPart="0010">
                <ShortText>Mauerwerk KS 240mm</ShortText>
                <Qty>100</Qty><QU>m2</QU>
                <UP>45.50</UP><IT>4550.00</IT>
              </Item>
              <Item RNoPart="0020">
                <ShortText>Beton C25/30</ShortText>
                <Qty>50</Qty><QU>m3</QU>
                <UP>180.00</UP><IT>9000.00</IT>
              </Item>
            </Itemlist>
          </BoQCtgy>
        </BoQBody></BoQ>
      </Award>
    </GAEB>
""")

_SAMPLE_X82 = dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA82/3.3">
      <GAEBInfo><Version>3.3</Version></GAEBInfo>
      <Award>
        <AwardInfo><Prj>PRJ-X82</Prj><Cur>EUR</Cur></AwardInfo>
        <BoQ><BoQBody>
          <BoQCtgy RNoPart="01"><LblTx>Kostenermittlung</LblTx>
            <Itemlist>
              <Item RNoPart="0010">
                <ShortText>Erdarbeiten Aushub</ShortText>
                <Qty>500</Qty><QU>m3</QU>
                <UP>12.00</UP><IT>6000.00</IT>
                <CostApproach>
                  <CostType>Material</CostType>
                  <Amount>5.00</Amount>
                  <Remark>Bodenabtrag</Remark>
                </CostApproach>
                <CostApproach>
                  <CostType>Labor</CostType>
                  <Amount>7.00</Amount>
                </CostApproach>
              </Item>
            </Itemlist>
          </BoQCtgy>
        </BoQBody></BoQ>
      </Award>
    </GAEB>
""")


def _write_fixture(tmp_path: Path, name: str, content: str) -> Path:
    f = tmp_path / name
    f.write_text(content, encoding="utf-8")
    return f


# ═══════════════════════════════════════════════════════════════════════
# CLI: info command
# ═══════════════════════════════════════════════════════════════════════


class TestCLIInfo:
    def test_info_shows_version_and_phase(self, tmp_path: Path) -> None:
        f = _write_fixture(tmp_path, "test.X86", _SAMPLE_X86)
        runner = CliRunner()
        result = runner.invoke(main, ["info", str(f)])
        assert result.exit_code == 0
        assert "DA XML 3.3" in result.output
        assert "X86" in result.output

    def test_info_shows_item_count(self, tmp_path: Path) -> None:
        f = _write_fixture(tmp_path, "test.X86", _SAMPLE_X86)
        result = CliRunner().invoke(main, ["info", str(f)])
        assert "Items:     2" in result.output

    def test_info_shows_total(self, tmp_path: Path) -> None:
        f = _write_fixture(tmp_path, "test.X86", _SAMPLE_X86)
        result = CliRunner().invoke(main, ["info", str(f)])
        assert "13,550.00" in result.output

    def test_info_shows_project(self, tmp_path: Path) -> None:
        f = _write_fixture(tmp_path, "test.X86", _SAMPLE_X86)
        result = CliRunner().invoke(main, ["info", str(f)])
        assert "PRJ-CLI" in result.output
        assert "CLI Testprojekt" in result.output

    def test_info_missing_file(self) -> None:
        result = CliRunner().invoke(main, ["info", "/nonexistent.X83"])
        assert result.exit_code != 0


# ═══════════════════════════════════════════════════════════════════════
# CLI: validate command
# ═══════════════════════════════════════════════════════════════════════


class TestCLIValidate:
    def test_validate_clean_file(self, tmp_path: Path) -> None:
        f = _write_fixture(tmp_path, "test.X86", _SAMPLE_X86)
        result = CliRunner().invoke(main, ["validate", str(f)])
        # May have INFO about XSD skipped, but no errors
        assert result.exit_code == 0

    def test_validate_strict_flag(self, tmp_path: Path) -> None:
        f = _write_fixture(tmp_path, "test.X86", _SAMPLE_X86)
        result = CliRunner().invoke(main, ["validate", str(f), "--strict"])
        assert result.exit_code == 0


# ═══════════════════════════════════════════════════════════════════════
# CLI: convert command
# ═══════════════════════════════════════════════════════════════════════


class TestCLIConvert:
    def test_convert_version(self, tmp_path: Path) -> None:
        f = _write_fixture(tmp_path, "input.X86", _SAMPLE_X86)
        out = tmp_path / "output.X86"
        result = CliRunner().invoke(
            main, ["convert", str(f), str(out), "--version", "3.2"],
        )
        assert result.exit_code == 0
        assert "Converted" in result.output
        assert out.exists()

    def test_convert_with_phase(self, tmp_path: Path) -> None:
        f = _write_fixture(tmp_path, "input.X86", _SAMPLE_X86)
        out = tmp_path / "output.X84"
        result = CliRunner().invoke(
            main, ["convert", str(f), str(out), "--phase", "X84"],
        )
        assert result.exit_code == 0

    def test_convert_invalid_phase(self, tmp_path: Path) -> None:
        f = _write_fixture(tmp_path, "input.X86", _SAMPLE_X86)
        out = tmp_path / "output.X84"
        result = CliRunner().invoke(
            main, ["convert", str(f), str(out), "--phase", "INVALID"],
        )
        assert result.exit_code != 0


# ═══════════════════════════════════════════════════════════════════════
# CLI: diff command
# ═══════════════════════════════════════════════════════════════════════


class TestCLIDiff:
    def test_diff_identical_files(self, tmp_path: Path) -> None:
        f1 = _write_fixture(tmp_path, "a.X86", _SAMPLE_X86)
        f2 = _write_fixture(tmp_path, "b.X86", _SAMPLE_X86)
        result = CliRunner().invoke(main, ["diff", str(f1), str(f2)])
        assert result.exit_code == 0
        assert "Changes: 0" in result.output

    def test_diff_json_output(self, tmp_path: Path) -> None:
        f1 = _write_fixture(tmp_path, "a.X86", _SAMPLE_X86)
        f2 = _write_fixture(tmp_path, "b.X86", _SAMPLE_X86)
        result = CliRunner().invoke(
            main, ["diff", str(f1), str(f2), "--format", "json"],
        )
        assert result.exit_code == 0
        assert '"summary"' in result.output


# ═══════════════════════════════════════════════════════════════════════
# CLI: export command
# ═══════════════════════════════════════════════════════════════════════


class TestCLIExport:
    def test_export_json(self, tmp_path: Path) -> None:
        f = _write_fixture(tmp_path, "test.X86", _SAMPLE_X86)
        out = tmp_path / "export.json"
        result = CliRunner().invoke(
            main, ["export", str(f), "-f", "json", "-o", str(out)],
        )
        assert result.exit_code == 0
        assert out.exists()
        assert "Exported" in result.output

    def test_export_csv(self, tmp_path: Path) -> None:
        f = _write_fixture(tmp_path, "test.X86", _SAMPLE_X86)
        out = tmp_path / "export.csv"
        result = CliRunner().invoke(
            main, ["export", str(f), "-f", "csv", "-o", str(out)],
        )
        assert result.exit_code == 0
        assert out.exists()

    def test_export_xlsx(self, tmp_path: Path) -> None:
        f = _write_fixture(tmp_path, "test.X86", _SAMPLE_X86)
        out = tmp_path / "export.xlsx"
        result = CliRunner().invoke(
            main, ["export", str(f), "-f", "xlsx", "-o", str(out)],
        )
        assert result.exit_code == 0
        assert out.exists()

    def test_export_default_output_name(self, tmp_path: Path) -> None:
        f = _write_fixture(tmp_path, "tender.X86", _SAMPLE_X86)
        result = CliRunner().invoke(
            main, ["export", str(f), "-f", "json"],
        )
        assert result.exit_code == 0
        assert "tender.json" in result.output


# ═══════════════════════════════════════════════════════════════════════
# CLI: version flag
# ═══════════════════════════════════════════════════════════════════════


class TestCLIVersion:
    def test_version_flag(self) -> None:
        result = CliRunner().invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "pygaeb" in result.output

    def test_help_flag(self) -> None:
        result = CliRunner().invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Parse, validate, convert" in result.output


# ═══════════════════════════════════════════════════════════════════════
# X82: Preisspiegel / Cost Estimate
# ═══════════════════════════════════════════════════════════════════════


class TestX82CostEstimate:
    def test_x82_parses_cost_approaches(self, tmp_path: Path) -> None:
        from pygaeb import GAEBParser

        f = _write_fixture(tmp_path, "cost.X82", _SAMPLE_X82)
        doc = GAEBParser.parse(str(f))
        items = list(doc.iter_items())
        assert len(items) == 1
        assert len(items[0].cost_approaches) == 2
        assert items[0].cost_approaches[0].cost_type == "Material"
        assert items[0].cost_approaches[1].cost_type == "Labor"

    def test_x82_phase_detected(self, tmp_path: Path) -> None:
        from pygaeb import ExchangePhase, GAEBParser

        f = _write_fixture(tmp_path, "cost.X82", _SAMPLE_X82)
        doc = GAEBParser.parse(str(f))
        assert doc.exchange_phase == ExchangePhase.X82

    def test_x82_round_trip(self, tmp_path: Path) -> None:
        from pygaeb import GAEBParser, GAEBWriter

        f = _write_fixture(tmp_path, "cost.X82", _SAMPLE_X82)
        doc1 = GAEBParser.parse(str(f))
        out = tmp_path / "cost_out.X82"
        GAEBWriter.write(doc1, out)
        doc2 = GAEBParser.parse(str(out))
        items1 = list(doc1.iter_items())
        items2 = list(doc2.iter_items())
        assert len(items1) == len(items2)
        assert len(items2[0].cost_approaches) == 2

    def test_x82_validation_warns_missing_price(self, tmp_path: Path) -> None:
        """X82 should warn when items lack unit price."""
        from pygaeb import GAEBParser

        xml = dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA82/3.3">
              <GAEBInfo><Version>3.3</Version></GAEBInfo>
              <Award>
                <AwardInfo><Prj>P1</Prj><Cur>EUR</Cur></AwardInfo>
                <BoQ><BoQBody>
                  <BoQCtgy RNoPart="01"><LblTx>Test</LblTx>
                    <Itemlist>
                      <Item RNoPart="0010">
                        <ShortText>Item without price</ShortText>
                        <Qty>100</Qty><QU>m2</QU>
                      </Item>
                    </Itemlist>
                  </BoQCtgy>
                </BoQBody></BoQ>
              </Award>
            </GAEB>
        """)
        f = _write_fixture(tmp_path, "no_price.X82", xml)
        doc = GAEBParser.parse(str(f))
        price_warnings = [
            r for r in doc.validation_results
            if "Unit price expected" in r.message and "X82" in r.message
        ]
        assert len(price_warnings) >= 1

    def test_x82_cli_info(self, tmp_path: Path) -> None:
        """CLI info command works with X82 files."""
        f = _write_fixture(tmp_path, "cost.X82", _SAMPLE_X82)
        result = CliRunner().invoke(main, ["info", str(f)])
        assert result.exit_code == 0
        assert "X82" in result.output
