import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).parent.parent.parent / "config" / ".env", override=True)

_AUDIT_LOG = Path(__file__).parent.parent.parent / "logs" / "audit.jsonl"
_BASE_URL  = os.environ.get("AZURE_DEEPSEEK_V4_ENDPOINT", "").strip().rstrip("/")
_MODEL     = "DeepSeek-V4-Flash"
_API_KEY   = "AZURE_DEEPSEEK_V4_API_KEY"

VARIABLES = [
    "Revenue", "Cost of Revenue", "Gross Profit", "R&D", "SG&A",
    "Operating Income", "Interest Expense", "Pre-tax Income", "Income Tax", "Net Income",
    "EPS Basic", "EPS Diluted", "Shares Basic", "Shares Diluted",
    "Cash", "Accounts Receivable", "Inventory", "Goodwill",
    "Current Assets", "Total Assets", "Current Liabilities", "Total Debt",
    "Total Liabilities", "Equity",
    "Operating CF", "CapEx", "Depreciation", "Stock-Based Comp",
    "Stock Buybacks", "Dividends Paid",
]

_NOTES = {
    "Revenue":          "Consolidated total only — never a segment or product line.",
    "SG&A":             "If shown as separate Selling + G&A lines, sum them.",
    "Interest Expense": "Return as a positive number.",
    "EPS Basic":        "Per-share amount — do not scale to millions.",
    "EPS Diluted":      "Per-share amount — do not scale to millions.",
    "Shares Basic":     "Weighted-average basic shares outstanding. Apply the same unit scaling as the table (thousands → ÷1000, actual count → ÷1000000). Report in millions of shares.",
    "Shares Diluted":   "Weighted-average diluted shares outstanding. Same unit scaling rule. Report in millions of shares.",
    "Total Debt":       "Sum ONLY interest-bearing financial obligations: short-term borrowings + commercial paper + current portion of long-term debt + long-term debt + finance lease obligations. EXCLUDE operating lease liabilities (right-of-use liabilities) — these are not debt.",
    "CapEx":            "Return as a positive number.",
    "Stock Buybacks":   "Return as a positive number.",
    "Dividends Paid":   "Return as a positive number.",
}


def _build_var_lines():
    """Build the variable list for the prompt, attaching notes where defined."""
    lines = []
    for v in VARIABLES:
        note = _NOTES.get(v)
        lines.append(f"  - {v}: {note}" if note else f"  - {v}")
    return "\n".join(lines)


def _build_response_template():
    """Build the JSON skeleton the model must fill in with value and source for each variable."""
    lines = []
    for i, v in enumerate(VARIABLES):
        comma = "," if i < len(VARIABLES) - 1 else ""
        lines.append(f'      "{v}": {{"value": null, "source": null}}{comma}')
    return "\n".join(lines)


_VAR_LINES         = _build_var_lines()
_RESPONSE_TEMPLATE = _build_response_template()

_CLIENT = None


def _get_client():
    """Create the Azure OpenAI client once and reuse it for all calls."""
    global _CLIENT
    if _CLIENT is None:
        api_key = os.environ.get(_API_KEY)
        if not api_key:
            raise RuntimeError(f"{_API_KEY} not set in config/.env")
        _CLIENT = OpenAI(api_key=api_key, base_url=_BASE_URL)
    return _CLIENT


def _call_api(client, prompt):
    """Send the prompt to the model, retrying on rate limit and server errors."""
    retries = 0

    while True:
        try:
            return client.chat.completions.create(
                model=_MODEL,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0,
            )
        except Exception as exc:
            code = getattr(exc, "status_code", None)
            if code not in (429, 500, 502, 503) or retries >= 5:
                raise
            retries += 1
            print(f"\n  Error {code}, retry {retries}/5, waiting 30s...")
            time.sleep(30)


_AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)


def _log(entry):
    """Append one extracted year's values and sources to the audit log."""
    with _AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def extract_from_filing(tables, ticker):
    """Send the three filing tables to the model and return extracted financial data by year."""
    if not _BASE_URL:
        raise RuntimeError("AZURE_DEEPSEEK_V4_ENDPOINT not set in config/.env")

    income   = tables.get("income_statement", "(not available)")
    balance  = tables.get("balance_sheet",    "(not available)")
    cashflow = tables.get("cash_flow",        "(not available)")

    prompt = f"""You are an expert accountant extracting financial data from SEC 10-K filings for {ticker}.
You know this company, its industry, and how it reports its financials. Use that knowledge throughout.

The three tables below are taken directly from the official SEC EDGAR filing.
Each table shows 2-3 fiscal years of data. You must extract ALL years shown.

=== INCOME STATEMENT ===
{income}

=== BALANCE SHEET ===
{balance}

=== CASH FLOW STATEMENT ===
{cashflow}

VARIABLES TO EXTRACT (for every fiscal year shown):
{_VAR_LINES}

RULES:
1. Use only the correct source table for each variable:
   - Revenue, Cost of Revenue, Gross Profit, R&D, SG&A, Operating Income, Interest Expense,
     Pre-tax Income, Income Tax, Net Income, EPS Basic, EPS Diluted,
     Shares Basic, Shares Diluted → INCOME STATEMENT only
   - Cash, Accounts Receivable, Inventory, Goodwill, Current Assets, Total Assets,
     Current Liabilities, Total Debt, Total Liabilities, Equity → BALANCE SHEET only
   - Operating CF, CapEx, Depreciation, Stock-Based Comp, Stock Buybacks,
     Dividends Paid → CASH FLOW STATEMENT only
2. Extract every fiscal year shown in the tables — do not skip any year. Use only values from
   that year's column — never read from a comparison year shown alongside the target year.
3. Always use the consolidated total line — never a segment, product line, or geography breakdown.
   For gross amounts (Interest Expense, CapEx, Stock Buybacks, Dividends Paid), only extract from
   a standalone line — never from a combined or net line that bundles multiple items together.
4. Check the table header for the unit. Dollar amounts and share counts have separate unit labels —
   "shares in Millions" applies ONLY to share counts, not to dollar values.
   Dollar scaling is only indicated by "$ in Millions", "$ in Thousands", "$ in Billions" etc.
   - If header says "$ in Millions": copy dollar values exactly as shown.
   - If header says "$ in Thousands": divide dollar values by 1,000.
   - If no dollar unit label (or header only mentions share units): divide dollar values by 1,000,000.
   Always report dollar amounts in millions.
5. Parentheses mean negative — convert them: "(1,234)" → -1234.
   Exception: variables noted as "Return as a positive number" must always be positive.
   Return plain integers or decimals — no $ signs, no commas.
   Example: "$ 416,161" → 416161    |    "(1,234)" → -1234    |    "6.08" → 6.08
   If a cell shows "—" or is blank, return null.
6. If a variable requires summing components (e.g. Total Debt = short-term debt + long-term debt),
   sum them.
7. Use your knowledge of {ticker} and its industry to find each variable. Industry-specific or
   company-specific labels for the same financial measurement are acceptable — extract them and
   record the actual label as the source. Return null only if the concept genuinely does not exist
   in this company's financials. Never assign the same source line to two different variables —
   if a line is already used for one variable in your answer, it cannot also answer another.
8. fiscal_year_end: convert the column header date to YYYY-MM-DD format.
   Example: "Sep. 27, 2025" → "2025-09-27"  |  "December 31, 2023" → "2023-12-31"
   source: write the exact line item label(s) from the table. If you summed multiple lines,
   list them separated by " + ".
   Example: "Total net revenue"  |  "Short-term borrowings + Current portion of long-term debt + Long-term debt"

Return ONLY a valid JSON object with this exact structure — one object per fiscal year:
{{
  "years": [
    {{
      "fiscal_year_end": "YYYY-MM-DD",
{_RESPONSE_TEMPLATE}
    }}
  ]
}}"""

    response = _call_api(_get_client(), prompt)
    time.sleep(4)  # stay under 20 RPM Azure limit
    years    = json.loads(response.choices[0].message.content).get("years", [])

    for year in years:
        entry = {"ticker": ticker, "fiscal_year_end": year.get("fiscal_year_end"), "tables": tables}
        for var in VARIABLES:
            item = year.get(var, {})
            if isinstance(item, dict):
                entry[var] = {"value": item.get("value"), "source": item.get("source")}
            else:
                entry[var] = {"value": item, "source": None}
        _log(entry)

    return years
