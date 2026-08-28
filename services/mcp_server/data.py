"""Queries yearly_variables and quarterly_variables for the 9 tracked
variables (Revenue, Gross Profit, Cost of Revenue, Operating Income,
Net Income, EPS Diluted, Cash, Operating CF, CapEx). A duplicate of this
file lives in the REST API too, so each service can be deployed on its
own.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "financials.db"

# Both tables happen to use the exact same column names for these 9
# variables, so one shared mapping works for both.
VARIABLES = ["revenue", "gross_profit", "cost_of_revenue", "operating_income",
             "net_income", "eps_diluted", "cash", "operating_cf", "capex"]

QUARTER_NUM = {"Q1": 1, "Q2": 2, "Q3": 3}


def _query(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_annual(ticker, year, end_year=None):
    """Annual rows for one ticker. end_year, if given, extends year to a
    range; otherwise returns just the one row for year.

    Real example: get_annual("AAPL", 2023) returns one row."""
    ticker = ticker.strip().upper()
    cols = ", ".join(["ticker", "fiscal_year_end", "filing_date", *VARIABLES])
    sql = (
        f"SELECT {cols} FROM yearly_variables "  # noqa: S608
        "WHERE ticker = ? AND fiscal_year_end >= ? AND fiscal_year_end <= ? "
        "ORDER BY fiscal_year_end ASC"
    )
    params = [ticker, f"{year}-01-01", f"{end_year or year}-12-31"]
    return _query(sql, params)


def get_quarterly(ticker, year, quarter, end_year=None, end_quarter=None):
    """Quarterly rows for one ticker (Q1-Q3 only). year/quarter identify
    the fiscal quarter, matched against period_label since quarters don't
    align to the calendar. end_year/end_quarter, if both given, extend it
    to a range; otherwise returns just the one matching row.

    Real example: get_quarterly("AAPL", 2025, "Q1") returns one row."""
    ticker = ticker.strip().upper()
    if quarter not in QUARTER_NUM or (end_quarter is not None and end_quarter not in QUARTER_NUM):
        return []

    cols = ", ".join(["ticker", "quarter_end", "filing_date", "period_label", *VARIABLES])
    sql = f"SELECT {cols} FROM quarterly_variables WHERE ticker = ? ORDER BY quarter_end ASC"  # noqa: S608
    rows = _query(sql, [ticker])

    start_key = (year, QUARTER_NUM[quarter])
    if end_year is not None and end_quarter is not None:
        end_key = (end_year, QUARTER_NUM[end_quarter])
    else:
        end_key = start_key

    def label_key(row):
        q, y = row["period_label"].split()
        return (int(y), QUARTER_NUM[q])

    return [row for row in rows if start_key <= label_key(row) <= end_key]
