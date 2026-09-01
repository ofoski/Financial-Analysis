"""Exposes 3 tools for an AI assistant to fetch real financial data
step by step: which periods a company has actually filed, the real raw
statement data for whichever of those periods it needs, and the real
stock price (live, or on/near a real date). No variable matching or
analysis happens here - the calling agent reasons over the raw
candidates itself, using its own general intelligence instead of a
separately hosted model. Runs over streamable-http, so it's a normal
web server reachable over a URL, not just by clients that can launch a
local process.
"""
import os

import financial_data
import stock_price
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("financial-extraction", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))  # noqa: S104

VALID_STATEMENTS = {"income_statement", "balance_sheet", "cash_flow"}


@mcp.tool()
def list_periods(ticker: str):
    """Real fiscal years and quarters a company has actually filed with
    the SEC, each with its own real period-end date. FY = 10-K
    (annual); Q1/Q2/Q3 = 10-Q (quarterly - there's no Q4, the 10-K
    covers that period instead). Call this before get_report, to turn
    something like "2023" or "last quarter" into the real period-end
    date get_report needs, since fiscal quarters don't align to the
    calendar.

    Real example: list_periods("AAPL")."""
    periods = financial_data.list_periods(ticker)
    if periods is None:
        return {"error": f"Ticker '{ticker.upper()}' not found."}
    return periods


@mcp.tool()
def get_report(ticker: str, statement: str, annual_periods: list[str] | None = None, quarterly_periods: list[str] | None = None):
    """Real (label, value) line items for one statement, across one or
    more real periods. Use list_periods first to get real period-end
    dates - annual_periods/quarterly_periods must be those exact dates,
    not years or quarter labels. statement must be exactly one of:
    income_statement, balance_sheet, cash_flow. Returns the raw data as
    reported, with no variable matching or analysis done here - that's
    for the calling agent to reason over directly, e.g. picking out
    which line item represents "Revenue" from the real candidates.

    Real example: get_report("AAPL", "income_statement", annual_periods=["2025-09-27"])."""
    if statement not in VALID_STATEMENTS:
        return {"error": f"statement must be one of {list(VALID_STATEMENTS)}"}
    if not annual_periods and not quarterly_periods:
        return {"error": "Provide at least one period, in annual_periods or quarterly_periods."}

    rows = financial_data.get_report(ticker, statement, annual_periods, quarterly_periods)
    if rows is None:
        return {"error": f"Ticker '{ticker.upper()}' not found."}
    if not rows:
        return {"error": f"No real filed data found for {ticker.upper()} for the requested period(s) - check list_periods for the real dates this company actually filed."}
    return rows


@mcp.tool()
def get_stock_price(ticker: str, on_date: str | None = None):
    """Real stock price for any real, currently listed ticker - not
    limited to the companies covered by get_report/list_periods.
    Split/dividend-adjusted, so a real stock split doesn't look like
    the price crashed overnight - the number always reflects what one
    share was genuinely worth. If on_date is omitted, returns the
    current live price. If on_date (YYYY-MM-DD) is given, returns the
    real closing price on that date, or the closest real trading day
    before it if markets were closed that day (a weekend or holiday) -
    useful for pairing with a period_end from list_periods/get_report.

    Real example: get_stock_price("AAPL") for the live price, or
    get_stock_price("AAPL", "2024-09-28") for a specific date."""
    result = stock_price.get_price(ticker, on_date)
    if result is None:
        return {"error": f"No real price data found for '{ticker.upper()}'" + (f" near {on_date}." if on_date else ".")}
    return result


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
