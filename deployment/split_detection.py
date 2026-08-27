"""Detects stock splits for a ticker:
1. Get its diluted share count history from SEC, one value per quarter/year.
2. Walk that history period by period, in real fiscal order.
3. Flag any point where the value jumps to the next by a clean split-like ratio.
"""
import datetime

import requests

HEADERS = {"User-Agent": "Research research@example.com"}
CONCEPT = "WeightedAverageNumberOfDilutedSharesOutstanding"

PERIOD_ORDER = ["Q1", "Q2", "Q3", "FY"]

# Minimum split ratio that a split can happen with.
MIN_SPLIT_RATIO = 1.25


def _is_clean_ratio(ratio):
    """Checks the ratio of split to find potential ratio."""
    return ratio > MIN_SPLIT_RATIO or ratio < 1 / MIN_SPLIT_RATIO


def _next_period(fy, fp):
    """fy = fiscal year (e.g. 2021), fp = fiscal period (one of "Q1","Q2","Q3","FY").
    Returns the (fy, fp) that comes right after the one given."""
    i = PERIOD_ORDER.index(fp)
    if i == len(PERIOD_ORDER) - 1:
        return fy + 1, PERIOD_ORDER[0]
    return fy, PERIOD_ORDER[i + 1]


def get_period_series(cik_int, concept=CONCEPT, unit="shares", since=None):
    """1. Pad cik_int to SEC's required 10-digit CIK format.
    2. Send the request to SEC to get this company's full share-count
       history.
    3. Go through every fact one at a time, reading out its start, end,
       filed, fy, and fp.
    4. Check that fact is actually usable:
       - skip it if start, end, filed, fy, or fp is missing/invalid
       - skip it if end is before 2020-01-01
       - skip it if since is set (the quarter the user selected in the
         app) and end is before since
       - skip it if its length isn't a real single quarter (~90 days)
         or a real single full year (~365 days), i.e. check it's
         singular, not a cumulative year-to-date figure
    5. Save whatever survives into series, keyed by (fy, fp).

    Example one entry of series: series[(2021, "Q1")] =
    (79623000, "2021-03-31", "2021-05-06")."""

    cik_padded = str(cik_int).zfill(10)
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik_padded}.json"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    tag_data = data.get("facts", {}).get("us-gaap", {}).get(concept)
    if not tag_data:
        return {}

    series = {}
    for fact in tag_data.get("units", {}).get(unit, []):
        start, end, filed = fact.get("start"), fact.get("end"), fact.get("filed")
        fy, fp = fact.get("fy"), fact.get("fp")
        if not start or not end or not filed or fy is None or fp not in PERIOD_ORDER:
            continue
        if end < "2020-01-01":
            continue
        if since and end < since:
            continue
        days = (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(start)).days
        if fp == "FY":
            if not (350 <= days <= 380):
                continue
        elif not (80 <= days <= 100):
            continue
        series[(fy, fp)] = (fact["val"], end, filed)
    return series


def detect_splits(ticker, cik_int, concept=CONCEPT, unit="shares", since=None):
    """1. Get series from get_period_series (optionally starting from since).
       Example: series[(2021, "Q3")] = (79909000, "2021-09-30", "2021-11-02"),
       series[(2021, "FY")] = (319238000, "2021-12-31", "2022-02-15").

    2. Go through every (fy, fp) entry one at a time as prev_val/prev_end/prev_filed
       (e.g. (fy, fp) = (2021, "Q3"), prev_val = 79909000, prev_end = "2021-09-30",
       prev_filed = "2021-11-02"):
       - find its real next period with _next_period, skip if that period
         isn't in series (e.g. _next_period(2021, "Q3") = (2021, "FY"), which is in series)
       - look up the next period's own value as next_val/next_end/next_filed
         (e.g. next_val = 319238000, next_end = "2021-12-31", next_filed = "2022-02-15")
       - skip if prev_val or next_val is missing, or they're equal (e.g. they
         differ here, so this doesn't skip)

    3. Compute ratio = next_val / prev_val (e.g. 319238000 / 79909000 = 3.995).

    4. If _is_clean_ratio(ratio), append a result with the ticker, the
       ratio, both periods' values/dates, and search_start (prev_end)
       (e.g. 3.995 > MIN_SPLIT_RATIO (1.25), so _is_clean_ratio(3.995)
       is True and this candidate gets appended).

    5. Example result appended to results:
       {"ticker": "ANET", "quarter_end": "2021-12-31", "ratio": 3.995,
        "prev_value": 79909000, "prev_filed": "2021-11-02",
        "next_value": 319238000, "next_filed": "2022-02-15",
        "search_start": "2021-09-30"}."""
    
    series = get_period_series(cik_int, concept, unit, since=since)

    results = []
    for (fy, fp), (prev_val, prev_end, prev_filed) in series.items():
        next_key = _next_period(fy, fp)
        if next_key not in series:
            continue
        next_val, next_end, next_filed = series[next_key]
        if not prev_val or not next_val or prev_val == next_val:
            continue

        ratio = next_val / prev_val
        if _is_clean_ratio(ratio):
            results.append({
                "ticker": ticker, "quarter_end": next_end, "ratio": round(ratio, 3),
                "prev_value": prev_val, "prev_filed": prev_filed,
                "next_value": next_val, "next_filed": next_filed,
                "search_start": prev_end,
            })
    return results


if __name__ == "__main__":
    for ticker, cik in {"RGTI": 1838359, "PANW": 1327567, "LRCX": 707549, "ANET": 1596532}.items():
        print(f"=== {ticker} ===")
        for r in detect_splits(ticker, cik):
            print(f"  {r}")
