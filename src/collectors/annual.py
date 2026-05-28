import sqlite3
import sys
from pathlib import Path

# Add project root to path so imports work from any directory
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.collectors.financial_variables import FINANCIAL_VARIABLES
from src.collectors.tags import fetch_cik, fetch_ns, get_filing_periods, find_value
from src.collectors.gemini_fallback import gemini_fallback
from src.storage.database import COLUMN_MAP, upsert_annual

N_ANNUAL = 5


def _year_in_db(db_path, ticker, fiscal_year_end):
    """Return True if this (ticker, fiscal_year_end) row is already saved in the DB."""
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM financial_data_annual "
            "WHERE ticker = ? AND fiscal_year_end = ? AND collected_date IS NOT NULL",
            (ticker, fiscal_year_end),
        ).fetchone()
    return row is not None


def extract_annual(ns, ticker, cik, db_path=None, collected_date=None):
    """
    Collect annual (10-K) financial data for a company.

    Gets the last 5 fiscal year-end dates from SEC filing metadata,
    then for each year:
      - Skips the year if a row already exists in the DB (from a previous partial run).
      - Looks up every variable in FINANCIAL_VARIABLES via standard tag matching.
      - Calls Gemini once for any variables that were not found.
      - Saves the year's row to the DB immediately before moving to the next year,
        so a failure on a later year does not lose the data already collected.

    When db_path is None (standalone / debugging mode) the DB check and save are skipped.

    Returns a list of dicts for the years that were actually processed this run:
    {
        "ticker":          ...,
        "fiscal_year_end": ...,
        "data":            { db_column_name: value, ... }
    }
    """
    periods = get_filing_periods(cik, "10-K", N_ANNUAL)
    rows = []

    for period_end in periods:
        # Skip years that were already saved in a previous (possibly partial) run
        if db_path and _year_in_db(db_path, ticker, period_end):
            continue

        data    = {}
        missing = []

        for line_item, tag_list in FINANCIAL_VARIABLES.items():
            col = COLUMN_MAP[line_item]
            value, _unit, _tag, _filed = find_value(ns, tag_list, "10-K", "FY", period_end)
            data[col] = value
            if value is None:
                missing.append(line_item)

        if missing:
            fallback = gemini_fallback(missing, ns, ticker, "10-K", "FY", period_end)
            for line_item in missing:
                if fallback.get(line_item) is not None:
                    data[COLUMN_MAP[line_item]] = fallback[line_item]

        # Save immediately — if a later year raises an exception this year is not lost
        if db_path:
            upsert_annual(db_path, ticker, period_end, data, collected_date=collected_date)

        rows.append({
            "ticker":          ticker,
            "fiscal_year_end": period_end,
            "data":            data,
        })

    return rows


def _print_rows(rows):
    """Print a readable summary table for each fiscal year."""
    for row in sorted(rows, key=lambda r: r["fiscal_year_end"], reverse=True):
        data    = row["data"]
        found   = sum(1 for v in data.values() if v is not None)
        missing = len(data) - found

        print(f"\n{'='*70}")
        print(f"  {row['fiscal_year_end']}  10-K  FY  --  {found} found, {missing} NULL")
        print(f"  {'Column':<22}  {'Value ($M)':>14}")
        print(f"  {'-'*40}")

        for col, val in data.items():
            if val is not None:
                formatted = f"{val:>14,.2f}"
            else:
                formatted = f"{'NULL':>14}"
            print(f"  {col:<22}  {formatted}")


if __name__ == "__main__":
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(f"Fetching annual data for {ticker}...")

    cik  = fetch_cik(ticker)
    ns   = fetch_ns(cik)
    rows = extract_annual(ns, ticker, cik)  # no db_path → standalone mode, no DB check/save

    _print_rows(rows)
