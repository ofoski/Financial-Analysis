"""Tests for the MCP server's own error handling.
"""
import server


def test_get_report_rejects_invalid_statement():
    # rejected before any network call, statement is checked first
    result = server.get_report("AAPL", "weather_forecast", annual_periods=["2024-09-28"])
    assert "error" in result
    assert "statement must be one of" in result["error"]


def test_get_report_requires_at_least_one_period():
    # rejected before any network call too
    result = server.get_report("AAPL", "income_statement")
    assert "error" in result
    assert "Provide at least one period" in result["error"]


def test_list_periods_unknown_ticker():
    # needs a real network call, to fetch SEC's real ticker list and
    # confirm this one genuinely isn't in it
    result = server.list_periods("NOTREALTICKERXYZ")
    assert result == {"error": "Ticker 'NOTREALTICKERXYZ' not found."}
