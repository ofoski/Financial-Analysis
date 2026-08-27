"""Takes the candidate lists collected by collect_quarterly_xbrl.py and asks
the fine-tuned Qwen2.5-3B-Instruct model (base model + LoRA adapter from
the adapter/ folder next to this file) to match each candidate label
against a plain-English variable description. The model has to match
that description against real, sometimes technical XBRL concept names
(e.g. "CostOfGoodsAndServicesSold (Product)", or a company's own custom
concept like "FinancingInterestExpensesIncludingDivestitures") instead
of a table's own row text. That match quality is exactly what this
script is meant to test.
"""
import json
import re
from pathlib import Path

import spaces
import torch
from collect_quarterly_xbrl import collect_quarterly_candidates
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

MODEL_NAME = "Qwen/Qwen2.5-3B-Instruct"
ADAPTER_PATH = Path(__file__).parent / "adapter"

_model = None
_tokenizer = None


def _load_model():
    """Loads the base model + adapter once, on first use, and reuses it
    for every later call, since loading is slow (a few seconds) but
    generation is fast."""
    global _model, _tokenizer
    if _model is not None:
        return _model, _tokenizer

    _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
    )
    base_model = AutoModelForCausalLM.from_pretrained(MODEL_NAME, quantization_config=bnb_config, device_map="auto")
    _model = PeftModel.from_pretrained(base_model, ADAPTER_PATH)
    _model.eval()
    return _model, _tokenizer

VARS_BY_STATEMENT = {
    "income_statement": [
        "Revenue", "Gross Profit", "Cost of Revenue",
        "Operating Income", "Net Income", "EPS Diluted",
    ],
    "balance_sheet": ["Cash"],
    "cash_flow": ["Operating CF", "CapEx"],
}

def collect_candidates_for_quarter(ticker, cik_int, quarter_end, variables):
    """Collects candidates for one specific quarter, but only from the
    statements variables actually needs, using VARS_BY_STATEMENT to map
    each requested variable back to its statement. If the user only asks
    for "CapEx", only the cash flow statement is fetched, the income
    statement and balance sheet report pages are never looked up at all.
    Uses collect_quarterly_candidates, which fetches the underlying
    filing document once and shares it across whichever statements are
    needed, instead of re-downloading the same filing once per statement.

    Returns {statement: candidates}, one entry per statement actually
    needed, in the same (label, value) shape build_candidates returns.
    """
    needed_statements = {
        statement for statement, statement_vars in VARS_BY_STATEMENT.items()
        if any(v in variables for v in statement_vars)
    }

    rows = collect_quarterly_candidates(ticker, cik_int, quarter_ends={quarter_end}, statements=needed_statements)
    if not rows:
        return {}
    return {statement: rows[0][statement] for statement in needed_statements}


def make_json_prompt(candidates, label):
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


@spaces.GPU
def ask_llm(candidates, label):
    """Asks the fine-tuned model which candidates match label, using the
    exact same prompt format it was trained on. Returns the model's
    answer as a list of strings, empty if generation didn't produce
    valid JSON."""
    model, tokenizer = _load_model()
    prompt = make_json_prompt(candidates, label)
    chat_text = tokenizer.apply_chat_template(
        [{"role": "user", "content": prompt}], tokenize=False, add_generation_prompt=True,
    )
    inputs = tokenizer(chat_text, return_tensors="pt").to(model.device)
    with torch.no_grad():
        output_ids = model.generate(
            **inputs, max_new_tokens=64, do_sample=False, pad_token_id=tokenizer.pad_token_id,
        )
    generated = tokenizer.decode(output_ids[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)

    match = re.search(r"\[.*?\]", generated, re.DOTALL)
    if not match:
        return []
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return []


def _split_sign(entry):
    """Splits a selected entry into (sign, label). No prefix defaults to
    addition. Handles a missing space after the sign too (e.g.
    "-CostOfGoodsAndServicesSold"), since the model doesn't always include
    one."""
    if entry.startswith("+ "):
        return 1, entry[2:]
    if entry.startswith("- "):
        return -1, entry[2:]
    if entry.startswith("+"):
        return 1, entry[1:].strip()
    if entry.startswith("-"):
        return -1, entry[1:].strip()
    return 1, entry


def format_selected(selected_labels):
    """Joins the model's selected entries into one readable string for
    storage/display, always showing an explicit sign."""
    if not selected_labels:
        return None
    if len(selected_labels) == 1:
        return selected_labels[0]
    parts = []
    for entry in selected_labels:
        sign, label = _split_sign(entry)
        parts.append(f"{'+' if sign == 1 else '-'} {label}")
    return " ".join(parts)


def resolve_value(selected_labels, value_for_label, per_share=False):
    """Sums (and subtracts, where marked) the value of every selected
    label's matching XBRL fact, looked up directly from the candidate
    list's own (label, value) pairs -- XBRL facts already carry the value,
    so no row/column parsing is needed here."""
    if not selected_labels:
        return None

    total = 0.0
    for entry in selected_labels:
        sign, label = _split_sign(entry)
        if label not in value_for_label:
            return None
        total += sign * value_for_label[label]

    if not per_share:
        total = total / 1_000_000
    return total


def match_variables(candidates, variables_to_collect=None):
    """Given one filing's candidate list, asks the fine-tuned model to
    match each variable and resolves its value. Returns
    {var: {selected, value}}."""
    clear_labels = {
        "Revenue": "Total Revenue (or Net Sales) -- the top-line amount the company earned from its core business this period",
        "Gross Profit": "Gross Profit (also called Gross Margin) -- only select this if a line item is literally labeled Gross Profit or Gross Margin. Do not construct it by combining Revenue and Cost of Revenue -- if no such line item exists, return [].",
        "Cost of Revenue": "Cost of Revenue (also called Cost of Goods Sold or Cost of Sales) -- the direct cost of producing what was sold",
        "Operating Income": "Operating Income (also called Income from Operations) -- profit from core business operations, before interest and taxes",
        "Net Income": "Net Income (or Net Loss) -- the company's final bottom-line profit or loss for the period",
        "EPS Diluted": "Diluted Earnings Per Share",
        "Cash": "Cash and Cash Equivalents -- exclude restricted cash if a plain, non-restricted line item is available. Only use a combined 'cash and restricted cash' line if no plain cash-only line item exists.",
        "Operating CF": "Net Cash Provided by (or Used in) Operating Activities",
        "CapEx": "Capital Expenditures -- capitalized software development costs, and/or property, plant, and equipment (PP&E) purchases. Either component alone is enough to select -- a company may only report one of the two. This may appear as one combined line item, or as separate lines to be summed. Do not include payments to acquire businesses/M&A, or investments in securities -- those are not Capital Expenditures.",
    }
    per_share_vars = {"EPS Diluted"}

    if variables_to_collect is None:
        variables_to_collect = list(clear_labels)
    value_for_label = dict(candidates)
    candidate_labels = list(value_for_label)

    variables = {}
    for var in variables_to_collect:
        try:
            selected = ask_llm(candidate_labels, clear_labels[var])
        except Exception as exc:  # noqa: BLE001
            print(f"\n  {var}: LLM call failed: {exc}")
            variables[var] = {"selected": None, "value": None}
            continue

        value = resolve_value(selected, value_for_label, per_share=(var in per_share_vars))
        variables[var] = {"selected": format_selected(selected), "value": value}

    if "Gross Profit" in variables and variables["Gross Profit"]["value"] is None:
        revenue = variables.get("Revenue", {}).get("value")
        cost_of_revenue = variables.get("Cost of Revenue", {}).get("value")
        if revenue is not None and cost_of_revenue is not None:
            variables["Gross Profit"] = {
                "selected": "Revenue - Cost of Revenue",
                "value": revenue - cost_of_revenue,
            }

    return variables
