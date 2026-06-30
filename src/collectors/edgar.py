import time
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

HEADERS         = {"User-Agent": "financial-analysis research@example.com"}
TICKERS_URL     = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{}.json"
ARCHIVES_BASE   = "https://www.sec.gov/Archives/edgar/data"


def get_cik_map():
    """Download SEC ticker→CIK mapping for all public companies."""
    resp = requests.get(TICKERS_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    result = {}
    for v in resp.json().values():
        ticker = v["ticker"].upper()
        result[ticker] = {"cik": str(v["cik_str"]).zfill(10), "name": v.get("title", "")}
    return result


def _parse_10k_filings(block, results):
    """Extract 10-K accession numbers and period dates from a submissions block."""
    for form, accession, period in zip(block.get("form", []), block.get("accessionNumber", []), block.get("reportDate", [])):
        if form == "10-K" and period:
            results.append((accession.replace("-", ""), period))


def get_10k_filings(cik):
    """Return all 10-K filings for a company as [(accession, period_end), ...], newest first."""
    resp = requests.get(SUBMISSIONS_URL.format(cik), headers=HEADERS, timeout=15)
    resp.raise_for_status()
    time.sleep(0.5)

    filings = resp.json().get("filings", {})
    results = []
    _parse_10k_filings(filings.get("recent", {}), results)

    for file_entry in filings.get("files", []):
        if len(results) >= 15:
            break
        r = requests.get("https://data.sec.gov/submissions/" + file_entry["name"], headers=HEADERS, timeout=15)
        r.raise_for_status()
        time.sleep(0.5)
        _parse_10k_filings(r.json(), results)

    return results


def _find_statement_files(cik_int, accession):
    """
    Read FilingSummary.xml and return HTML filenames for the three financial statements.

    Returns a dict with:
      "income_candidates" → list of income statement candidate filenames (in XML order)
      "balance_sheet"     → single filename
      "cash_flow"         → single filename

    For the income statement, multiple candidates are returned because some filings have
    both a real income statement and a supplemental "Comprehensive Income" table with a
    similar name. The caller checks the content of each candidate to pick the right one.

    For balance sheet and cash flow, two passes are made: main financial statement tables
    first, then uncategorized tables as a fallback (some companies tag their tables
    differently in the XML).
    """
    url  = f"{ARCHIVES_BASE}/{cik_int}/{accession}/FilingSummary.xml"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    time.sleep(0.5)

    tree = ET.fromstring(resp.text)
    found = {}
    is_candidates = []
    seen = set()

    # Only look for the income statement inside "Statements" and "Uncategorized" categories.
    # The "Notes" category is skipped because it contains detail tables such as "Income Taxes"
    # whose name contains the word "income" but is not the income statement.
    _IS_CATEGORIES = {"Statements", "Uncategorized"}
    for report in tree.iter("Report"):
        html_file = report.findtext("HtmlFileName", "")
        if not html_file.endswith(".htm"):
            continue
        if report.findtext("MenuCategory", "") not in _IS_CATEGORIES:
            continue
        name = report.findtext("ShortName", "").lower()
        if "parenthetical" in name:
            continue
        is_income              = any(w in name for w in ("income", "operations", "earnings"))
        is_comprehensive_only  = "other comprehensive" in name
        if is_income and not is_comprehensive_only and html_file not in seen:
            is_candidates.append(html_file)
            seen.add(html_file)

    # Balance sheet and cash flow: two-pass (Statements first, Uncategorized fallback)
    for categories in (("Statements",), ("Uncategorized",)):
        for report in tree.iter("Report"):
            html_file = report.findtext("HtmlFileName", "")
            if not html_file.endswith(".htm"):
                continue
            if report.findtext("MenuCategory", "") not in categories:
                continue
            name = report.findtext("ShortName", "").lower()
            if "parenthetical" in name:
                continue
            if "balance_sheet" not in found and ("balance" in name or "financial position" in name):
                found["balance_sheet"] = html_file
            elif "cash_flow" not in found and "cash" in name:
                found["cash_flow"] = html_file
        if "balance_sheet" in found and "cash_flow" in found:
            break

    found["income_candidates"] = is_candidates
    return found


def _fetch_table_text(cik_int, accession, html_file):
    """Download one filing HTML table file from EDGAR and return its content as pipe-separated plain text."""
    url  = f"{ARCHIVES_BASE}/{cik_int}/{accession}/{html_file}"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    time.sleep(0.5)

    table = BeautifulSoup(resp.text, "html.parser").find("table")
    if not table:
        return ""

    lines = []
    for row in table.find_all("tr"):
        cells = [c.get_text(strip=True).replace("\xa0", " ") for c in row.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        if cells:
            lines.append("  |  ".join(cells))
    return "\n".join(lines)


def fetch_filing_tables(cik_int, accession):
    """
    Fetch the income statement, balance sheet, and cash flow tables for one 10-K filing.
    For the income statement, multiple candidates are checked by content to pick the correct one.
    For balance sheet and cash flow, the file is fetched directly by name.
    Returns a dict with keys: income_statement, balance_sheet, cash_flow.
    """
    files = _find_statement_files(cik_int, accession)
    if not files:
        raise ValueError("No financial statements found in FilingSummary.xml")

    result = {}

    # ── Step 1: Income statement ──────────────────────────────────────────────
    # Unlike balance sheet and cash flow, the income statement requires content validation
    # because multiple tables can share "income" in the name. The real income statement
    # and the supplemental "Comprehensive Income" table (which only contains currency and
    # pension adjustments, not revenue) both match by name. So we download each candidate
    # and check the actual content for revenue or cost keywords to identify the correct one.
    # If no candidate passes the check (very rare), use the first one as a last resort.
    _IS_KEYWORDS = ("revenue", "net sales", "sales", "cost of")
    candidates = files.pop("income_candidates", [])
    fallback = None
    for html_file in candidates:
        text = _fetch_table_text(cik_int, accession, html_file)
        if fallback is None:
            fallback = text
        if any(kw in text.lower() for kw in _IS_KEYWORDS):
            result["income_statement"] = text
            break
    if "income_statement" not in result:
        result["income_statement"] = fallback or "(not available)"

    # ── Step 2: Balance sheet and cash flow ──────────────────────────────────
    # These are fetched directly — their names are unique enough that no content
    # validation is needed.
    for key, html_file in files.items():
        result[key] = _fetch_table_text(cik_int, accession, html_file)

    return result
