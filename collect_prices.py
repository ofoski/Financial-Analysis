import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf

from src.storage.database import init_db

DB_PATH = Path("data/financials.db")


def _price_on_or_before(hist_index, hist, target_date):
    """Return the closing price on the nearest trading day at or before target_date."""
    before = [d for d in hist_index if d <= target_date]
    if not before:
        return None
    return round(float(hist.loc[max(before), "Close"]), 4)


def collect_prices(db_path):
    """Fetch fiscal-year-end and filing-date closing prices for every company year missing them."""
    init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("""
            SELECT f.ticker, f.fiscal_year_end, f.filing_date
            FROM financial_data_annual f
            LEFT JOIN prices p ON f.ticker = p.ticker AND f.fiscal_year_end = p.fiscal_year_end
            WHERE p.fiscal_year_end IS NULL OR p.price IS NULL OR p.price_at_filing IS NULL
            ORDER BY f.ticker, f.fiscal_year_end
        """).fetchall()

    tickers = {}
    for ticker, fiscal_year_end, filing_date in rows:
        tickers.setdefault(ticker, []).append((fiscal_year_end, filing_date))

    total = len(tickers)
    print(f"{total} tickers to process. Ctrl+C to stop anytime.\n")

    for i, (ticker, year_rows) in enumerate(tickers.items(), 1):
        print(f"[{i}/{total}] {ticker} ...", end=" ", flush=True)
        try:
            all_dates = [d for row in year_rows for d in row if d]
            earliest  = datetime.strptime(min(all_dates), "%Y-%m-%d") - timedelta(days=7)
            hist = yf.Ticker(ticker).history(start=earliest.strftime("%Y-%m-%d"), end=datetime.today().strftime("%Y-%m-%d"))
            if hist.empty:
                print("no data")
                continue

            hist.index = [str(d)[:10] for d in hist.index]

            inserts = []
            for fiscal_year_end, filing_date in year_rows:
                price           = _price_on_or_before(hist.index, hist, fiscal_year_end)
                price_at_filing = _price_on_or_before(hist.index, hist, filing_date) if filing_date else None
                inserts.append((ticker, fiscal_year_end, price, filing_date, price_at_filing))

            with sqlite3.connect(db_path) as conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO prices (ticker, fiscal_year_end, price, filing_date, price_at_filing) "
                    "VALUES (?, ?, ?, ?, ?)",
                    inserts,
                )
            print(f"saved {len(inserts)}/{len(year_rows)}")

        except KeyboardInterrupt:
            print("\nStopped. Re-run to continue.")
            raise SystemExit

        except Exception as exc:
            print(f"error: {exc}")
            continue


if __name__ == "__main__":
    collect_prices(DB_PATH)
