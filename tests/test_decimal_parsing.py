"""Numbers in GAEB files are plain decimals; anything else reads as empty and is reported.

Python's ``Decimal()`` accepts NaN, Infinity, exponents, Unicode digits and
underscores. Each caused trouble: NaN and Infinity crashed parsing and exports,
and an exponent such as ``1E+999999`` held validation for minutes or blew exports
up to gigabytes. GAEB numbers are xs:decimal, so the parsers now read only that.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, localcontext

import pytest

from pygaeb import (
    BoQBuilder,
    GAEBParser,
    GAEBValidationError,
    GAEBWriter,
    Item,
    ValidationMode,
    to_json_string,
)
from pygaeb.models.boq import Totals
from pygaeb.models.enums import ValidationSeverity
from pygaeb.parser._decimal import collecting_rejects, parse_decimal
from pygaeb.parser.gaeb_parser import _version_tuple
from pygaeb.parser.reb_parser import parse_reb_row
from pygaeb.validation.numeric_validator import _pre_decimal_digits
from pygaeb.writer.gaeb_writer import _discounted_total
from tests.conftest import SAMPLE_V33_XML


def _with(xml: str, *swaps: tuple[str, str]) -> str:
    for old, new in swaps:
        assert old in xml
        xml = xml.replace(old, new)
    return xml


# Three positions, three bad numbers: 01.01.0010 NaN Qty, 01.01.0020 exponent UP,
# 02.0010 infinite IT.
BAD = _with(
    SAMPLE_V33_XML,
    ("<Qty>1170.000</Qty>", "<Qty>NaN</Qty>"),
    ("<UP>68.00</UP>", "<UP>1E+999999</UP>"),
    ("<IT>11250.00</IT>", "<IT>Infinity</IT>"),
)

# A bid answering a field with a ComplBodyInt whose Value is no number.
FIELD = """\
<?xml version="1.0" encoding="UTF-8"?>
<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA84/3.3">
<GAEBInfo><Version>3.3</Version><ProgSystem>TestSuite</ProgSystem></GAEBInfo>
<Award><BoQ>
<BoQInfo><Name>LV</Name>
  <BoQBkdn><BoQLevel Length="2"/><Item Length="4"/></BoQBkdn></BoQInfo>
<BoQBody><BoQCtgy RNoPart="01"><BoQBody><Itemlist>
<Item RNoPart="0010"><Qty>1</Qty><Description><CompleteText><DetailTxt>\
<Text><span>Dicke </span></Text>\
<TextComplement Kind="Bidder" MarkLbl="1"><ComplCaption><span>Dicke</span></ComplCaption>\
<ComplBody><ComplBodyInt Value="NaN"/></ComplBody></TextComplement>\
</DetailTxt></CompleteText></Description></Item>
</Itemlist></BoQBody></BoQCtgy></BoQBody>
</BoQ></Award>
</GAEB>
"""


class TestTheReader:
    @pytest.mark.parametrize(("text", "expected"), [
        ("12", "12"), ("12.50", "12.50"), ("12,5", "12.5"), (".5", "0.5"), ("5.", "5"),
        ("-3.25", "-3.25"), ("+4", "4"), (" 7 \n", "7"), ("000123", "123"),
    ])
    def test_plain_decimals_are_read_with_their_scale(self, text: str, expected: str) -> None:
        value = parse_decimal(text)
        assert value is not None
        assert str(value) == expected

    @pytest.mark.parametrize("text", [
        "NaN", "nan", "sNaN", "Infinity", "-inf", "1E5", "1e-3", "1E+999999", "1_000",
        "١٢", "1.000,50", "1 000", ".", "-", "abc", "12.5.3", "0x10",
    ])
    def test_anything_else_reads_as_empty_and_is_counted(self, text: str) -> None:
        with collecting_rejects() as rejected:
            assert parse_decimal(text) is None
        assert rejected.count == 1

    def test_the_size_limits(self) -> None:
        assert parse_decimal("9" * 15) == Decimal("9" * 15)
        assert parse_decimal("0" * 20 + "1") == 1  # leading zeros are no digits
        assert parse_decimal("0." + "1" * 10) is not None
        with collecting_rejects() as rejected:
            assert parse_decimal("9" * 16) is None
            assert parse_decimal("0." + "1" * 11) is None
        assert rejected.count == 2

    def test_empty_values_and_free_text_are_not_reported(self) -> None:
        with collecting_rejects() as rejected:
            assert parse_decimal(None) is None
            assert parse_decimal("  ") is None
            assert parse_decimal("ca. 5", report=False) is None
        assert rejected.count == 0


class TestParsingAFile:
    def test_a_file_with_bad_numbers_parses_and_says_so(self) -> None:
        doc = GAEBParser.parse_string(BAD, filename="bad.X86")
        items = {i.full_oz: i for i in doc.iter_items() if isinstance(i, Item)}
        assert items["01.01.0010"].qty is None
        assert items["01.01.0020"].unit_price is None
        assert items["02.0010"].total_price is None
        errors = [r.message for r in doc.validation_results
                  if r.severity is ValidationSeverity.ERROR]
        assert len(errors) == 1
        assert errors[0].startswith("3 value(s) are not plain decimal numbers")
        assert "'NaN'" in errors[0] and "'1E+999999'" in errors[0]
        # What used to crash, hang or explode now just works.
        assert doc.grand_total == Decimal("111069.00")
        assert doc.computed_grand_total is not None
        assert to_json_string(doc)

    def test_strict_mode_refuses_a_file_with_bad_numbers(self) -> None:
        with pytest.raises(GAEBValidationError, match="not plain decimal"):
            GAEBParser.parse_string(BAD, filename="bad.X86", validation=ValidationMode.STRICT)

    def test_a_fill_in_value_that_is_no_number_does_not_abort_the_parse(self) -> None:
        # It used to raise a pydantic ValidationError out of the parse.
        doc = GAEBParser.parse_string(FIELD, filename="bid.X84")
        item = next(i for i in doc.iter_items() if isinstance(i, Item))
        assert item.long_text is not None
        assert [c.number for c in item.long_text.complements] == [None]
        assert any("not plain decimal" in r.message for r in doc.validation_results)


class TestAmounts:
    def test_the_amount_does_not_depend_on_the_callers_decimal_context(self) -> None:
        item = Item(oz="0010", qty=Decimal("1.234549999"), unit_price=Decimal("100"))
        with localcontext() as ctx:
            ctx.prec = 6  # used to round the product first: 123.455, then 123.46
            assert item.computed_total == Decimal("123.45")

    def test_the_largest_accepted_values_multiply_without_error(self) -> None:
        big = Decimal("9" * 15 + ".999")
        item = Item(oz="0010", qty=big, unit_price=big)
        with localcontext() as ctx:
            ctx.prec, ctx.rounding = 100, ROUND_HALF_UP
            expected = (big * big).quantize(Decimal("0.01"))
        assert item.computed_total == expected

    def test_a_non_finite_operand_gives_no_amount_instead_of_a_crash(self) -> None:
        item = Item(oz="0010", qty=Decimal("2"), unit_price=Decimal("3"))
        item.unit_price = Decimal("NaN")  # assignment is not validated
        assert item.computed_total is None

    def test_the_builder_total_does_not_depend_on_the_callers_decimal_context(self) -> None:
        builder = BoQBuilder(phase="X84")
        category = builder.add_category("01", "Rohbau")
        with localcontext() as ctx:
            ctx.prec = 6  # used to give 123.46
            category.add_item("01.0010", "Wand", qty=Decimal("1.234549999"), unit="m2",
                              unit_price=100)
        item = next(i for i in builder.build().iter_items() if isinstance(i, Item))
        assert item.total_price == Decimal("123.45")

    def test_the_builder_refuses_an_infinite_quantity(self) -> None:
        category = BoQBuilder(phase="X84").add_category("01", "Rohbau")
        with pytest.raises(ValueError, match="finite"):  # was decimal.InvalidOperation
            category.add_item("01.0010", "Wand", qty=float("inf"), unit="m2", unit_price=1)

    def test_the_written_discounted_total_does_not_depend_on_the_callers_context(self) -> None:
        totals = Totals(total=Decimal("123456.78"), discount_pcnt=Decimal("3"))
        with localcontext() as ctx:
            ctx.prec = 6  # used to raise InvalidOperation
            assert _discounted_total(totals) == Decimal("119753.08")


class TestOtherNumbersInTheFile:
    @pytest.mark.parametrize(("value", "expected"), [
        ("2", 2), ("3", 3), ("-5", None), ("7", None), ("1_0", None),
    ])
    def test_unit_price_places_are_two_or_three(self, value: str, expected: int | None) -> None:
        # The writer rounds every unit price to these places; -5 rounded to 100,000s.
        xml = _with(SAMPLE_V33_XML, ("</GAEBInfo>", (
            f"</GAEBInfo><PrjInfo><NamePrj>P</NamePrj><UPFracDig>{value}</UPFracDig></PrjInfo>"
        )))
        doc = GAEBParser.parse_string(xml, filename="award.X86")
        assert doc.award is not None
        assert doc.award.up_frac_dig == expected
        warned = [r for r in doc.validation_results if "UPFracDig" in r.message]
        assert len(warned) == (0 if expected else 1)
        written, _ = GAEBWriter.to_bytes(doc)
        assert b"<UP>45.50" in written

    @pytest.mark.parametrize("text", ["3.²", "1." + "9" * 5000, "٣.٣"])
    def test_a_writer_version_with_odd_digits_does_not_crash(self, text: str) -> None:
        _version_tuple(text)  # "²" and 5,000 digits raised ValueError


@pytest.mark.parametrize(("value", "digits"), [
    ("0", 1), ("0.5", 1), ("9.99", 1), ("123.45", 3), ("-123", 3), ("1E+20", 21),
    ("1E+999999", 1_000_000),  # counting by division took minutes
])
def test_integer_digits_are_counted_in_constant_time(value: str, digits: int) -> None:
    assert _pre_decimal_digits(Decimal(value)) == digits


def test_a_non_finite_value_has_no_integer_digits() -> None:
    assert _pre_decimal_digits(Decimal("NaN")) == 0


@pytest.mark.parametrize("row", ["2 * sNaN", "2 * 1E999999999", "Wand 5,00 * 3,00 = NaN m2"])
def test_takeoff_rows_with_odd_numbers_do_not_crash(row: str) -> None:
    parse_reb_row(row)  # used to raise InvalidOperation or decimal.Overflow
