import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai

load_dotenv(Path(__file__).parent.parent.parent / "config" / ".env")

_LOGS_DIR   = Path(__file__).parent.parent.parent / "logs"
_FOUND_LOG  = _LOGS_DIR / "gemini_found.jsonl"
_NULL_LOG   = _LOGS_DIR / "gemini_null.jsonl"

_VARIABLE_DEFINITIONS = {
    "Revenue":             "Total revenue / net sales — all income from primary business operations.",
    "Cost of Revenue":     "Direct cost of goods sold or services delivered. Excludes SG&A and R&D.",
    "Gross Profit":        "Revenue minus Cost of Revenue.",
    "R&D":                 "Research and development expenses.",
    "SG&A":                "Selling, general and administrative expenses.",
    "Operating Income":    "Gross Profit minus operating expenses (R&D, SG&A, etc.).",
    "Interest Expense":    "Interest paid on debt.",
    "Pre-tax Income":      "Income before income taxes.",
    "Income Tax":          "Income tax expense or benefit.",
    "Net Income":          "Bottom-line profit after all expenses and taxes.",
    "EPS Basic":           "Basic earnings per share — per-share amount, NOT in millions.",
    "EPS Diluted":         "Diluted earnings per share — per-share amount, NOT in millions.",
    "Cash":                "Cash and cash equivalents at period end.",
    "Accounts Receivable": "Net trade receivables after allowances.",
    "Inventory":           "Net inventory at period end.",
    "Goodwill":            "Goodwill from acquisitions.",
    "Current Assets":      "Total current assets.",
    "Total Assets":        "Total assets.",
    "Current Liabilities": "Total current liabilities.",
    "Total Debt":          "Short-term + long-term debt + capital leases combined.",
    "Total Liabilities":   "Total liabilities.",
    "Equity":              "Total shareholders equity.",
    "Operating CF":        "Net cash from operating activities.",
    "CapEx":               "Cash paid for property, plant, and equipment.",
    "Depreciation":        "Depreciation, depletion, and amortization.",
    "Stock-Based Comp":    "Non-cash stock-based compensation expense.",
    "Stock Buybacks":      "Cash paid to repurchase common stock.",
    "Dividends Paid":      "Cash dividends paid to shareholders.",
}


def _get_period_tags(ns, form, fp, period_end):
    """Return {tag_name: {"value": ..., "unit": ...}} for every XBRL tag with data for this period."""
    tags = {}
    for tag, tag_data in ns.items():
        for unit, entries in tag_data.get("units", {}).items():
            matches = [
                e for e in entries
                if e.get("end") == period_end
                and e.get("form") == form
                and e.get("fp") == fp
                and e.get("val") is not None
            ]
            if not matches:
                continue
            best  = max(matches, key=lambda e: e.get("filed", ""))
            raw   = float(best["val"])
            value = raw / 1_000_000 if unit == "USD" else raw
            tags[tag] = {"value": value, "unit": unit}
            break
    return tags


def _append_lines(path, lines):
    """Append JSON lines to a log file, creating it and its parent dir if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for obj in lines:
            f.write(json.dumps(obj) + "\n")


def gemini_fallback(missing_variables, ns, ticker, form, fp, period_end):
    """
    Ask Gemini to find values for variables that standard tag matching could not find.

    One API call per fiscal year — all missing variables are batched into a single request.
    Sleeps 15 s after the call to respect Gemini free-tier rate limits.

    Found results  → logs/gemini_found.jsonl
    Null results   → logs/gemini_null.jsonl

    Returns {variable_name: value_or_None}.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {var: None for var in missing_variables}

    available_tags = _get_period_tags(ns, form, fp, period_end)
    if not available_tags:
        return {var: None for var in missing_variables}

    var_lines = "\n".join(
        f"  - {var}: {_VARIABLE_DEFINITIONS.get(var, '')}"
        for var in missing_variables
    )
    tag_lines = "\n".join(
        f"  {tag}: {info['value']:,.4f} {info['unit']}"
        for tag, info in sorted(available_tags.items())
    )

    prompt = f"""You are an accountant analyzing SEC XBRL data for {ticker} ({form}, period ending {period_end}).

MISSING VARIABLES (find these):
{var_lines}

AVAILABLE XBRL TAGS (USD already in millions):
{tag_lines}

RULES:
1. One tag covering the full amount is fine.
2. Summing multiple non-overlapping tags that together equal 100% of the amount is fine.
3. A partial value (one segment, one category, not the total) is never acceptable — return null.
4. If not confident, return null. A wrong value is worse than null.
5. Think like an accountant. Understand what each variable means, not just the tag name.
6. EPS values are per-share — do not scale them.

Return a JSON object. Each key is a variable name. Each value has:
  "value":      number in millions (or per-share for EPS), or null
  "method":     "single_tag", "aggregation", or null
  "tags":       list of tag names used, or []
  "tag_values": dict of {{tag_name: value}} for each tag used (same scale as the tag list above), or {{}} if value is null
  "reasoning":  one sentence explaining why null was returned — only fill this when value is null, otherwise null

Example:
{{
  "Revenue": {{"value": 1234.56, "method": "aggregation", "tags": ["RevenueA", "RevenueB"], "tag_values": {{"RevenueA": 1000.0, "RevenueB": 234.56}}, "reasoning": null}},
  "Inventory": {{"value": null, "method": null, "tags": [], "tag_values": {{}}, "reasoning": "No inventory tags present; company appears to be a pure services business."}}
}}

Respond with ONLY the JSON object."""

    base = {"ticker": ticker, "fiscal_year_end": period_end, "form": form, "fp": fp}

    # Any API error (503 overload, 429 rate limit, network failure, etc.) is
    # re-raised so the caller stops processing this ticker and it is NOT marked
    # as done in progress.json — the next run will retry it cleanly.
    try:
        client   = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=" gemini-2.5-flash",
            contents=prompt,
            config={"response_mime_type": "application/json", "temperature": 0},
        )
    except Exception:
        time.sleep(15)
        raise

    time.sleep(15)  # pace calls: free tier allows 10 RPM / 250 RPD

    parsed     = json.loads(response.text)
    result     = {}
    found_rows = []
    null_rows  = []

    for var in missing_variables:
        item       = parsed.get(var) or {}
        value      = item.get("value")
        method     = item.get("method")
        tags       = item.get("tags") or []
        tag_values = item.get("tag_values") or {}
        reasoning  = item.get("reasoning")

        if not isinstance(value, (int, float)):
            value = None

        result[var] = value

        if value is not None:
            found_rows.append({**base, "variable": var, "value": value,
                               "method": method, "tags_used": tags,
                               "tag_values": tag_values})
        else:
            null_rows.append({**base, "variable": var, "reasoning": reasoning})

    _append_lines(_FOUND_LOG, found_rows)
    _append_lines(_NULL_LOG,  null_rows)
    return result
