import json
import logging
import time
from datetime import date
from pathlib import Path

import requests

from src.collectors.tags import HEADERS, TICKERS_URL, fetch_ns
from src.collectors.annual import extract_annual
from src.collectors.accounting import apply_accounting_identities
from src.storage.database import init_db, upsert_company
from src.analysis.metrics import create_metrics_view

# ── Sector filter ──────────────────────────────────────────────────────────────
# Set to a list of sector names to only collect those sectors.
# Set to [] to collect all sectors (full Russell 3000 run).
SECTOR_FILTER = ["Information Technology"]

# ── Company list ───────────────────────────────────────────────────────────────
COMPANIES = [
    entry["ticker"]
    for entry in json.loads(Path("config/russell_3000_equity_holdings.json").read_text())
]

PROGRESS_FILE = Path("progress.json")
DB_PATH       = Path("data/financials.db")
AUDIT_PATH    = Path("data/extraction_audit.jsonl")

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
    Load sector data from the Russell 3000 config file.
    Returns a dict: { "AAPL": {"sector": ...}, ... }
    """
    config_path = Path("config/russell_3000_equity_holdings.json")
    if not config_path.exists():
        return {}
    entries = json.loads(config_path.read_text())
    return {
        e["ticker"].upper(): {"sector": e.get("sector")}
        for e in entries
    }


def process_ticker(ticker, cik_map, company_config, db_path, audit_path):
    """
    Run the full collection pipeline for one ticker:
    1. Look up CIK and company name from the pre-loaded map
    2. Save company info (name, sector) to the companies table
    3. Download XBRL facts from SEC
    4. Extract annual data and save each fiscal year to the DB
    """
    entry = cik_map.get(ticker.upper())
    if not entry:
        raise ValueError(f"CIK not found for {ticker}")

    cik  = entry["cik"]
    name = entry["name"]

    ns = fetch_ns(cik)  # fetch first — only insert company if this succeeds

    extra  = company_config.get(ticker.upper(), {})
    sector = extra.get("sector")
    upsert_company(db_path, ticker, name=name, sector=sector)

    today = date.today().isoformat()
    extract_annual(ns, ticker, cik, db_path=db_path, collected_date=today, sector=sector, audit_path=audit_path)
    apply_accounting_identities(db_path, ticker)



def main():
    db_path = init_db(DB_PATH)
    create_metrics_view(db_path)
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

    if SECTOR_FILTER:
        remaining = [t for t in remaining if company_config.get(t, {}).get("sector") in SECTOR_FILTER]
        print(f"Sector filter active: {SECTOR_FILTER}")

    print(f"{len(done)} already done, {len(remaining)} remaining\n")

    for i, ticker in enumerate(remaining, 1):
        print(f"[{i}/{len(remaining)}] {ticker} ...", end=" ", flush=True)
        try:
            process_ticker(ticker, cik_map, company_config, db_path, AUDIT_PATH)
            done.add(ticker)
            save_progress(done)
            print("OK")
        except Exception as exc:
            logging.error("%s: %s", ticker, exc)
            print("ERROR -- see errors.log")

        if i < len(remaining):
            time.sleep(0.5)

    print(f"\nDone. {len(done)}/{len(COMPANIES)} tickers collected.")


if __name__ == "__main__":
    main()
