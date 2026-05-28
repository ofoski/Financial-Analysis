import sys
from pathlib import Path

# Add project root to path so imports work from any directory
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.collectors.financial_variables import FINANCIAL_VARIABLES
from src.collectors.tags import fetch_cik, fetch_ns, get_filing_periods, find_value
from src.storage.database import COLUMN_MAP

N_ANNUAL = 5


def extract_annual(ns, ticker, cik):
    """
    Collect annual (10-K) financial data for a company.

    Gets the last 5 fiscal year-end dates from SEC filing metadata,
    then for each year looks up every variable in FINANCIAL_VARIABLES.

    Returns a list of dicts, one per fiscal year:
    {
        "ticker":          ...,
        "fiscal_year_end": ...,
        "data":            { db_column_name: value, ... }
    }
    """
    periods = get_filing_periods(cik, "10-K", N_ANNUAL)
    rows = []

    for period_end in periods:
        data = {}
        for line_item, tag_list in FINANCIAL_VARIABLES.items():
            col = COLUMN_MAP[line_item]
            value, _unit, _tag, _filed = find_value(ns, tag_list, "10-K", "FY", period_end)
            data[col] = value

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
    rows = extract_annual(ns, ticker, cik)

    _print_rows(rows)
