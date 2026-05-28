import json
import logging
import sqlite3
import time
from datetime import date
from pathlib import Path

import requests

from src.collectors.tags import HEADERS, TICKERS_URL, fetch_ns
from src.collectors.annual import extract_annual
from src.storage.database import init_db, upsert_company, upsert_annual, COLUMN_MAP

# ── Edit this list to choose which companies to collect ───────────────────────
# To run on the full Russell 2000:
# COMPANIES = [entry["ticker"] for entry in json.loads(Path("config/russell2000_companies.json").read_text())]
COMPANIES = ["AAPL",'MSFT', 'GOOGL', 'AMZN', 'META']  # <-- example with just a few tickers for testing

PROGRESS_FILE = Path("progress.json")
DB_PATH       = Path("data/financials.db")

logging.basicConfig(
    filename="errors.log",
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def load_cik_map():
    """
    Download the full SEC ticker-to-CIK mapping in one request.
    Also captures the company name from the same response.
    Returns a dict like {"AAPL": {"cik": "0000320193", "name": "Apple Inc."}, ...}.
    """
    resp = requests.get(TICKERS_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    result = {}
    for v in resp.json().values():
        ticker = v["ticker"].upper()
        result[ticker] = {
            "cik":  str(v["cik_str"]).zfill(10),
            "name": v.get("title", ""),
        }
    return result


def load_progress():
    """Read the set of tickers already completed from progress.json."""
    if PROGRESS_FILE.exists():
        return set(json.loads(PROGRESS_FILE.read_text()))
    return set()


def save_progress(done):
    """Save the set of completed tickers to progress.json."""
    PROGRESS_FILE.write_text(json.dumps(sorted(done)))


def load_company_config():
    """
    Load sector and industry data from the Russell 2000 config file.
    Returns a dict: { "AAPL": {"sector": ..., "industry": ...}, ... }
    """
    config_path = Path("config/russell2000_companies.json")
    if not config_path.exists():
        return {}
    entries = json.loads(config_path.read_text())
    return {
        e["ticker"].upper(): {"sector": e.get("sector"), "industry": e.get("industry")}
        for e in entries
    }


def process_ticker(ticker, cik_map, company_config, db_path):
    """
    Run the full collection pipeline for one ticker:
    1. Look up CIK and company name from the pre-loaded map
    2. Save company info (name, sector, industry) to the companies table
    3. Download XBRL facts from SEC
    4. Extract annual data and save each fiscal year to the DB
    """
    entry = cik_map.get(ticker.upper())
    if not entry:
        raise ValueError(f"CIK not found for {ticker}")

    cik  = entry["cik"]
    name = entry["name"]

    extra = company_config.get(ticker.upper(), {})
    upsert_company(db_path, ticker, name=name, sector=extra.get("sector"), industry=extra.get("industry"))

    ns = fetch_ns(cik)

    today = date.today().isoformat()
    for row in extract_annual(ns, ticker, cik):
        upsert_annual(db_path, row["ticker"], row["fiscal_year_end"], row["data"], collected_date=today)


def print_results(db_path, ticker):
    """
    Read back what was saved for a ticker and print it as a table,
    one section per fiscal year.
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM financial_data_annual WHERE ticker = ? ORDER BY fiscal_year_end DESC",
            (ticker,),
        ).fetchall()

    if not rows:
        print("  No data found.")
        return

    col_names = list(COLUMN_MAP.values())

    for row in rows:
        found   = sum(1 for col in col_names if row[col] is not None)
        missing = len(col_names) - found

        print(f"\n  {row['fiscal_year_end']}  10-K  FY  --  {found} found, {missing} NULL")
        print(f"  {'Column':<22}  {'Value ($M)':>14}")
        print(f"  {'-'*40}")

        for col in col_names:
            val = row[col]
            if val is not None:
                formatted = f"{val:>14,.2f}"
            else:
                formatted = f"{'NULL':>14}"
            print(f"  {col:<22}  {formatted}")


def main():
    db_path = init_db(DB_PATH)
    done    = load_progress()

    print("Loading CIK map from SEC...")
    try:
        cik_map = load_cik_map()
    except Exception as exc:
        logging.error("Failed to load CIK map: %s", exc)
        print(f"ERROR: could not load CIK map -- {exc}")
        return

    company_config = load_company_config()

    remaining = [t for t in COMPANIES if t not in done]
    print(f"{len(done)} already done, {len(remaining)} remaining out of {len(COMPANIES)} total\n")

    for i, ticker in enumerate(remaining, 1):
        print(f"[{i}/{len(remaining)}] {ticker} ...", end=" ", flush=True)
        try:
            process_ticker(ticker, cik_map, company_config, db_path)
            done.add(ticker)
            save_progress(done)
            print("OK")
        except Exception as exc:
            logging.error("%s: %s", ticker, exc)
            print("ERROR -- see errors.log")

        if i < len(remaining):
            time.sleep(0.5)

    print(f"\nDone. {len(done)}/{len(COMPANIES)} tickers collected.")

    for ticker in COMPANIES:
        if ticker in done:
            print(f"\n{'='*70}\n  RESULTS -- {ticker}\n{'='*70}")
            print_results(db_path, ticker)


if __name__ == "__main__":
    main()
