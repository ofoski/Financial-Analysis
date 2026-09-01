"""Business logic behind the MCP server's tools: resolving a ticker to
its real SEC CIK, listing which periods a company has actually filed,
and fetching one statement's raw real (label, value) candidates for
one or more of those periods. No MCP-specific code here at all -
server.py is just a thin layer of @mcp.tool() wrappers around these
functions, so the tool definitions and the real data-gathering work
stay separate.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "xbrl_pipeline"))
from collect_annual_xbrl import collect_annual_candidates
from collect_quarterly_xbrl import collect_quarterly_candidates
from edgar_helpers import get_cik_map

from xbrl_method import list_available_quarters

_cik_map = None


def _get_cik_map():
    """Downloads SEC's full ticker -> CIK list on first use only, then
    reuses it in memory for the rest of the server's lifetime, instead
    of re-downloading it on every call."""
    global _cik_map  # noqa: PLW0603
    if _cik_map is None:
        _cik_map = get_cik_map()
    return _cik_map


def resolve_ticker(ticker):
    """Looks up one ticker's real CIK and company name. Returns None if
    it isn't a real, known ticker.

    Real example: resolve_ticker("AAPL") returns
    {"cik": "0000320193", "name": "Apple Inc."}"""
    return _get_cik_map().get(ticker.strip().upper())


def list_periods(ticker):
    """Real fiscal years and quarters this company has actually filed
    with the SEC, each with its own real period-end date. Returns None
    if the ticker isn't real/known."""
    entry = resolve_ticker(ticker)
    if not entry:
        return None
    return list_available_quarters(entry["cik"])


def get_report(ticker, statement, annual_periods=None, quarterly_periods=None):
    """Raw real (label, value) candidates for one statement, across one
    or more real periods. annual_periods/quarterly_periods are real
    period-end dates (e.g. from list_periods' output), not years or
    quarter labels. Returns None if the ticker isn't real/known,
    otherwise one row per period: {"period_end": ..., "candidates": [...]}."""
    entry = resolve_ticker(ticker)
    if not entry:
        return None
    cik_int = int(entry["cik"])
    ticker = ticker.strip().upper()

    rows = []
    if annual_periods:
        for row in collect_annual_candidates(
            ticker, cik_int, fiscal_year_ends=set(annual_periods), statements={statement},
        ):
            rows.append({"period_end": row["period_end"], "candidates": row[statement]})
    if quarterly_periods:
        for row in collect_quarterly_candidates(
            ticker, cik_int, quarter_ends=set(quarterly_periods), statements={statement},
        ):
            rows.append({"period_end": row["period_end"], "candidates": row[statement]})
    return rows
