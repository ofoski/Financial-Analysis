import json
import sqlite3

from src.collectors.sector_variables import get_variables
from src.collectors.tags import get_filing_periods, find_value
from src.collectors.gemini_fallback import gemini_fallback
from src.storage.database import COLUMN_MAP, upsert_annual

N_ANNUAL = 5

# Columns where a negative XBRL value is always a sign-convention filing error.
# These represent cash outflows or expense magnitudes that are positive by definition.
ALWAYS_POSITIVE = {"interest_expense", "capex", "stock_buybacks", "dividends_paid"}


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


def _write_audit(audit_path, record):
    """Append one JSON record to the audit file (one line per ticker/year)."""
    with open(audit_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def extract_annual(ns, ticker, cik, db_path=None, collected_date=None, sector=None, audit_path=None):
    """
    Collect annual (10-K) financial data for a company.

    Gets the last 5 fiscal year-end dates from SEC filing metadata,
    then for each year:
      - Skips the year if a row already exists in the DB (from a previous partial run).
      - Looks up every variable in the sector-appropriate FINANCIAL_VARIABLES via tag matching.
      - Fills remaining gaps using aggregation rules (combining two component tags).
      - Calls Gemini once for any variables still not found.
      - Saves the year's row to the DB immediately before moving to the next year,
        so a failure on a later year does not lose the data already collected.

    The `sector` parameter selects the right variable set (e.g. Real Estate and Financials
    use a reduced set that omits Cost of Revenue, Gross Profit, and R&D, which do not
    apply to those sectors). Defaults to the standard set when sector is None or unknown.

    Returns a list of dicts for the years that were actually processed this run:
    {
        "ticker":          ...,
        "fiscal_year_end": ...,
        "data":            { db_column_name: value, ... }
    }
    """
    variables = get_variables(sector)

    periods = get_filing_periods(cik, "10-K", N_ANNUAL)
    rows = []

    for period_end in periods:
        # Skip years that were already saved in a previous (possibly partial) run
        if db_path and _year_in_db(db_path, ticker, period_end):
            continue

        data    = {}
        missing = []
        audit   = {}   # variable -> {tag, value, source} for this year

        for line_item, tag_list in variables.items():
            col = COLUMN_MAP[line_item]
            value, _unit, tag, _filed = find_value(ns, tag_list, "10-K", "FY", period_end)
            if value is not None and col in ALWAYS_POSITIVE and value < 0:
                value = abs(value)
            data[col] = value
            if value is None:
                missing.append(line_item)
            else:
                audit[line_item] = {"tag": tag, "value": value, "source": "xbrl"}

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

        # Gross Profit = Operating Income + R&D + SG&A
        # Applies when the income statement structure is: GP - R&D - SG&A = Operating Income
        if "Gross Profit" in missing:
            op_inc = data.get(COLUMN_MAP["Operating Income"])
            rd     = data.get(COLUMN_MAP["R&D"])
            sga    = data.get(COLUMN_MAP["SG&A"])
            if op_inc is not None and rd is not None and sga is not None:
                derived_gp = op_inc + rd + sga
                if derived_gp >= 0:
                    data[COLUMN_MAP["Gross Profit"]] = derived_gp
                    missing.remove("Gross Profit")

        # Cost of Revenue = Revenue - Gross Profit (when Gross Profit is directly tagged)
        if "Cost of Revenue" in missing:
            rev = data.get(COLUMN_MAP["Revenue"])
            gp  = data.get(COLUMN_MAP["Gross Profit"])
            if rev is not None and gp is not None:
                derived = rev - gp
                if derived >= 0:
                    data[COLUMN_MAP["Cost of Revenue"]] = derived
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

        if audit_path:
            _write_audit(audit_path, {
                "ticker":          ticker,
                "fiscal_year_end": period_end,
                "sector":          sector,
                "variables":       audit,
            })

        rows.append({
            "ticker":          ticker,
            "fiscal_year_end": period_end,
            "data":            data,
        })

    return rows


