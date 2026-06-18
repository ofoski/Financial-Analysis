import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import yfinance as yf

DB_PATH = Path("data/financials.db")

with sqlite3.connect(DB_PATH) as conn:
    rows = conn.execute("""
        SELECT f.ticker, f.fiscal_year_end
        FROM financial_data_annual f
        LEFT JOIN prices p ON f.ticker = p.ticker AND f.fiscal_year_end = p.date
        WHERE p.date IS NULL
        ORDER BY f.ticker
    """).fetchall()

ticker_dates = defaultdict(list)
for ticker, date in rows:
    ticker_dates[ticker].append(date)

total = len(ticker_dates)
print(f"{total} tickers to process. Ctrl+C to stop anytime.\n")

for i, (ticker, dates) in enumerate(ticker_dates.items(), 1):
    print(f"[{i}/{total}] {ticker} ...", end=" ", flush=True)
    try:
        earliest = datetime.strptime(min(dates), "%Y-%m-%d") - timedelta(days=7)
        hist = yf.Ticker(ticker).history(start=earliest.strftime("%Y-%m-%d"), end=datetime.today().strftime("%Y-%m-%d"))
        if hist.empty:
            print("no data")
            continue

        hist.index = [str(d)[:10] for d in hist.index]

        inserts = []
        for date in dates:
            before = [d for d in hist.index if d <= date]
            if not before:
                continue
            price = round(float(hist.loc[max(before), "Close"]), 4)
            inserts.append((ticker, date, price))

        with sqlite3.connect(DB_PATH) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO prices (ticker, date, price) VALUES (?, ?, ?)",
                inserts,
            )
        print(f"saved {len(inserts)}/{len(dates)}")

    except KeyboardInterrupt:
        print("\nStopped. Re-run to continue.")
        raise SystemExit

    except Exception as exc:
        print(f"error: {exc}")
