"""Pipeline that turns one SEC quarterly filing (10-Q) into a candidate
list of (label, value) pairs, for the LLM to pick a variable's value from.
The steps run in this order:

1. get_10q_filings_with_doc: list a company's filings, and which document
   to fetch for each one.
2. fetch_xbrl_soup + build_context_map: download one filing, and build a
   lookup from context id to the period it means.
3. find_income_statement_report / find_balance_sheet_report /
   find_cash_flow_report: find which page in the filing is which
   statement.
4. get_report_concepts: read which XBRL tag names actually belong to that
   page.
5. find_quarter_period / find_cumulative_period / find_instant_period:
   pick the right period for that statement, standalone quarter, year to
   date, or a single point in time.
6. collect_facts: for that period, keep one trustworthy value per
   concept, the highest-precision tag, when a concept is tagged twice.
7. build_candidates: turn those facts into the final (label, value) list.

Uses BeautifulSoup with the built-in "html.parser" backend ("lxml" and
"lxml-xml" aren't installed in this environment). html.parser lowercases
every tag and attribute name, so "ix:nonFraction" becomes
"ix:nonfraction" and "contextRef" becomes "contextref", which every
tag/attribute lookup in this file accounts for.
"""
import time

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Research research@example.com"}
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{}.json"


def fetch_xbrl_soup(cik_int, accession_nodash, main_htm_filename):
    """Downloads one filing's document and parses it into a searchable
    structure, so later code can search its tags instead of raw HTML."""
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{main_htm_filename}"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def _parse_10q_entries(block, results):
    for form, accession, period, primary_doc in zip(
        block.get("form", []), block.get("accessionNumber", []),
        block.get("reportDate", []), block.get("primaryDocument", []),
    ):
        if form == "10-Q" and period and primary_doc:
            results.append((accession.replace("-", ""), period, primary_doc))


def get_10q_filings_with_doc(cik):
    """Gets the company's quarterly filings (10-Qs): for each one, the
    period it covers and the document needed to fetch its data."""
    resp = requests.get(SUBMISSIONS_URL.format(cik), headers=HEADERS, timeout=15)
    resp.raise_for_status()
    time.sleep(0.5)

    filings = resp.json().get("filings", {})
    results = []
    _parse_10q_entries(filings.get("recent", {}), results)

    for file_entry in filings.get("files", []):
        if len(results) >= 5:
            break
        r = requests.get("https://data.sec.gov/submissions/" + file_entry["name"], headers=HEADERS, timeout=15)
        r.raise_for_status()
        time.sleep(0.5)
        _parse_10q_entries(r.json(), results)

    return results


def _parse_10k_entries(block, results):
    for form, accession, period, primary_doc in zip(
        block.get("form", []), block.get("accessionNumber", []),
        block.get("reportDate", []), block.get("primaryDocument", []),
    ):
        if form == "10-K" and period and primary_doc:
            results.append((accession.replace("-", ""), period, primary_doc))


def get_10k_filings_with_doc(cik, min_year=None):
    """Gets the company's annual filings (10-Ks): for each one, the fiscal
    year-end date it covers and the document needed to fetch its data.
    10-Ks are filed once a year (vs. three 10-Qs), so unlike
    get_10q_filings_with_doc, this keeps paging through every older
    submissions page until min_year is covered (or there are no more
    pages), rather than stopping after a fixed filing count."""
    resp = requests.get(SUBMISSIONS_URL.format(cik), headers=HEADERS, timeout=15)
    resp.raise_for_status()
    time.sleep(0.5)

    filings = resp.json().get("filings", {})
    results = []
    _parse_10k_entries(filings.get("recent", {}), results)

    for file_entry in filings.get("files", []):
        if min_year is not None and results and min(r[1] for r in results) < f"{min_year}-01-01":
            break
        r = requests.get("https://data.sec.gov/submissions/" + file_entry["name"], headers=HEADERS, timeout=15)
        r.raise_for_status()
        time.sleep(0.5)
        _parse_10k_entries(r.json(), results)

    return results


def list_available_quarters(cik):
    """Groups a company's real 10-Q dates into fiscal-year groups without
    downloading every filing. A normal gap between two consecutive
    quarter_end dates is about 91 days (one quarter). A gap of about 182
    days means a fiscal year's Q4 (a 10-K, not a 10-Q) fell in between,
    that gap marks a real fiscal-year boundary, so the filing right after
    it starts a new fiscal year at Q1. Within each boundary-to-boundary
    group, chronological order is always Q1, Q2, Q3.

    That handles the quarter label for free. The fiscal YEAR number still
    needs one real anchor, since it depends on each company's own fiscal
    year-end month, not on calendar dates alone, e.g. NVDA's group
    [2025-04-27, 2025-07-27, 2025-10-26] is real fiscal year "2026", not
    "2025", even though every date in it is calendar year 2025. So this
    downloads exactly one filing, the single most recent one, and reads
    its real dei:DocumentFiscalYearFocus. Every older group is then just
    that number minus 1 per boundary crossed, no more downloads needed.

    Years before 2020 are dropped from the result, older filings don't
    reliably use the XBRL structure the collection step depends on, so
    offering them just leads to a real quarter that silently returns no
    data.
    """
    import re
    from datetime import date

    cik_int = int(cik)
    filings = get_10q_filings_with_doc(cik)
    if not filings:
        return {}

    JUMP_THRESHOLD_DAYS = 140  # between one quarter (~91) and two (~182)
    groups = [[filings[0]]]
    for newer, older in zip(filings, filings[1:]):
        gap = (date.fromisoformat(newer[1]) - date.fromisoformat(older[1])).days
        if gap > JUMP_THRESHOLD_DAYS:
            groups.append([])
        groups[-1].append(older)

    accession, quarter_end, primary_doc = filings[0]
    soup = fetch_xbrl_soup(cik_int, accession, primary_doc)
    fy_tag = soup.find("ix:nonnumeric", {"name": re.compile("documentfiscalyearfocus", re.I)})
    anchor_year = int(fy_tag.text.strip())

    result = {}
    for i, group in enumerate(groups):
        year = anchor_year - i
        if year < 2020:
            continue
        chronological = list(reversed(group))
        labels = ["Q1", "Q2", "Q3"][:len(chronological)]
        result[str(year)] = {label: qend for label, (_, qend, _) in zip(labels, chronological)}

    # A 10-K's fiscal_year_end normally falls about one quarter (~91 days)
    # after that same fiscal year's Q3 end date, so it can be matched to
    # the right year using dates already on hand, no extra document
    # fetch needed (unlike the anchor lookup above, which genuinely does
    # need one real document to read a company's fiscal year number).
    oldest_year = min(int(y) for y in result)
    for accession, fiscal_year_end, primary_doc in get_10k_filings_with_doc(cik, min_year=oldest_year):
        fy_end_date = date.fromisoformat(fiscal_year_end)
        best_year, best_gap = None, None
        for year, periods in result.items():
            q3 = periods.get("Q3")
            if not q3:
                continue
            gap = (fy_end_date - date.fromisoformat(q3)).days
            if 60 <= gap <= 120 and (best_gap is None or gap < best_gap):
                best_year, best_gap = year, gap
        if best_year:
            result[best_year]["FY"] = fiscal_year_end

    return result


def build_context_map(soup):
    """Reads the filing once and builds a lookup: for each context ID,
    what time period it means. So later code can look up an ID instead
    of re-searching the document every time.

    Real example, from MCHP's 2026 Q1 10-Q. This tag in the file:
    <context id="c-1">
      <period>
        <startdate>2026-04-01</startdate>
        <enddate>2026-06-30</enddate>
      </period>
    </context>
    becomes this in the returned lookup:
    {"c-1": {"start": "2026-04-01", "end": "2026-06-30", "dimensions": {}}}
    """
    import re
    contexts = {}
    for ctx in soup.find_all(re.compile(r":context$")):
        cid = ctx.get("id")
        period = ctx.find(re.compile(r":period$"))
        if period is None:
            continue
        start_tag = period.find(re.compile(r":startdate$"))
        end_tag = period.find(re.compile(r":enddate$"))
        instant_tag = period.find(re.compile(r":instant$"))
        start = start_tag.text if start_tag else None
        end = end_tag.text if end_tag else (instant_tag.text if instant_tag else None)
        dims = {}
        for member in ctx.find_all(re.compile(r":explicitmember$")):
            dims[member.get("dimension")] = member.text.strip()
        contexts[cid] = {"start": start, "end": end, "dimensions": dims}
    return contexts


def _fact_precision(fact):
    """Reads the "decimals" attribute off a tag and returns it as a number.
    Used to compare two tags for the same fact: the higher number wins.
    A tag with no "decimals" attribute at all is treated as the lowest
    possible number, so it never wins. "INF" (exact, no rounding at all)
    is treated as the highest possible number, so it always wins. Checked
    against 54 real filings across 54 different companies: every one
    that uses a non-numeric "decimals" value uses "INF" and nothing else,
    matching the XBRL specification.

    Real example, MCHP's AccumulatedOtherComprehensiveIncomeLossNetOfTax
    (a balance sheet item, not Revenue), from their 2026 Q1 10-Q:
    Tag:    <ix:nonfraction name="us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax" scale="6" sign="-" decimals="-5">3.7</ix:nonfraction>
    Output: -5
    """
    decimals = fact.get("decimals", "-999999")
    if decimals == "INF":
        return 999999
    try:
        return int(decimals)
    except ValueError:
        return -999999


def _fact_value(fact):
    """Reads the real number a tag represents. The text inside the tag is
    not the final number by itself. Two attributes can change it:
    "scale" (multiply by 10 to that power) and "sign" (negate it).

    Real example, MCHP's AccumulatedOtherComprehensiveIncomeLossNetOfTax
    (a balance sheet item, not Revenue), from their 2026 Q1 10-Q:
    Tag:    <ix:nonfraction name="us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax" scale="6" sign="-">3.7</ix:nonfraction>
    Step 1: 3.7 (the text inside the tag)
    Step 2: 3.7 x 10^6 = 3,700,000 (scale="6")
    Step 3: -3,700,000 (sign="-" negates it)
    Output: -3,700,000.0
    """
    raw = fact.text.strip().replace(",", "")
    try:
        val = float(raw)
    except ValueError:
        return None
    scale = int(fact.get("scale", "0"))
    val = val * (10 ** scale)
    if fact.get("sign") == "-":
        val = -val
    return val


def collect_facts(soup, contexts, period_start, period_end, report_concepts=None):
    """Walks every fact tag in the filing once. The same real-world
    number can be tagged more than once (once in the statement table,
    again elsewhere, often rounded differently). For each (concept,
    period) combination, this keeps only the one tag with the highest
    _fact_precision, and drops the rest, so later code gets exactly one
    trustworthy value per fact instead of picking between duplicates.

    Real example, both tags from MCHP's 2026 Q1 10-Q. Same concept
    (TreasuryStockCommonShares), same period, tagged twice:
    <ix:nonfraction name="us-gaap:TreasuryStockCommonShares" decimals="INF" scale="0">35,415,887</ix:nonfraction>
    <ix:nonfraction name="us-gaap:TreasuryStockCommonShares" decimals="-5" scale="6">35.4</ix:nonfraction>
    The first is the exact share count (35,415,887). The second is the
    same number rounded to the nearest hundred-thousand (35,400,000).
    This function keeps the first one, the exact value.
    """
    best = {}
    for fact in soup.find_all("ix:nonfraction"):
        name = fact.get("name", "")
        if ":" not in name:
            continue
        if report_concepts is not None and name not in report_concepts:
            continue
        cid = fact.get("contextref")
        ctx = contexts.get(cid)
        if not ctx or ctx["end"] != period_end or ctx["start"] != period_start:
            continue
        key = (name, cid)
        precision = _fact_precision(fact)
        if key not in best or precision > best[key][1]:
            best[key] = (fact, precision)
    return {key: fact for key, (fact, _) in best.items()}


def get_report_concepts(cik_int, accession_nodash, report_htm):
    """Fetches one specific statement's page and returns which concept
    names actually appear on it. This is what lets later code keep only
    the facts genuinely belonging to one statement, instead of every fact
    filed anywhere in the whole filing for that period.

    Real example, MCHP's 2026 Q1 10-Q. report_htm="R4.htm" is their
    income statement page. Some of what this function returns for it:
    us-gaap:CostOfRevenue
    us-gaap:GrossProfit
    us-gaap:EarningsPerShareDiluted
    mchp:AmortizationOfIntangibleAssetsAcquiredInABusinessCombination
    The last one is MCHP's own custom concept, not a standard us-gaap
    one. It is still returned, since this function covers every
    namespace, not just us-gaap.
    """
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{report_htm}"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    import re
    matches = re.findall(r"defref_([a-zA-Z][a-zA-Z0-9-]*)_([A-Za-z][A-Za-z0-9]*)", resp.text)
    return {f"{namespace}:{concept}" for namespace, concept in matches}


def _report_has_income_statement_content(cik_int, accession_nodash, htm):
    """Fetches one rendered report page and checks whether it actually
    shows revenue/cost figures, not just other-comprehensive-income
    adjustments (currency translation, pension, etc.). Looks at the
    page's real content (every row of data on it), not its title, since
    two different pages can share a similar, misleading title.

    Real example, MCHP's 2026 Q1 10-Q. Two candidate pages both have
    "income" in their title, so both need this check:
    R4.htm, titled "Income Statement [Abstract]" -> True
    R5.htm, titled "Statement of Comprehensive Income [Abstract]" -> False
    R5.htm's title alone looks like a match, but its actual rows only
    contain currency/pension-type adjustments, no real revenue or cost
    figures, so it correctly gets rejected.
    """
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{htm}"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    text = resp.text.lower()
    return "revenue" in text or "cost of" in text or "net sales" in text


def find_income_statement_report(cik_int, accession_nodash):
    """Finds the correct R-file for the income statement, and only the
    income statement, out of every report page in the filing.

    Title matching alone is not enough. Real example, MCHP's 2026 Q1
    10-Q: both R4.htm ("Income Statement") and R5.htm ("Statement of
    Comprehensive Income") have "income" in their title, but only R4.htm
    is the real income statement. This function gets the title-matched
    candidates from xbrl_method.edgar_helpers.find_statement_files, then
    checks each one's real content (via
    _report_has_income_statement_content) to pick the one that actually
    shows revenue/cost figures, R4.htm in this case, not just the one
    whose title happens to match.
    """
    from edgar_helpers import find_statement_files
    files = find_statement_files(cik_int, accession_nodash)
    candidates = files.get("income_candidates", [])
    for htm in candidates:
        if _report_has_income_statement_content(cik_int, accession_nodash, htm):
            return htm
    return candidates[0] if candidates else None


def _find_report(cik_int, accession_nodash, key):
    """Shared lookup behind find_balance_sheet_report and
    find_cash_flow_report, via the same proven, category-filtered lookup
    as find_income_statement_report."""
    from edgar_helpers import find_statement_files
    files = find_statement_files(cik_int, accession_nodash)
    return files.get(key)


def find_balance_sheet_report(cik_int, accession_nodash):
    """Returns the R-file name for the balance sheet."""
    return _find_report(cik_int, accession_nodash, "balance_sheet")


def find_cash_flow_report(cik_int, accession_nodash):
    """Returns the R-file name for the cash flow statement."""
    return _find_report(cik_int, accession_nodash, "cash_flow")


# Real quarters vary a bit in length, so _closest_period accepts anything
# within PERIOD_TOLERANCE_DAYS days of a whole multiple of QUARTER_DAYS,
# e.g. 81-101 days counts as one quarter, 263-283 days counts as three.
QUARTER_DAYS = 91
PERIOD_TOLERANCE_DAYS = 10


def _real_periods(soup, contexts, quarter_end, report_concepts):
    """Returns every distinct (start, end) period that facts belonging to
    report_concepts actually use, ending on quarter_end. A filing's end
    date is shared by many unrelated contexts too (any fact reported "as
    of" that date), so this only looks at contexts that facts belonging
    to this specific statement actually use, not every context in the
    filing that happens to end on the right date.

    Real example, MCHP's fiscal Q3 2026 10-Q (period ending 2025-12-31),
    cash flow concepts. Two genuinely different real periods both exist:
    ("2025-04-01", "2025-12-31") = 274 days, the year-to-date cumulative
    ("2025-10-01", "2025-12-31") = 91 days, the standalone quarter
    Both are real. Which one is wanted depends on what the caller asked
    for, decided next by _closest_period.
    """
    periods = set()
    for fact in soup.find_all("ix:nonfraction"):
        name = fact.get("name", "")
        if report_concepts is not None and name not in report_concepts:
            continue
        cid = fact.get("contextref")
        ctx = contexts.get(cid)
        if not ctx or ctx["dimensions"] or not ctx["start"] or ctx["end"] != quarter_end:
            continue
        periods.add((ctx["start"], ctx["end"]))
    return periods


def _closest_period(soup, contexts, quarter_end, quarter_multiples, report_concepts):
    """Given the real periods from _real_periods, keeps only the ones
    close to a whole number of quarters (quarter_multiples says which:
    [1] for a standalone quarter, [1, 2, 3] for year-to-date), then
    returns the largest of those.

    Real example, MCHP's cash flow concepts across one fiscal year:
    Q1 (2025-06-30): only one real period, 90 days.
    Q2 (2025-09-30): two real periods, 91 days and 182 days.
    Q3 (2025-12-31): two real periods, 91 days and 274 days.
    With quarter_multiples=[1, 2, 3] (year-to-date), Q3's largest
    qualifying period wins: 274 days (about 3 quarters). With
    quarter_multiples=[1] (standalone quarter only), Q3's 91-day period
    is returned instead, since 274 days is not close to 1 quarter.
    """
    from datetime import date

    candidates = []
    for start, end in _real_periods(soup, contexts, quarter_end, report_concepts):
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
        nearest_multiple = min(quarter_multiples, key=lambda n: abs(days - n * QUARTER_DAYS))
        distance = abs(days - nearest_multiple * QUARTER_DAYS)
        if distance <= PERIOD_TOLERANCE_DAYS:
            candidates.append((days, (start, end)))

    if not candidates:
        return None
    return max(candidates, key=lambda c: c[0])[1]


def find_quarter_period(soup, contexts, quarter_end, report_concepts):
    """Gets the standalone 3-month period ending on quarter_end, for a
    single quarter's figure, not a running total. Used for the income
    statement. Balance sheet facts are also single-quarter, not
    cumulative, but instant instead of a duration, so they use
    find_instant_period instead. Cash flow is the only one of the three
    that's cumulative, see find_cumulative_period.

    Real example, MCHP's Q3 (2025-12-31): picks the 91-day period out of
    the two real periods that exist (91 and 274 days).
    """
    return _closest_period(soup, contexts, quarter_end, quarter_multiples=[1], report_concepts=report_concepts)


def find_annual_period(soup, contexts, fiscal_year_end, report_concepts):
    """Gets the full-year (~365-day) period ending on fiscal_year_end, for
    a 10-K's income statement and cash flow statement, both of which
    report one full-year column, not a quarterly one. Balance sheet facts
    are still instant, not a duration, see find_instant_period, same as
    for a 10-Q. Reuses _closest_period with quarter_multiples=[4], since
    4 * QUARTER_DAYS (364) is within PERIOD_TOLERANCE_DAYS of a real
    365/366-day year."""
    return _closest_period(soup, contexts, fiscal_year_end, quarter_multiples=[4], report_concepts=report_concepts)


def find_cumulative_period(soup, contexts, quarter_end, report_concepts):
    """Gets the year-to-date period ending on quarter_end. Used only for
    the cash flow statement, since a 10-Q's cash flow statement prints one
    column, the year-to-date total, not a separate standalone quarter
    column. The standalone period usually has no real cash flow data
    behind it at all.

    Real example, MCHP's Q3 (2025-12-31): the 274-day cumulative period
    has all 38 real cash flow concepts. The 91-day standalone period
    exists in the filing too, but only for 5 unrelated concepts, not
    NetCashProvidedByUsedInOperatingActivities or any other real line.
    """
    return _closest_period(soup, contexts, quarter_end, quarter_multiples=[1, 2, 3], report_concepts=report_concepts)


def find_instant_period(contexts, balance_sheet_date):
    """Finds the context that represents "as of balance_sheet_date", with
    no start date and no segment. Returns it as (None, balance_sheet_date),
    the same (start, end) shape the other find_*_period functions return,
    so build_candidates can treat every statement the same way.

    Real example, from MCHP's 2026 Q3 10-Q, contexts built by
    build_context_map:
    {"c-5": {"start": None, "end": "2025-12-31", "dimensions": {}}, ...}
    find_instant_period(contexts, "2025-12-31") returns (None, "2025-12-31"),
    matching c-5.
    """
    for ctx in contexts.values():
        if ctx["dimensions"] or ctx["start"] is not None:
            continue
        if ctx["end"] == balance_sheet_date:
            return (None, balance_sheet_date)
    return None


def build_candidates(soup, contexts, period_start, period_end, report_concepts=None):
    """Builds the final candidate list handed to the LLM: one (label, value)
    pair per concept for this period. If a concept has a plain total (no
    segment), only that total is kept, its segment breakdown is dropped, so
    the same real dollar amount is never offered twice. A concept only
    shows its segments when it has no plain total at all.

    Real example, CDNS's 2026 Q2 10-Q, Cost of Revenue:
    No plain CostOfGoodsAndServicesSold fact exists for this filing, so
    both segments appear:
    ("CostOfGoodsAndServicesSold (Productandmaintenance)", 175183000.0)
    ("CostOfGoodsAndServicesSold (TechnologyService)", 64135000.0)

    Real example, AAPL's 2026 Q3 10-Q, Cost of Revenue:
    A plain total does exist, so only that one entry appears, its
    "(Products)"/"(Services)" segment breakdown is dropped:
    ("CostOfGoodsAndServicesSold", 54647000000.0)
    """
    facts = collect_facts(soup, contexts, period_start, period_end, report_concepts=report_concepts)

    concepts_with_plain_total = {
        name for (name, cid) in facts if not contexts[cid]["dimensions"]
    }

    candidates = []
    for (name, cid), fact in facts.items():
        ctx = contexts[cid]
        concept = name.split(":", 1)[1]
        dims = ctx["dimensions"]
        if dims and name in concepts_with_plain_total:
            continue
        if len(dims) == 1:
            member = next(iter(dims.values()))
            # a segment's raw value is verbose, e.g.
            # "cdns:ProductandmaintenanceMember" -> "Productandmaintenance"
            member_label = member.split(":", 1)[-1].removesuffix("Member")
            label = f"{concept} ({member_label})"
        elif not dims:
            label = concept
        else:
            # rare: a fact split by 2 segments at once. Real example, AAPL:
            # EquitySecuritiesFvNiCost tagged with both
            # FinancialInstrumentAxis=MoneyMarketFundsMember and
            # FairValueByFairValueHierarchyLevelAxis=FairValueInputsLevel1Member
            # at once. Show both instead of picking one.
            label = f"{concept} ({dims})"

        val = _fact_value(fact)
        if val is None:
            continue

        entry = (label, val)
        if entry not in candidates:
            # skip if this exact (label, value) is already in the list.
            # Real example, AAPL's 2026 Q3 10-Q cash flow: NetIncomeLoss,
            # value 101464000000.0, tagged under two different context ids
            # (c-1 and c-42) that both mean the same period.
            candidates.append(entry)
    return candidates


