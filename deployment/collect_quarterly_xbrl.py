"""Collects the income statement, balance sheet, and cash flow candidate
lists (label -> value) for a ticker's 10-Q filings. A thin wrapper around
collect_statement_xbrl.py's shared engine, supplying the 10-Q-specific
pieces: the 10-Q filing lookup, find_quarter_period for the income
statement (a standalone quarter), and find_cumulative_period for cash
flow (a 10-Q's cash flow statement only ever prints the year-to-date
total, not a standalone quarter). No LLM involved here, this only
gathers data. See xbrl_llm_match.py for the separate step that matches
these candidates against a variable using an LLM.
"""
from collect_statement_xbrl import collect_statement_candidates
from xbrl_method import (
    find_cumulative_period,
    find_quarter_period,
    get_10q_filings_with_doc,
)


def collect_quarterly_candidates(ticker, cik_int, quarter_ends=None, statements=None):
    """Returns one row per 10-Q filing: {ticker, period_end,
    income_statement, balance_sheet, cash_flow}. quarter_ends and
    statements are passed straight through to collect_statement_candidates,
    see its docstring. Without quarter_ends, only the 3 most recent
    filings are used, since "3 most recent" drifts as new filings come
    out; passing exact dates keeps results lined up with a reference
    dataset collected earlier."""
    return collect_statement_candidates(
        ticker, cik_int,
        get_filings=lambda cik: get_10q_filings_with_doc(str(cik).zfill(10)),
        income_period_fn=find_quarter_period, cash_flow_period_fn=find_cumulative_period,
        period_ends=quarter_ends, statements=statements, default_limit=3,
    )
