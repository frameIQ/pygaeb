"""Tests for extensibility and custom configuration (v1.7.0).

Covers:
- register_validator / clear_validators — global and per-call
- post_parse_hook — receives item + element, can populate raw_data
- post_parse_hook auto-enables / discards XML when keep_xml=False
- custom taxonomy= and prompt_template= on LLMClassifier
- register_prompt() — custom prompt version is retrievable
- collect_raw_data=True — unknown XML elements appear in item.raw_data
- log_level application via configure()
- reset_settings export accessibility
"""

from __future__ import annotations

import logging
from textwrap import dedent

import pytest

from pygaeb import GAEBParser
from pygaeb.classifier.batch_classifier import LLMClassifier
from pygaeb.classifier.prompt_templates import (
    _custom_prompts,
    get_prompt,
    register_prompt,
)
from pygaeb.config import configure, get_settings, reset_settings
from pygaeb.models.enums import ValidationSeverity
from pygaeb.models.item import ValidationResult
from pygaeb.validation import clear_validators, register_validator

# ── XML Fixture ──────────────────────────────────────────────────────

GAEB_WITH_VENDOR_EL = dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA86/3.3">
      <GAEBInfo>
        <Version>3.3</Version>
        <ProgSystem>TestSuite</ProgSystem>
      </GAEBInfo>
      <Award>
        <BoQ>
          <BoQBody>
            <BoQCtgy RNoPart="01" LblTx="Section 1">
              <BoQBody>
                <Itemlist>
                  <Item RNoPart="001">
                    <Qty>10.000</Qty>
                    <QU>m2</QU>
                    <UP>45.50</UP>
                    <Description>
                      <CompleteText>
                        <OutlineText><OutlTxt><TextOutlTxt><p>Test item</p>\
</TextOutlTxt></OutlTxt></OutlineText>
                      </CompleteText>
                    </Description>
                    <VendorCostCode>VC-001</VendorCostCode>
                    <CustomNote>Important</CustomNote>
                  </Item>
                </Itemlist>
              </BoQBody>
            </BoQCtgy>
          </BoQBody>
        </BoQ>
      </Award>
    </GAEB>""")

GAEB_NO_UNIT = dedent("""\
    <?xml version="1.0" encoding="utf-8"?>
    <GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA86/3.3">
      <GAEBInfo>
        <Version>3.3</Version>
        <ProgSystem>TestSuite</ProgSystem>
      </GAEBInfo>
      <Award>
        <BoQ>
          <BoQBody>
            <BoQCtgy RNoPart="01" LblTx="Section 1">
              <BoQBody>
                <Itemlist>
                  <Item RNoPart="001">
                    <Qty>5.000</Qty>
                    <UP>10.00</UP>
                    <Description>
                      <CompleteText>
                        <OutlineText><OutlTxt><TextOutlTxt><p>No unit item</p>\
</TextOutlTxt></OutlTxt></OutlineText>
                      </CompleteText>
                    </Description>
                  </Item>
                </Itemlist>
              </BoQBody>
            </BoQCtgy>
          </BoQBody>
        </BoQ>
      </Award>
    </GAEB>""")


# ── Helpers ───────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_state():
    """Ensure validators and settings are reset between tests."""
    clear_validators()
    reset_settings()
    _custom_prompts.clear()
    yield
    clear_validators()
    reset_settings()
    _custom_prompts.clear()


# ── 1. Custom Validator Registry ─────────────────────────────────────

class TestValidatorRegistry:
    def test_register_and_run(self):
        def require_unit(doc):
            issues = []
            for item in doc.iter_items():
                if not item.unit:
                    issues.append(
                        ValidationResult(
                            severity=ValidationSeverity.WARNING,
                            message=f"{item.oz}: missing unit",
                        )
                    )
            return issues

        register_validator(require_unit)
        doc = GAEBParser.parse_string(GAEB_NO_UNIT, filename="test.X83")

        msgs = [r.message for r in doc.validation_results]
        assert any("missing unit" in m for m in msgs)

    def test_clear_validators(self):
        def always_fail(doc):
            return [ValidationResult(severity=ValidationSeverity.ERROR, message="boom")]

        register_validator(always_fail)
        clear_validators()

        doc = GAEBParser.parse_string(GAEB_WITH_VENDOR_EL, filename="test.X83")
        assert all("boom" not in r.message for r in doc.validation_results)

    def test_extra_validators_per_call(self):
        def check_qty(doc):
            issues = []
            for item in doc.iter_items():
                if item.qty is None:
                    issues.append(
                        ValidationResult(
                            severity=ValidationSeverity.WARNING,
                            message=f"{item.oz}: no qty",
                        )
                    )
            return issues

        GAEBParser.parse_string(
            GAEB_WITH_VENDOR_EL, filename="test.X83", extra_validators=[check_qty],
        )
        from pygaeb.validation import _custom_validators
        assert check_qty not in _custom_validators

    def test_extra_validators_results_appear(self):
        def always_warn(doc):
            return [
                ValidationResult(
                    severity=ValidationSeverity.WARNING,
                    message="extra-validator-ran",
                )
            ]

        doc = GAEBParser.parse_string(
            GAEB_WITH_VENDOR_EL, filename="test.X83", extra_validators=[always_warn],
        )
        assert any("extra-validator-ran" in r.message for r in doc.validation_results)


# ── 2. Post-Parse Hook ───────────────────────────────────────────────

class TestPostParseHook:
    def test_hook_receives_item_and_element(self):
        received = []

        def hook(item, el):
            received.append((item.oz, el is not None))

        GAEBParser.parse_string(
            GAEB_WITH_VENDOR_EL, filename="test.X83", post_parse_hook=hook,
        )
        assert len(received) >= 1
        assert received[0] == ("001", True)

    def test_hook_can_populate_raw_data(self):
        def hook(item, el):
            if el is None:
                return
            for child in el:
                tag = child.tag
                if "}" in tag:
                    tag = tag.split("}", 1)[1]
                if tag == "VendorCostCode":
                    item.raw_data = item.raw_data or {}
                    item.raw_data["vendor_code"] = child.text

        doc = GAEBParser.parse_string(
            GAEB_WITH_VENDOR_EL, filename="test.X83", post_parse_hook=hook,
        )
        items = list(doc.iter_items())
        assert items[0].raw_data is not None
        assert items[0].raw_data["vendor_code"] == "VC-001"

    def test_hook_auto_discards_xml_when_keep_xml_false(self):
        def noop_hook(item, el):
            pass

        doc = GAEBParser.parse_string(
            GAEB_WITH_VENDOR_EL, filename="test.X83",
            keep_xml=False, post_parse_hook=noop_hook,
        )
        # XML should have been discarded after hook ran
        assert doc.xml_root is None
        for item in doc.iter_items():
            assert item.source_element is None

    def test_hook_keeps_xml_when_keep_xml_true(self):
        def noop_hook(item, el):
            pass

        doc = GAEBParser.parse_string(
            GAEB_WITH_VENDOR_EL, filename="test.X83",
            keep_xml=True, post_parse_hook=noop_hook,
        )
        assert doc.xml_root is not None


# ── 3. Custom Taxonomy & Prompt ──────────────────────────────────────

class TestCustomTaxonomyPrompt:
    def test_classifier_stores_taxonomy(self):
        tax = {"Elec": {"Cable": ["Ladder"]}}
        clf = LLMClassifier(taxonomy=tax)
        assert clf.taxonomy is tax

    def test_classifier_stores_prompt_template(self):
        pt = "You are an MEP expert..."
        clf = LLMClassifier(prompt_template=pt)
        assert clf.prompt_template == pt

    def test_default_taxonomy_is_none(self):
        clf = LLMClassifier()
        assert clf.taxonomy is None
        assert clf.prompt_template is None

    def test_register_prompt_and_retrieve(self):
        register_prompt("custom-v1", "My custom prompt text")
        assert get_prompt("custom-v1") == "My custom prompt text"

    def test_registered_prompt_overrides_builtin(self):
        register_prompt("v1", "Override of v1")
        assert get_prompt("v1") == "Override of v1"

    def test_unknown_version_falls_back_to_v1(self):
        result = get_prompt("nonexistent")
        assert "construction industry expert" in result


# ── 4. Log Level Application ─────────────────────────────────────────

class TestLogLevel:
    def test_configure_debug_sets_logger(self):
        configure(log_level="DEBUG")
        pygaeb_logger = logging.getLogger("pygaeb")
        assert pygaeb_logger.level == logging.DEBUG

    def test_configure_error_sets_logger(self):
        configure(log_level="ERROR")
        pygaeb_logger = logging.getLogger("pygaeb")
        assert pygaeb_logger.level == logging.ERROR

    def test_default_level_is_warning(self):
        reset_settings()
        _ = get_settings()
        pygaeb_logger = logging.getLogger("pygaeb")
        assert pygaeb_logger.level == logging.WARNING

    def test_configure_info_case_insensitive(self):
        configure(log_level="info")
        pygaeb_logger = logging.getLogger("pygaeb")
        assert pygaeb_logger.level == logging.INFO


# ── 5. Collect Raw Data ──────────────────────────────────────────────

class TestCollectRawData:
    def test_unknown_elements_in_raw_data(self):
        doc = GAEBParser.parse_string(
            GAEB_WITH_VENDOR_EL, filename="test.X83", collect_raw_data=True,
        )
        items = list(doc.iter_items())
        assert items[0].raw_data is not None
        assert "VendorCostCode" in items[0].raw_data
        assert items[0].raw_data["VendorCostCode"] == "VC-001"
        assert "CustomNote" in items[0].raw_data
        assert items[0].raw_data["CustomNote"] == "Important"

    def test_known_elements_excluded(self):
        doc = GAEBParser.parse_string(
            GAEB_WITH_VENDOR_EL, filename="test.X83", collect_raw_data=True,
        )
        items = list(doc.iter_items())
        raw = items[0].raw_data or {}
        # These are known tags and should NOT appear in raw_data
        assert "Qty" not in raw
        assert "QU" not in raw
        assert "UP" not in raw
        assert "Description" not in raw

    def test_raw_data_none_when_disabled(self):
        doc = GAEBParser.parse_string(
            GAEB_WITH_VENDOR_EL, filename="test.X83", collect_raw_data=False,
        )
        items = list(doc.iter_items())
        assert items[0].raw_data is None

    def test_collect_raw_data_discards_xml(self):
        doc = GAEBParser.parse_string(
            GAEB_WITH_VENDOR_EL, filename="test.X83",
            collect_raw_data=True, keep_xml=False,
        )
        assert doc.xml_root is None
        for item in doc.iter_items():
            assert item.source_element is None


# ── 6. reset_settings Export ─────────────────────────────────────────

class TestResetSettings:
    def test_importable_from_pygaeb(self):
        import pygaeb
        assert hasattr(pygaeb, "reset_settings")
        assert callable(pygaeb.reset_settings)

    def test_register_validator_importable(self):
        import pygaeb
        assert callable(pygaeb.register_validator)

    def test_clear_validators_importable(self):
        import pygaeb
        assert callable(pygaeb.clear_validators)

    def test_register_prompt_importable(self):
        import pygaeb
        assert callable(pygaeb.register_prompt)
