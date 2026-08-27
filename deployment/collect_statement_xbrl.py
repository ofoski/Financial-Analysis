"""For one company's real SEC filing, downloads that filing once and
pulls out its actual financial numbers (label -> value pairs) for the
income statement, balance sheet, and cash flow statement, ready for an
LLM to later match against a plain-English variable like "Revenue" or
"Cash".

This is the one shared engine behind both collect_annual_xbrl.py and
collect_quarterly_xbrl.py, since a 10-K and a 10-Q both work this exact
same way underneath, just against different filing types and period
lengths. Rather than each of those two files repeating the same
fetch/parse logic, they each just tell this file how to find their own
filings and how long a period to look for, and this file does the real
work once, in one place.
"""
from xbrl_method import (
    build_candidates,
    build_context_map,
    fetch_xbrl_soup,
    find_balance_sheet_report,
    find_cash_flow_report,
    find_income_statement_report,
    find_instant_period,
    get_report_concepts,
)

ALL_STATEMENTS = {"income_statement", "balance_sheet", "cash_flow"}


def collect_statement_candidates(
    ticker, cik_int, get_filings, income_period_fn, cash_flow_period_fn,
    period_ends=None, statements=None, default_limit=None,
):
    """Downloads one real filing (it holds every statement's numbers
    together, not split into separate files), then uses a separate
    lookup function to find and pull out just the income statement,
    balance sheet, and/or cash flow statement from it, based on which
    ones are actually needed. Returns one row per filing:
    {ticker, period_end, income_statement, balance_sheet, cash_flow},
    each a list of real (label, value) pairs.

    Parameters:
    - ticker, cik_int: the real company being asked about, coming
      straight from what the user picked in the app.
    - period_ends: the real date(s) the user's year/period selection
      resolved to (e.g. {"2022-09-24"}), also from the user's action.
    - statements: which of the three statements to actually look up (the
      others come back as empty lists), computed from which variables
      the user checked, e.g. checking only "Cash" means
      statements = {"balance_sheet"}.
    - get_filings, income_period_fn, cash_flow_period_fn, default_limit:
      not set by the user at all, these are fixed values hardcoded by
      whichever of the two callers is invoking this function.
      collect_annual_xbrl.py always passes the 10-K filing lookup and
      find_annual_period for both periods; collect_quarterly_xbrl.py
      always passes the 10-Q lookup, find_quarter_period, and
      find_cumulative_period, plus default_limit=3. The balance sheet
      never needs its own period function, it's always
      find_instant_period, since "as of one date" works the same
      whether that date is a quarter-end or a fiscal year-end."""
    
    statements = statements if statements is not None else ALL_STATEMENTS

    filings = get_filings(cik_int)
    if period_ends is not None:
        filings = [f for f in filings if f[1] in period_ends]
    elif default_limit is not None:
        filings = filings[:default_limit]

    rows = []
    for accession, period_end, primary_doc in filings:
        try:
            soup = fetch_xbrl_soup(cik_int, accession, primary_doc)
            contexts = build_context_map(soup)

            income_candidates = []
            if "income_statement" in statements:
                income_report = find_income_statement_report(cik_int, accession)
                income_concepts = get_report_concepts(cik_int, accession, income_report) if income_report else set()
                income_period = income_period_fn(soup, contexts, period_end, income_concepts) if income_report else None
                income_candidates = (
                    build_candidates(soup, contexts, income_period[0], income_period[1], report_concepts=income_concepts)
                    if income_period else []
                )

            balance_candidates = []
            if "balance_sheet" in statements:
                balance_report = find_balance_sheet_report(cik_int, accession)
                balance_concepts = get_report_concepts(cik_int, accession, balance_report) if balance_report else set()
                balance_period = find_instant_period(contexts, period_end) if balance_report else None
                balance_candidates = (
                    build_candidates(soup, contexts, balance_period[0], balance_period[1], report_concepts=balance_concepts)
                    if balance_period else []
                )

            cash_flow_candidates = []
            if "cash_flow" in statements:
                cash_flow_report = find_cash_flow_report(cik_int, accession)
                cash_flow_concepts = get_report_concepts(cik_int, accession, cash_flow_report) if cash_flow_report else set()
                cash_flow_period = cash_flow_period_fn(soup, contexts, period_end, cash_flow_concepts) if cash_flow_report else None
                cash_flow_candidates = (
                    build_candidates(soup, contexts, cash_flow_period[0], cash_flow_period[1], report_concepts=cash_flow_concepts)
                    if cash_flow_period else []
                )
        except Exception as exc:  # noqa: BLE001
            print(f"\n  {ticker} {accession}: fetch failed: {exc}")
            continue

        rows.append({
            "ticker": ticker, "period_end": period_end,
            "income_statement": income_candidates, "balance_sheet": balance_candidates,
            "cash_flow": cash_flow_candidates,
        })

    return rows
