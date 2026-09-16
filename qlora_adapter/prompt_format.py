"""The prompt format the qlora_adapter model was trained on: which
statement each of the 15 variables comes from, the plain-language
description of each variable shown to the model, and the exact prompt
template itself.

Split out from build_training_data_v2.py so that serving code (the
Gradio apps under filing_assistant/ and filing_variable_lookup/) can
depend on just this - the format the adapter actually expects - without
depending on the training-data-build script itself. Both
build_training_data_v2.py and the serving apps import from here, so
there's exactly one place these definitions live.

CLEAR_LABELS covers all 15 variables. The first 9 are copied verbatim
from xbrl_method/xbrl_llm_match.py's clear_labels, since that wording
is already validated (matches the deployed adapter's behavior) --
except Gross Profit, which is updated: the old wording forbids
deriving Gross Profit from Revenue - Cost of Revenue, but the verified
training data does exactly that in over half of its Gross Profit
entries (118 DERIVED vs 76 real GrossProfit tag, annual), so keeping
the old wording would directly contradict the training data itself.
"""
import json

STATEMENT_BY_VARIABLE = {
    'Revenue': 'income_statement', 'Cost of Revenue': 'income_statement', 'Gross Profit': 'income_statement',
    'Operating Income': 'income_statement', 'Net Income': 'income_statement', 'EPS Diluted': 'income_statement',
    'Operating Cash Flow': 'cash_flow', 'Capital Expenditures': 'cash_flow',
    'Total Assets': 'balance_sheet', 'Total Current Assets': 'balance_sheet', 'Total Current Liabilities': 'balance_sheet',
    'Total Liabilities': 'balance_sheet', 'Total Stockholders Equity': 'balance_sheet',
    'Cash and Cash Equivalents': 'balance_sheet', 'Total Debt': 'balance_sheet',
}

CLEAR_LABELS = {
    # --- carried over verbatim from xbrl_method/xbrl_llm_match.py (already validated) ---
    "Revenue": "Total Revenue (or Net Sales) -- the top-line amount the company earned from its core business this period",
    "Cost of Revenue": "Cost of Revenue (also called Cost of Goods Sold or Cost of Sales) -- the direct cost of producing what was sold",
    "Operating Income": "Operating Income (also called Income from Operations) -- profit from core business operations, before interest and taxes",
    "Net Income": "Net Income (or Net Loss) -- the company's final bottom-line profit or loss for the period",
    "EPS Diluted": "Diluted Earnings Per Share",
    "Cash and Cash Equivalents": "Cash and Cash Equivalents -- exclude restricted cash if a plain, non-restricted line item is available. Only use a combined 'cash and restricted cash' line if no plain cash-only line item exists.",
    "Operating Cash Flow": "Net Cash Provided by (or Used in) Operating Activities",
    "Capital Expenditures": "Capital Expenditures -- capitalized software development costs, and/or property, plant, and equipment (PP&E) purchases. Either component alone is enough to select -- a company may only report one of the two. This may appear as one combined line item, or as separate lines to be summed. Do not include payments to acquire businesses/M&A, or investments in securities -- those are not Capital Expenditures.",
    # --- updated: old wording forbade deriving Gross Profit, our verified data derives it often ---
    "Gross Profit": "Gross Profit (also called Gross Margin) -- prefer a line item literally labeled Gross Profit or Gross Margin if one exists. If none exists, it may be derived by subtracting Cost of Revenue from Revenue, prefixing '+ ' on Revenue and '- ' on Cost of Revenue.",
    # --- new: the 6 balance-sheet variables our dataset adds ---
    "Total Assets": "Total Assets -- the company's total resources reported on the balance sheet",
    "Total Current Assets": "Total Current Assets -- assets expected to be converted to cash or used within one year. If the balance sheet is unclassified (does not separate current from noncurrent), return [].",
    "Total Current Liabilities": "Total Current Liabilities -- obligations due within one year. If the balance sheet is unclassified (does not separate current from noncurrent), return [].",
    "Total Liabilities": "Total Liabilities -- the company's total obligations. If no line item is literally labeled Liabilities, it may be derived from the balance sheet identity: Total Assets (or Total Liabilities and Stockholders Equity) minus Total Stockholders Equity (including any noncontrolling interest), prefixing '+ ' on the asset/total side and '- ' on each equity component subtracted.",
    "Total Stockholders Equity": "Total Stockholders Equity -- the parent company's own equity, excluding any noncontrolling (minority) interest. If only a combined figure including noncontrolling interest is reported, along with a separate noncontrolling interest line, derive it by subtracting the noncontrolling interest, prefixing '+ ' and '- ' accordingly.",
    "Total Debt": "Total Debt -- the company's total interest-bearing borrowings (short-term and long-term debt, and finance lease liabilities where reported as debt). This is very often reported as separate current and noncurrent (or short-term and long-term) lines that must be summed together. Exclude operating lease liabilities, accounts payable, and other non-debt obligations. If no debt is reported at all, return [].",
}

assert set(CLEAR_LABELS) == set(STATEMENT_BY_VARIABLE), "CLEAR_LABELS and STATEMENT_BY_VARIABLE must cover the same 15 variables"  # noqa: S101


def make_json_prompt(candidates, label):
    """Identical to make_json_prompt() in xbrl_method/xbrl_llm_match.py."""
    candidates_json = json.dumps(candidates, indent=2)
    return (
        "Here is a JSON array of line item labels from a financial statement in a SEC filing:\n\n"
        f"{candidates_json}\n\n"
        f"Which line item(s) represent: {label}?\n"
        "Return the exact matching string(s), copied verbatim from the array above, as a JSON array.\n\n"
        "If a single line matches, return an array with just that one item, no sign prefix needed.\n\n"
        "If the value is derived by combining multiple line items -- summed together, or a subtotal "
        "that needs some lines added and others subtracted -- prefix each item with a literal '+ ' or "
        "'- ' to say whether it should be added or subtracted, e.g. '+ Revenues', '- Cost of goods sold'.\n\n"
        "If none match, return []."
    )
