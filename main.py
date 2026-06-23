import json
import logging
import sqlite3
import time
from datetime import date
from pathlib import Path

from src.collectors.edgar import get_cik_map, get_10k_filings, fetch_filing_tables
from src.collectors.extractor import extract_from_filing
from src.storage.database import COLUMN_MAP, init_db, save_company, save_annual

# ── Configuration ─────────────────────────────────────────────────────────────
SECTOR_FILTER = []
N_ANNUAL      = 10  # years to collect per company
TRIAL_LIMIT   = None

PROGRESS_FILE = Path("progress.json")
DB_PATH       = Path("data/financials.db")

_raw            = json.loads(Path("config/russell_3000_equity_holdings.json").read_text())
COMPANIES       = [e["ticker"].upper() for e in _raw[:40]]
COMPANY_SECTORS = {e["ticker"].upper(): e.get("sector") for e in _raw}

logging.basicConfig(
    filename="errors.log",
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_progress():
    """Load the set of already-completed tickers from the progress file."""
    if PROGRESS_FILE.exists():
        return set(json.loads(PROGRESS_FILE.read_text()))
    return set()


def save_progress(done):
    """Save the set of completed tickers to the progress file."""
    PROGRESS_FILE.write_text(json.dumps(sorted(done)))


def _count_saved_years(db_path, ticker):
    """Return how many valid annual rows exist for a ticker in the database."""
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM financial_data_annual "
            "WHERE ticker = ? AND revenue IS NOT NULL AND current_assets IS NOT NULL",
            (ticker,),
        ).fetchone()
    return row[0] if row else 0


# ── Core pipeline ─────────────────────────────────────────────────────────────

def _drop_incomplete(db_path, ticker):
    """Delete rows that are missing balance sheet data (gap years not yet filled)."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "DELETE FROM financial_data_annual WHERE ticker = ? AND current_assets IS NULL",
            (ticker,),
        )
        conn.commit()


def collect_ticker(ticker, cik_entry, db_path):
    """Fetch filings from EDGAR, extract financials, and save all years for one ticker."""
    cik_int = int(cik_entry["cik"])
    save_company(db_path, ticker, name=cik_entry["name"], sector=COMPANY_SECTORS.get(ticker))

    filings = get_10k_filings(cik_entry["cik"])
    if not filings:
        raise ValueError("No 10-K filings found")

    today        = date.today().isoformat()
    saved_before = _count_saved_years(db_path, ticker)

    # Every-2nd filing: each overlaps 1 year so the gap-year balance sheet is filled by the next filing.
    n_filings = (N_ANNUAL + 1) // 2
    selected  = filings[0::2][:n_filings]

    for accession, _ in selected:
        if _count_saved_years(db_path, ticker) >= N_ANNUAL:
            break

        try:
            tables = fetch_filing_tables(cik_int, accession)
        except Exception as exc:
            logging.error("%s %s: fetch failed: %s", ticker, accession, exc)
            continue

        try:
            year_rows = extract_from_filing(tables, ticker)
        except RuntimeError:
            raise
        except Exception as exc:
            logging.error("%s %s: extraction failed: %s", ticker, accession, exc)
            print(f"\n  Skipping filing {accession}: {exc}")
            continue

        for year in year_rows:
            fy_end = year.get("fiscal_year_end")
            if not fy_end:
                continue
            data = {}
            for var_name, col in COLUMN_MAP.items():
                item = year.get(var_name)
                val  = item.get("value") if isinstance(item, dict) else item
                data[col] = float(val) if isinstance(val, (int, float)) else None
            save_annual(db_path, ticker, fy_end, data, collected_date=today)

    _drop_incomplete(db_path, ticker)
    return _count_saved_years(db_path, ticker) - saved_before


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    """Run the full collection pipeline for all companies in the list."""
    db_path = init_db(DB_PATH)
    done = load_progress()

    print("Loading CIK map from SEC...")
    try:
        cik_map = get_cik_map()
    except Exception as exc:
        logging.error("Failed to load CIK map: %s", exc)
        print(f"ERROR: {exc}")
        return

    remaining = [t for t in COMPANIES if t not in done]
    if SECTOR_FILTER:
        remaining = [t for t in remaining if COMPANY_SECTORS.get(t) in SECTOR_FILTER]
        print(f"Sector filter: {SECTOR_FILTER}")
    if TRIAL_LIMIT:
        remaining = remaining[:TRIAL_LIMIT]
        print(f"Trial mode: {TRIAL_LIMIT} companies")

    print(f"{len(done)} done, {len(remaining)} remaining\n")

    for i, ticker in enumerate(remaining, 1):
        cik_entry = cik_map.get(ticker.upper())
        if not cik_entry:
            print(f"[{i}/{len(remaining)}] {ticker} — CIK not found, skipping")
            continue

        print(f"[{i}/{len(remaining)}] {ticker} ...", end=" ", flush=True)

        try:
            saved = collect_ticker(ticker, cik_entry, db_path)
            done.add(ticker)
            save_progress(done)
            print(f"OK ({saved} years saved)")
        except RuntimeError as exc:
            logging.error("%s: %s", ticker, exc)
            print(f"\nStopped: {exc}")
            break
        except Exception as exc:
            logging.error("%s: %s", ticker, exc)
            print("ERROR — see errors.log")

        if i < len(remaining):
            time.sleep(0.5)

    print(f"\nDone. {len(done)}/{len(COMPANIES)} collected.")


if __name__ == "__main__":
    main()
