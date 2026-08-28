"""Collects the income statement, balance sheet, and cash flow candidate
lists (label -> value) for a ticker's 10-K filings. A thin wrapper around
collect_statement_xbrl.py's shared engine, supplying the 10-K-specific
pieces: the 10-K filing lookup, and find_annual_period for both the
income statement and cash flow statement, since a 10-K reports both as
one full fiscal year, not a quarterly or year-to-date figure. No LLM
involved here, this only gathers data. See xbrl_llm_match.py for the
separate step that matches these candidates against a variable using an
LLM.
"""
from collect_statement_xbrl import collect_statement_candidates

from xbrl_method import find_annual_period, get_10k_filings_with_doc


def collect_annual_candidates(ticker, cik_int, fiscal_year_ends=None, statements=None):
    """Returns one row per 10-K filing: {ticker, period_end,
    income_statement, balance_sheet, cash_flow}. fiscal_year_ends and
    statements are passed straight through to collect_statement_candidates,
    see its docstring."""
    min_year = min(int(d[:4]) for d in fiscal_year_ends) if fiscal_year_ends else None
    return collect_statement_candidates(
        ticker, cik_int,
        get_filings=lambda cik: get_10k_filings_with_doc(str(cik).zfill(10), min_year=min_year),
        income_period_fn=find_annual_period, cash_flow_period_fn=find_annual_period,
        period_ends=fiscal_year_ends, statements=statements,
    )
