"""Exposes 4 tools an AI assistant can call: fetch one company's annual
or quarterly financials, or compare growth/margins across companies.
Runs over streamable-http, so it's a normal web server reachable over a
URL, not just by clients that can launch a local process.
"""
import os

from mcp.server.fastmcp import FastMCP

from data import QUARTER_NUM, VARIABLES, get_annual, get_quarterly

mcp = FastMCP("financial-data", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))  # noqa: S104

MARGIN_FORMULAS = {
    "gross_margin": lambda row: _safe_divide(row["gross_profit"], row["revenue"]),
    "operating_margin": lambda row: _safe_divide(row["operating_income"], row["revenue"]),
    "net_margin": lambda row: _safe_divide(row["net_income"], row["revenue"]),
    "operating_cf_margin": lambda row: _safe_divide(row["operating_cf"], row["revenue"]),
    "fcf_margin": lambda row: _safe_divide(_free_cash_flow(row), row["revenue"]),
    "capex_ratio": lambda row: _safe_divide(row["capex"], row["revenue"]),
}


def _safe_divide(numerator, denominator):
    """Returns None instead of crashing when a stored variable is null or revenue is 0."""
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _free_cash_flow(row):
    """Operating CF minus CapEx, or None if either is missing - used by fcf_margin."""
    if row["operating_cf"] is None or row["capex"] is None:
        return None
    return row["operating_cf"] - row["capex"]


@mcp.tool()
def get_annual_financials(ticker: str, year: int, end_year: int | None = None):
    """A company's annual financials. end_year optionally extends year to
    a range; otherwise returns just the one row for year.

    Real example: get_annual_financials("AAPL", 2023)."""
    rows = get_annual(ticker, year, end_year)
    if not rows:
        return {"error": f"No annual data for {ticker.upper()}"}
    return rows


@mcp.tool()
def get_quarterly_financials(ticker: str, year: int, quarter: str, end_year: int | None = None, end_quarter: str | None = None):
    """A company's quarterly financials. quarter and end_quarter must be
    exactly "Q1", "Q2", or "Q3" (no Q4 - annual filings cover that period
    instead). end_year/end_quarter optionally extend year/quarter to a
    range; otherwise returns just the one matching row.

    Real example: get_quarterly_financials("AAPL", 2025, "Q1")."""
    if quarter not in QUARTER_NUM or (end_quarter is not None and end_quarter not in QUARTER_NUM):
        return {"error": f"quarter and end_quarter must be one of {list(QUARTER_NUM)}"}

    rows = get_quarterly(ticker, year, quarter, end_year, end_quarter)
    if not rows:
        return {"error": f"No quarterly data for {ticker.upper()}"}
    return rows


@mcp.tool()
def compare_growth(tickers: list[str], variable: str, start_year: int, end_year: int):
    """Year-over-year percent change in one variable across companies.
    variable must be one of: revenue, gross_profit, cost_of_revenue,
    operating_income, net_income, eps_diluted, cash, operating_cf, capex.
    The first year in the range always has a null pct_change, since
    there's no earlier year in the results to compare against.

    Real example: compare_growth(["AAPL", "MSFT"], "revenue", 2022, 2024)."""
    if variable not in VARIABLES:
        return {"error": f"variable must be one of {VARIABLES}"}

    results = []
    for ticker in tickers:
        prev_value = None
        for row in get_annual(ticker, start_year, end_year):
            value = row[variable]
            pct_change = (
                _safe_divide(value - prev_value, abs(prev_value))
                if prev_value is not None and value is not None else None
            )
            results.append({
                "ticker": row["ticker"], "fiscal_year_end": row["fiscal_year_end"],
                "value": value, "pct_change": pct_change,
            })
            prev_value = value
    return results


@mcp.tool()
def compare_margins(tickers: list[str], margin: str, year: int, end_year: int | None = None):
    """One margin/ratio across companies, computed live (no market price
    involved). margin must be one of: gross_margin, operating_margin,
    net_margin, operating_cf_margin, fcf_margin, capex_ratio - each a
    ratio against revenue.

    Real example: compare_margins(["AAPL", "MSFT"], "gross_margin", 2022, 2024)."""
    if margin not in MARGIN_FORMULAS:
        return {"error": f"margin must be one of {list(MARGIN_FORMULAS)}"}

    formula = MARGIN_FORMULAS[margin]
    results = []
    for ticker in tickers:
        for row in get_annual(ticker, year, end_year):
            results.append({
                "ticker": row["ticker"], "fiscal_year_end": row["fiscal_year_end"],
                margin: formula(row),
            })
    return results


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
