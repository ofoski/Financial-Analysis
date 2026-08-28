"""REST API for this project's 9-variable financial data (yearly_variables
and quarterly_variables only). A FastAPI app: each route is a GET
endpoint, since this only reads data, never writes it. Same data as the
MCP server's tools, just reachable over plain HTTP for non-AI callers
(scripts, other apps, curl) instead of through an AI agent.
"""
from fastapi import FastAPI, HTTPException

from data import QUARTER_NUM, get_annual, get_quarterly

app = FastAPI(
    title="Financial Data API",
    description="Real annual and quarterly financials for 187 tracked tickers.",
)


@app.get("/annual/{ticker}")
def annual_financials(ticker: str, year: int, end_year: int | None = None):
    """Real annual financials for one ticker, one row per fiscal year.
    Without end_year, returns just the one row for year.

    Real example: GET /annual/AAPL?year=2023&end_year=2024
    """
    rows = get_annual(ticker, year, end_year)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No annual data for {ticker.upper()}")
    return rows


@app.get("/quarterly/{ticker}")
def quarterly_financials(ticker: str, year: int, quarter: str, end_year: int | None = None, end_quarter: str | None = None):
    """Real quarterly financials for one ticker (10-Q filings only, Q1-Q3
    each fiscal year), one row per quarter, each labeled with its real
    fiscal quarter and year (e.g. "Q2 2025"). Without end_year/end_quarter,
    returns just the one row for year/quarter.

    Real example: GET /quarterly/AAPL?year=2025&quarter=Q1&end_year=2025&end_quarter=Q3
    """
    if quarter not in QUARTER_NUM or (end_quarter is not None and end_quarter not in QUARTER_NUM):
        raise HTTPException(status_code=400, detail=f"quarter and end_quarter must be one of {list(QUARTER_NUM)}")

    rows = get_quarterly(ticker, year, quarter, end_year, end_quarter)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No quarterly data for {ticker.upper()}")
    return rows
