"""Builds a local, cached company list for variable_lookup/app.py's
dropdown, instead of it fetching SEC's full ~10,000-company list live
on every restart.

Two things this does beyond a plain cache:
  1. Filters out companies that don't actually file Form 10-K or 10-Q
     (mainly foreign private issuers, who file 20-F/40-F/6-K instead) -
     this pipeline only ever reads 10-K/10-Q filings, so a company
     that never files either would always come back "not found" if
     picked. Checked via each company's real SEC filing history
     (data.sec.gov/submissions), not guessed.
  2. Normalizes the display name's casing (SEC's raw data mixes ALL
     CAPS legacy names with properly-cased modern ones), for a more
     visually consistent dropdown.

This makes ~10,000 real network requests (one per company, to check
its filing history), rate-limited to respect SEC's guidance, so it
takes a while (tens of minutes). Progress is saved incrementally to
OUT_PATH after every company, so it can be safely interrupted and
rerun - already-checked tickers (kept or excluded) are skipped on the
next run.
"""
import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent / "xbrl_pipeline"))
from edgar_helpers import HEADERS, get_cik_map

OUT_PATH = Path(__file__).parent / "companies_cache.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
RATE_LIMIT_DELAY = 0.15  # ~6-7 requests/second, under SEC's 10 req/s guidance

DOMESTIC_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A"}


def normalize_name(name):
    """Title-cases an ALL CAPS name (e.g. "MICROSOFT CORP" ->
    "Microsoft Corp"), but leaves already-mixed-case names alone
    (e.g. "AbbVie Inc." stays as-is, not flattened to "Abbvie Inc.").
    Every word is title-cased uniformly, including suffixes like
    "Corp"/"Inc"/"Llc" - no special-casing to keep some words upper,
    since that produced visually inconsistent results of its own (e.g.
    "Microsoft CORP"). Not perfect (a few odd real names like "AT&T"
    or "3M" will come out imperfectly), but a clear visual improvement
    over raw SEC casing for the common case. This is a display-only
    value - the real, unmodified SEC name is kept alongside it, never
    replaced, since other code (e.g. the chat app's resolve_company())
    matches against the exact real name."""
    if not name.isupper():
        return name  # already has real mixed case - trust it as-is
    return " ".join(w.capitalize() if w else w for w in name.split(" "))


def is_domestic_filer(cik):
    url = SUBMISSIONS_URL.format(cik=cik)
    resp = requests.get(url, headers=HEADERS, timeout=15)
    if resp.status_code != 200:
        return False
    forms = resp.json().get("filings", {}).get("recent", {}).get("form", [])
    return any(f in DOMESTIC_FORMS for f in forms)


def load_existing():
    if OUT_PATH.exists():
        with open(OUT_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"kept": {}, "excluded": []}


def main():
    cik_map = get_cik_map()
    print(f"total companies in SEC's list: {len(cik_map)}")

    state = load_existing()
    kept = state["kept"]
    excluded = set(state["excluded"])
    already_done = set(kept) | excluded
    remaining = [(t, e) for t, e in cik_map.items() if t not in already_done]
    print(f"already checked in a previous run: {len(already_done)}, remaining: {len(remaining)}")

    failures = 0
    for i, (ticker, entry) in enumerate(remaining, 1):
        try:
            if is_domestic_filer(entry["cik"]):
                kept[ticker] = {
                    "cik": entry["cik"],
                    "name": entry["name"],  # raw, unmodified SEC name - never overwritten
                    "display_name": normalize_name(entry["name"]),
                }
            else:
                excluded.add(ticker)
        except requests.RequestException:
            # Leave it out of both kept and excluded, so it's neither
            # wrongly dropped nor wrongly kept - a rerun will retry it
            # since it won't show up in already_done.
            failures += 1

        if i % 50 == 0 or i == len(remaining):
            with open(OUT_PATH, "w", encoding="utf-8") as f:
                json.dump({"kept": kept, "excluded": sorted(excluded)}, f, indent=2)
            print(f"[{i}/{len(remaining)}] checked, kept so far: {len(kept)}", flush=True)

        time.sleep(RATE_LIMIT_DELAY)

    print(f"\ndone. kept {len(kept)} domestic 10-K/10-Q filers, excluded {len(excluded)}, {failures} fetch failures (retry by rerunning).")
    print(f"saved to {OUT_PATH}")


if __name__ == "__main__":
    main()
