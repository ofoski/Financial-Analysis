import requests
from datetime import datetime

# SEC API endpoints used across the project
HEADERS         = {"User-Agent": "financial-analysis research@example.com"}
TICKERS_URL     = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{}.json"
FACTS_URL       = "https://data.sec.gov/api/xbrl/companyfacts/CIK{}.json"

# How many days each quarterly period type should cover.
# Q1 = 3 months, Q2 = 6 months YTD, Q3 = 9 months YTD — as filed in 10-Qs.
_FP_DAYS = {
    "Q1": (75,  105),
    "Q2": (165, 195),
    "Q3": (255, 285),
}


def fetch_cik(ticker):
    """
    Look up the SEC CIK number for a ticker symbol.
    Downloads the full ticker list from SEC and searches for a match.
    Returns the CIK as a 10-digit zero-padded string (e.g. "0000320193").
    """
    resp = requests.get(TICKERS_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    for v in resp.json().values():
        if v["ticker"].upper() == ticker.upper():
            return str(v["cik_str"]).zfill(10)
    raise ValueError(f"Ticker '{ticker}' not found in SEC index")


def fetch_ns(cik):
    """
    Download the XBRL facts for a company from SEC EDGAR and return
    only the us-gaap section, which is where financial statement data lives.
    """
    resp = requests.get(FACTS_URL.format(cik), headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json().get("facts", {}).get("us-gaap", {})


def _collect_periods(block, form, periods, num):
    """Scan one filings block and append matching period-end dates to `periods`."""
    for f, date in zip(block.get("form", []), block.get("reportDate", [])):
        if f == form and date and date not in periods:
            periods.append(date)
        if len(periods) >= num:
            break


def get_filing_periods(cik, form, num):
    """
    Return the last N official period-end dates for a given filing type (e.g. "10-K" or "10-Q").

    The SEC submissions API splits filings into a "recent" block plus paginated
    archive files. Large, active companies (e.g. Alphabet) fill up "recent" with
    8-Ks and proxies quickly, pushing older 10-Ks into the archive. This function
    follows those pagination links so we always get the full history we need.
    """
    resp = requests.get(SUBMISSIONS_URL.format(cik), headers=HEADERS, timeout=15)
    resp.raise_for_status()
    payload = resp.json()

    filings  = payload.get("filings", {})
    periods  = []

    _collect_periods(filings.get("recent", {}), form, periods, num)

    for file_entry in filings.get("files", []):
        if len(periods) >= num:
            break
        url = "https://data.sec.gov/submissions/" + file_entry["name"]
        r   = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        _collect_periods(r.json(), form, periods, num)

    return periods[:num]


def find_value(ns, tag_list, form, fp, period_end):
    """
    Search for a financial value in the XBRL data by trying each tag in order.

    For each tag, it looks for entries that match the given form, fp, and
    period end date. If multiple entries match (e.g. amended filings),
    it picks the most recently filed one.

    For quarterly income/cash-flow items (which have a start date), it also
    checks the period length is correct for that quarter type. This prevents
    accidentally picking up a 6-month slice when looking for a 3-month one.

    Returns (value, unit, xbrl_tag, filed_date), or (None, None, None, None)
    if no matching data was found.
    """
    for tag in tag_list:
        if tag not in ns:
            continue

        for unit, entries in ns[tag].get("units", {}).items():
            matches = []

            for e in entries:
                # Skip if this entry doesn't match the period we're looking for
                if e.get("end") != period_end:
                    continue
                if e.get("form") != form:
                    continue
                if e.get("fp") != fp:
                    continue
                if e.get("val") is None:
                    continue

                # For quarterly flow items, make sure the period length is right
                if form == "10-Q" and fp in _FP_DAYS and "start" in e:
                    lo, hi = _FP_DAYS[fp]
                    days = (datetime.strptime(e["end"], "%Y-%m-%d") - datetime.strptime(e["start"], "%Y-%m-%d")).days
                    if not (lo <= days <= hi):
                        continue

                matches.append(e)

            if not matches:
                continue

            # Pick the most recently filed entry
            best  = max(matches, key=lambda e: e.get("filed", ""))
            raw   = float(best["val"])
            value = raw / 1_000_000 if unit == "USD" else raw
            return value, unit, tag, best.get("filed")

    return None, None, None, None
