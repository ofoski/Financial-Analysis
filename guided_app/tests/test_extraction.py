"""Tests for the deterministic, model-free parts of extraction.py -
no GPU or fine-tuned model needed, since none of these paths call it.
Several of these cases are real bugs found and fixed during testing:
the model itself misreading a specific year, failing to recognize
"annual"/"fiscal"/"full year" as a full year, and scoring an unrelated
word as a closer match than a genuine typo.
"""
from extraction import _extract_quarter, _extract_year, _match_variables_deterministic


def test_extract_year_plain():
    assert _extract_year("2024") == 2024


def test_extract_year_specific_year_that_broke_the_model():
    assert _extract_year("2025") == 2025


def test_extract_year_no_year_present():
    assert _extract_year("no year here") is None


def test_extract_year_ignores_out_of_range_numbers():
    assert _extract_year("12345") is None


def test_extract_quarter_q_notation():
    assert _extract_quarter("Q2 2024") == "Q2"


def test_extract_quarter_spelled_out():
    assert _extract_quarter("second quarter") == "Q2"


def test_extract_quarter_full_year_wordings():
    assert _extract_quarter("annual") == "FY"
    assert _extract_quarter("fiscal year") == "FY"
    assert _extract_quarter("full year") == "FY"


def test_extract_quarter_none_mentioned():
    assert _extract_quarter("2024") is None


def test_match_variables_clean_list():
    matched, leftover = _match_variables_deterministic("Revenue and Cash")
    assert set(matched) == {"Revenue", "Cash"}
    assert leftover == []


def test_match_variables_typo_still_matches():
    matched, _ = _match_variables_deterministic("Revenu")
    assert matched == ["Revenue"]


def test_match_variables_unrelated_word_not_matched():
    matched, leftover = _match_variables_deterministic("casher")
    assert matched == []
    assert leftover == ["casher"]


def test_match_variables_semicolon_separator():
    matched, _ = _match_variables_deterministic("Gross Profit; Cost of Revenue")
    assert set(matched) == {"Gross Profit", "Cost of Revenue"}


def test_match_variables_ampersand_separator():
    matched, _ = _match_variables_deterministic("Operating Income & Net Income")
    assert set(matched) == {"Operating Income", "Net Income"}


def test_match_variables_messy_sentence_falls_back():
    # not a clean list - real variable names buried in a full sentence
    # should be left for the model fallback, not silently dropped
    _, leftover = _match_variables_deterministic("just give me the revenue please")
    assert leftover
