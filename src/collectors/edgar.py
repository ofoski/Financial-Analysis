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
    """Find the income statement, balance sheet, and cash flow HTML files inside a filing."""
    url  = f"{ARCHIVES_BASE}/{cik_int}/{accession}/FilingSummary.xml"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    time.sleep(0.5)

    found = {}
    # Two passes: Statements first, then Uncategorized as fallback (needed for some companies e.g. NVDA)
    for categories in (("Statements",), ("Uncategorized",)):
        for report in ET.fromstring(resp.text).iter("Report"):
            html_file = report.findtext("HtmlFileName", "")
            if not html_file.endswith(".htm"):
                continue
            if report.findtext("MenuCategory", "") not in categories:
                continue

            name = report.findtext("ShortName", "").lower()
            if "parenthetical" in name:
                continue

            is_income           = any(w in name for w in ("income", "operations", "earnings"))
            is_comprehensive    = "comprehensive" in name and "operations" not in name and "earnings" not in name

            if "income_statement" not in found and is_income and not is_comprehensive:
                found["income_statement"] = html_file
            elif "balance_sheet" not in found and ("balance" in name or "financial position" in name):
                found["balance_sheet"] = html_file
            elif "cash_flow" not in found and "cash" in name:
                found["cash_flow"] = html_file

        if len(found) == 3:
            break

    return found


def _fetch_table_text(cik_int, accession, html_file):
    """Download one HTML R-file and return its table as pipe-separated plain text."""
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
    """Return the three financial statement tables for one 10-K filing as plain text."""
    files = _find_statement_files(cik_int, accession)
    if not files:
        raise ValueError("No financial statements found in FilingSummary.xml")

    return {key: _fetch_table_text(cik_int, accession, html_file) for key, html_file in files.items()}
