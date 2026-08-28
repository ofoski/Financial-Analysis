"""Tests for the parts of the extraction pipeline that don't need the
fine-tuned model itself (no GPU, no SEC filing fetch) - just the logic
that runs on the model's output afterward: parsing its picks, formatting
them for display, and resolving them to a real number.
"""
from xbrl_llm_match import _split_sign, format_selected, resolve_value


def test_split_sign_no_prefix_defaults_to_addition():
    assert _split_sign("Revenues") == (1, "Revenues")


def test_split_sign_plus_with_space():
    assert _split_sign("+ Revenues") == (1, "Revenues")


def test_split_sign_minus_with_space():
    assert _split_sign("- CostOfGoodsAndServicesSold") == (-1, "CostOfGoodsAndServicesSold")


def test_split_sign_minus_without_space():
    assert _split_sign("-CostOfGoodsAndServicesSold") == (-1, "CostOfGoodsAndServicesSold")


def test_format_selected_none_when_empty():
    assert format_selected([]) is None


def test_format_selected_single_label_unchanged():
    assert format_selected(["Revenues"]) == "Revenues"


def test_format_selected_multiple_labels_shows_explicit_signs():
    result = format_selected(["PropertyPlantAndEquipmentAdditions", "CapitalizedSoftware"])
    assert result == "+ PropertyPlantAndEquipmentAdditions + CapitalizedSoftware"


def test_resolve_value_none_when_no_selection():
    assert resolve_value([], {"Revenues": 94036000000.0}) is None


def test_resolve_value_single_label_converts_to_millions():
    value = resolve_value(["Revenues"], {"Revenues": 94036000000.0})
    assert value == 94036.0


def test_resolve_value_sums_multiple_labels():
    value_for_label = {"PropertyPlantAndEquipmentAdditions": 2000000.0, "CapitalizedSoftware": 940000.0}
    value = resolve_value(["PropertyPlantAndEquipmentAdditions", "CapitalizedSoftware"], value_for_label)
    assert value == 2.94


def test_resolve_value_subtracts_when_marked():
    value_for_label = {"Revenues": 94036000000.0, "CostOfGoodsAndServicesSold": 50318000000.0}
    value = resolve_value(["Revenues", "- CostOfGoodsAndServicesSold"], value_for_label)
    assert value == 43718.0


def test_resolve_value_per_share_skips_millions_conversion():
    value = resolve_value(["EarningsPerShareDiluted"], {"EarningsPerShareDiluted": 1.57}, per_share=True)
    assert value == 1.57


def test_resolve_value_none_when_label_missing():
    assert resolve_value(["Revenues"], {"SomethingElse": 1.0}) is None
