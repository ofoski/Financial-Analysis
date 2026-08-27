"""First step of the pipeline: before any financial data can be
collected, two things need to be known. Which company (its SEC CIK
number, via get_cik_map), and, within one of its filings, which page is
the income statement, which is the balance sheet, and which is the cash
flow statement (via find_statement_files). Everything else in
xbrl_method builds on top of these two lookups.
"""
import time
import xml.etree.ElementTree as ET

import requests

HEADERS = {"User-Agent": "financial-analysis research@example.com"}
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"


def get_cik_map():
    """Downloads SEC's full ticker to CIK mapping, for every public
    company. A CIK is the ID number SEC uses internally for a company,
    needed for every other request in this pipeline.

    Example: {"MCHP": {"cik": "0000827054", "name": "MICROCHIP TECHNOLOGY INC"}}
    """
    resp = requests.get(TICKERS_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    result = {}
    for v in resp.json().values():
        ticker = v["ticker"].upper()
        result[ticker] = {"cik": str(v["cik_str"]).zfill(10), "name": v.get("title", "")}
    return result


def find_statement_files(cik_int, accession):
    """Every filing lists its own report pages in a file called
    FilingSummary.xml, each with a title and a category. This reads
    that list and returns which page is which statement.

    Real example, MCHP's 2026 Q1 10-Q:
    {"balance_sheet": "R2.htm", "cash_flow": "R6.htm",
     "income_candidates": ["R4.htm", "R5.htm"]}

    income_candidates is a list, not a single page, because more than
    one page can have an income-statement-like title in the same filing
    (here, R5.htm is really "Statement of Comprehensive Income", not the
    real income statement). The caller checks each candidate's actual
    content to pick the right one.
    """
    url = f"{ARCHIVES_BASE}/{cik_int}/{accession}/FilingSummary.xml"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    time.sleep(0.5)

    tree = ET.fromstring(resp.text)
    found = {}
    is_candidates = []
    seen = set()

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
        is_income = any(w in name for w in ("income", "operations", "earnings", "loss"))
        is_comprehensive_only = "other comprehensive" in name
        if is_income and not is_comprehensive_only and html_file not in seen:
            is_candidates.append(html_file)
            seen.add(html_file)

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
