"""
Russell 2000 company list collector.

Uses two NASDAQ public APIs (no API key required):
  1. Screener API   — small/micro-cap stocks from NASDAQ and NYSE (~2,400 stocks)
  2. Profile API    — sector and industry per ticker

This is a close approximation of the Russell 2000 (US small-cap index).
Run once and save to JSON; subsequent calls use load_company_list() instead.
Expected runtime: ~5 minutes (one HTTP request per ticker for sector data).
"""

import json
import time
from pathlib import Path

import requests

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json",
    "Referer": "https://www.nasdaq.com/",
}


def get_russell2000_list() -> list[dict]:
    """
    Fetch ~2,000 Russell 2000-equivalent small-cap companies.
    Returns list of dicts with keys: ticker, name, sector, industry.
    """
    tickers = _fetch_tickers()
    if not tickers:
        return []

    companies = []
    total = len(tickers)
    print(f"Fetching sector data for {total} companies (this takes ~5 minutes)...")

    for i, (ticker, name) in enumerate(tickers, 1):
        if i % 100 == 0:
            print(f"  {i}/{total}")
        sector, industry = _fetch_sector(ticker)
        companies.append({"ticker": ticker, "name": name, "sector": sector, "industry": industry})
        time.sleep(0.1)  # avoid hammering the NASDAQ API

    return companies


def _fetch_tickers() -> list[tuple]:
    """Get deduplicated (ticker, name) pairs for US small/micro-cap stocks."""
    seen = set()
    results = []

    for exchange in ["NASDAQ", "NYSE"]:
        for marketcap in ["small", "micro"]:
            try:
                r = requests.get(
                    "https://api.nasdaq.com/api/screener/stocks",
                    params={"tableonly": "true", "limit": 3000, "exchange": exchange, "marketcap": marketcap},
                    headers=_HEADERS,
                    timeout=20,
                )
                r.raise_for_status()
                rows = r.json().get("data", {}).get("table", {}).get("rows") or []
                for row in rows:
                    sym = row["symbol"]
                    if sym not in seen:
                        seen.add(sym)
                        results.append((sym, row["name"]))
            except requests.RequestException as e:
                print(f"Warning: screener error ({exchange}/{marketcap}): {e}")

    print(f"Found {len(results)} unique small-cap tickers.")
    return results


def _fetch_sector(ticker: str) -> tuple[str, str]:
    """Return (sector, industry) for a single ticker from the NASDAQ profile API."""
    try:
        r = requests.get(
            f"https://api.nasdaq.com/api/company/{ticker}/company-profile",
            headers=_HEADERS,
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json().get("data") or {}
            sector = (data.get("Sector") or {}).get("value") or "Unknown"
            industry = (data.get("Industry") or {}).get("value") or "Unknown"
            return sector, industry
    except requests.RequestException:
        pass
    return "Unknown", "Unknown"


def save_company_list(companies: list[dict], filepath: str = "config/russell2000_companies.json") -> None:
    """Save company list to a JSON file, creating the directory if needed."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(companies, indent=2), encoding="utf-8")
    print(f"Saved {len(companies)} companies to {path}.")


def load_company_list(filepath: str = "config/russell2000_companies.json") -> list[dict]:
    """Load company list from JSON. Returns [] if the file does not exist."""
    path = Path(filepath)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


if __name__ == "__main__":
    print("Fetching Russell 2000 small-cap company list from NASDAQ...")
    companies = get_russell2000_list()
    if companies:
        save_company_list(companies)
        print(f"\nDone — {len(companies)} companies saved.")
        for c in companies[:5]:
            print(f"  {c['ticker']:6s}  {c['name']:<40s}  {c['sector']}")
    else:
        print("No data retrieved. Check network connection and try again.")
