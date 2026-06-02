import sqlite3

from src.collectors.financial_variables import FINANCIAL_VARIABLES
from src.collectors.tags import get_filing_periods, find_value
from src.collectors.gemini_fallback import gemini_fallback
from src.storage.database import COLUMN_MAP, upsert_annual

N_ANNUAL = 5


def _year_in_db(db_path, ticker, fiscal_year_end):
    """Return True if this (ticker, fiscal_year_end) row is already saved in the DB."""
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM financial_data_annual "
            "WHERE ticker = ? AND fiscal_year_end = ? AND collected_date IS NOT NULL",
            (ticker, fiscal_year_end),
        ).fetchone()
    return row is not None


def _sum_tags(ns, tags, form, fp, period_end):
    """Sum multiple XBRL tags for a period. Returns None if any single tag is missing."""
    total = 0.0
    for tag in tags:
        value, _, _, _ = find_value(ns, [tag], form, fp, period_end)
        if value is None:
            return None
        total += value
    return total


def extract_annual(ns, ticker, cik, db_path=None, collected_date=None):
    """
    Collect annual (10-K) financial data for a company.

    Gets the last 5 fiscal year-end dates from SEC filing metadata,
    then for each year:
      - Skips the year if a row already exists in the DB (from a previous partial run).
      - Looks up every variable in FINANCIAL_VARIABLES via standard tag matching.
      - Fills remaining gaps using aggregation rules (combining two component tags).
      - Calls Gemini once for any variables still not found.
      - Saves the year's row to the DB immediately before moving to the next year,
        so a failure on a later year does not lose the data already collected.

    Returns a list of dicts for the years that were actually processed this run:
    {
        "ticker":          ...,
        "fiscal_year_end": ...,
        "data":            { db_column_name: value, ... }
    }
    """
    periods = get_filing_periods(cik, "10-K", N_ANNUAL)
    rows = []

    for period_end in periods:
        # Skip years that were already saved in a previous (possibly partial) run
        if db_path and _year_in_db(db_path, ticker, period_end):
            continue

        data    = {}
        missing = []

        for line_item, tag_list in FINANCIAL_VARIABLES.items():
            col = COLUMN_MAP[line_item]
            value, _unit, _tag, _filed = find_value(ns, tag_list, "10-K", "FY", period_end)
            data[col] = value
            if value is None:
                missing.append(line_item)

        # ── Aggregation rules: fill gaps by combining two component tags ──────

        # SG&A = Selling + G&A (companies that split them, e.g. Google)
        if "SG&A" in missing:
            v = _sum_tags(ns, ["SellingAndMarketingExpense", "GeneralAndAdministrativeExpense"], "10-K", "FY", period_end)
            if v is not None:
                data[COLUMN_MAP["SG&A"]] = v
                missing.remove("SG&A")

        # SG&A = G&A alone (companies with no separate selling line, e.g. biotechs, banks)
        if "SG&A" in missing and "SellingAndMarketingExpense" not in ns:
            v, _, _, _ = find_value(ns, ["GeneralAndAdministrativeExpense"], "10-K", "FY", period_end)
            if v is not None:
                data[COLUMN_MAP["SG&A"]] = v
                missing.remove("SG&A")

        # Pre-tax Income = domestic + foreign split (multinationals, e.g. McDonald's)
        if "Pre-tax Income" in missing:
            v = _sum_tags(ns, [
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic",
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesForeign",
            ], "10-K", "FY", period_end)
            if v is not None:
                data[COLUMN_MAP["Pre-tax Income"]] = v
                missing.remove("Pre-tax Income")

        # Total Liabilities = current + non-current (when the combined tag is absent)
        if "Total Liabilities" in missing:
            v = _sum_tags(ns, ["LiabilitiesCurrent", "LiabilitiesNoncurrent"], "10-K", "FY", period_end)
            if v is not None:
                data[COLUMN_MAP["Total Liabilities"]] = v
                missing.remove("Total Liabilities")

        # ── Accounting identity rules: derive from already-found values ─────────
        # Use values already in data{} from XBRL extraction above.
        # Running here (before Gemini) avoids wasting quota on simple math.

        # Gross Profit = Revenue - Cost of Revenue
        if "Gross Profit" in missing:
            rev  = data.get(COLUMN_MAP["Revenue"])
            cogs = data.get(COLUMN_MAP["Cost of Revenue"])
            if rev is not None and cogs is not None:
                data[COLUMN_MAP["Gross Profit"]] = rev - cogs
                missing.remove("Gross Profit")

        # Cost of Revenue = Revenue - Gross Profit (when Gross Profit is directly tagged)
        if "Cost of Revenue" in missing:
            rev = data.get(COLUMN_MAP["Revenue"])
            gp  = data.get(COLUMN_MAP["Gross Profit"])
            if rev is not None and gp is not None:
                data[COLUMN_MAP["Cost of Revenue"]] = rev - gp
                missing.remove("Cost of Revenue")

        # Pre-tax Income = Net Income + Income Tax
        if "Pre-tax Income" in missing:
            net = data.get(COLUMN_MAP["Net Income"])
            tax = data.get(COLUMN_MAP["Income Tax"])
            if net is not None and tax is not None:
                data[COLUMN_MAP["Pre-tax Income"]] = net + tax
                missing.remove("Pre-tax Income")

        # Total Liabilities = Total Assets - Equity
        if "Total Liabilities" in missing:
            assets = data.get(COLUMN_MAP["Total Assets"])
            equity = data.get(COLUMN_MAP["Equity"])
            if assets is not None and equity is not None:
                derived = assets - equity
                if derived >= 0:
                    data[COLUMN_MAP["Total Liabilities"]] = derived
                    missing.remove("Total Liabilities")

        # ─────────────────────────────────────────────────────────────────────

        if missing:
            fallback = gemini_fallback(missing, ns, ticker, "10-K", "FY", period_end)
            for line_item in missing:
                if fallback.get(line_item) is not None:
                    data[COLUMN_MAP[line_item]] = fallback[line_item]

        # Save immediately — if a later year raises an exception this year is not lost
        if db_path:
            upsert_annual(db_path, ticker, period_end, data, collected_date=collected_date)

        rows.append({
            "ticker":          ticker,
            "fiscal_year_end": period_end,
            "data":            data,
        })

    return rows


