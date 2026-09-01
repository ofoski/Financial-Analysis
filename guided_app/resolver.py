"""The 9 trained variables and their display names, the fine-tuned
model loader, resolving a company name/ticker to a real (ticker,
entry) pair, and the fetch-and-match pipeline that takes an
already-known (ticker, variables, year, quarter) and matches the real
candidates in that company's filing against each variable, the task
the adapter was actually fine-tuned on.

Reuses the fetch/parse pipeline already maintained elsewhere, rather
than keeping a separate copy here.
"""
import json
import re
import sys
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

sys.path.insert(0, str(Path(__file__).parent.parent / "xbrl_pipeline"))
from collect_annual_xbrl import collect_annual_candidates  # noqa: E402
from collect_quarterly_xbrl import collect_quarterly_candidates  # noqa: E402
from edgar_helpers import get_cik_map  # noqa: E402
from xbrl_method import list_available_quarters  # noqa: E402

MODEL_NAME = "Qwen/Qwen2.5-3B-Instruct"
ADAPTER_PATH = Path(__file__).parent / "adapter"

VARIABLES = [
    "Revenue", "Gross Profit", "Cost of Revenue", "Operating Income",
    "Net Income", "EPS Diluted", "Cash", "Operating CF", "CapEx",
]

VARIABLE_DISPLAY_NAMES = {
    "CapEx": "Capital Expenditure",
    "Operating CF": "Operating Cashflow",
    "EPS Diluted": "Earnings Per Share Diluted",
}


def display_name(variable):
    return VARIABLE_DISPLAY_NAMES.get(variable, variable)

# Which statement each variable comes from, and the exact plain-English
# description the model was fine-tuned on for each - the wording matters,
# since changing it is untested for this fine-tuned adapter.
VARS_BY_STATEMENT = {
    "income_statement": ["Revenue", "Gross Profit", "Cost of Revenue", "Operating Income", "Net Income", "EPS Diluted"],
    "balance_sheet": ["Cash"],
    "cash_flow": ["Operating CF", "CapEx"],
}
CLEAR_LABELS = {
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
PER_SHARE_VARS = {"EPS Diluted"}

_model = None
_tokenizer = None
_cik_map = None


def _load_model():
    """Loads the base model + adapter once, on first use, and reuses it
    for every later call."""
    global _model, _tokenizer  # noqa: PLW0603
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


def _generate_json_from_messages(messages, pattern, max_new_tokens=128):
    """Shared by both LLM calls below: runs the model on a real chat
    (a list of {"role", "content"} turns, not just one merged block of
    text), pulls the first pattern match (a {...} or [...] block) out
    of its response, and parses it as JSON. Returns None if generation
    didn't produce valid JSON."""
    model, tokenizer = _load_model()
    chat_text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(chat_text, return_tensors="pt").to(model.device)
    with torch.no_grad():
        output_ids = model.generate(
            **inputs, max_new_tokens=max_new_tokens, do_sample=False, pad_token_id=tokenizer.pad_token_id,
        )
    generated = tokenizer.decode(output_ids[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)

    match = re.search(pattern, generated, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _generate_json(prompt, pattern):
    """Single-turn version of _generate_json_from_messages, used by the
    matching step (make_match_prompt), which doesn't need a
    multi-turn conversation."""
    return _generate_json_from_messages([{"role": "user", "content": prompt}], pattern)


def _generate_text(prompt, max_new_tokens=40):
    """Like _generate_json, but returns the model's raw text instead of
    parsing it as JSON - used where the model is asked for a plain
    comma-separated list rather than a JSON shape."""
    model, tokenizer = _load_model()
    messages = [{"role": "user", "content": prompt}]
    chat_text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(chat_text, return_tensors="pt").to(model.device)
    with torch.no_grad():
        output_ids = model.generate(
            **inputs, max_new_tokens=max_new_tokens, do_sample=False, pad_token_id=tokenizer.pad_token_id,
        )
    return tokenizer.decode(output_ids[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def make_match_prompt(candidate_labels, label):
    """Same prompt shape the adapter was actually fine-tuned on - only
    the real candidate labels, not their values, since the model just
    needs to pick which label(s) match, not judge by the number."""
    candidates_json = json.dumps(candidate_labels, indent=2)
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


def _split_sign(entry):
    """Splits a selected entry into (sign, label). No prefix defaults to
    addition."""
    if entry.startswith("+ "):
        return 1, entry[2:]
    if entry.startswith("- "):
        return -1, entry[2:]
    if entry.startswith("+"):
        return 1, entry[1:].strip()
    if entry.startswith("-"):
        return -1, entry[1:].strip()
    return 1, entry


def _match_one_value(variable, candidate_labels, value_for_label, existing_results):
    """Gets a variable's resolved value, reusing it from existing_results
    if it was already matched, otherwise matching it now against the
    same already-fetched candidates. Used by the Gross Profit fallback
    below to get Revenue/Cost of Revenue even when the user didn't ask
    for them directly."""
    if variable in existing_results:
        return existing_results[variable].get("value")
    selected = _generate_json(make_match_prompt(candidate_labels, CLEAR_LABELS[variable]), r"\[.*?\]")
    if selected is None:
        return None
    return resolve_value(selected, value_for_label, per_share=(variable in PER_SHARE_VARS))


def resolve_value(selected_labels, value_for_label, per_share=False):
    """Sums (and subtracts, where marked) the value of every selected
    label's matching fact. Returns None if nothing was selected, or a
    selected label doesn't actually exist in the candidates."""
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


def _get_cik_map():
    """Downloads SEC's full ticker -> CIK/name list on first use only,
    then reuses it in memory for the rest of the process's lifetime."""
    global _cik_map  # noqa: PLW0603
    if _cik_map is None:
        _cik_map = get_cik_map()
    return _cik_map


_SUFFIXES = re.compile(
    r"\b(INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|LTD|LLC|PLC|GROUP|HOLDINGS?)\b\.?,?",
    re.IGNORECASE,
)


def _normalize_name(name):
    """Strips punctuation, casing, and common legal suffixes (Inc,
    Corp, Ltd, ...), so "Gitlab Inc." and "GITLAB INC" compare equal."""
    name = _SUFFIXES.sub("", name.upper())
    name = re.sub(r"[^A-Z0-9 ]", " ", name)
    return " ".join(name.split())


def resolve_company(company):
    """Resolves whatever the model extracted - a real ticker if the
    question already used one (e.g. "AAPL"), or a company name
    otherwise (e.g. "Apple Inc.") - to a real (ticker, entry) pair.

    Ticker is tried first, since that's an exact, unambiguous lookup.
    Only if that fails does this fall back to searching SEC's real
    company list by name - not by trusting the model to recall a
    ticker symbol from memory, which turned out to be unreliable even
    for well-known companies (e.g. guessing "ACNT" for Accenture, real
    ticker "ACN"). Name matching, in order: an exact match (after
    normalizing both sides, so "Apple Inc." matches SEC's "APPLE INC"
    once the legal suffix is stripped from both), then a whole-word
    prefix match (a short common name like "Akamai" is the start of
    the real legal name "Akamai Technologies Inc", so this catches it
    directly). No fuzzy/similarity matching here on purpose - real
    testing found character-similarity scoring against SEC's full
    ~10,000-company list lets genuinely unrelated words through just
    because they happen to share several letters with some real
    company (e.g. "banana" matching a company called "Cannae"), a risk
    that doesn't exist for the 9-item variable list, which is small
    enough for fuzzy matching to stay safe. Returns None if nothing
    matches, which should trigger a re-ask rather than a guess."""
    cik_map = _get_cik_map()

    exact = cik_map.get(company.strip().upper())
    if exact:
        return company.strip().upper(), exact

    target = _normalize_name(company)
    normalized_to_ticker = {}
    for ticker, entry in cik_map.items():
        normalized_to_ticker.setdefault(_normalize_name(entry["name"]), ticker)

    if target in normalized_to_ticker:
        ticker = normalized_to_ticker[target]
        return ticker, cik_map[ticker]

    prefix_matches = [name for name in normalized_to_ticker if name.startswith(target + " ")]
    if prefix_matches:
        best = min(prefix_matches, key=len)  # closest to just the base name
        ticker = normalized_to_ticker[best]
        return ticker, cik_map[ticker]

    return None


def resolve_from_fields(ticker, entry, variables, year, quarter):
    """The full fetch-and-match pipeline, once (ticker, entry,
    variables, year, quarter) are already known from the guided,
    step-by-step conversation. Returns a dict with "ok": True and
    "results" (one entry per variable, each either {"variable",
    "selected", "value"} or {"variable", "error"}) on success, or
    "ok": False and "error" if the period couldn't be resolved."""
    cik_int = int(entry["cik"])

    periods = list_available_quarters(entry["cik"])
    year_data = periods.get(str(year), {})
    period_end = year_data.get(quarter)
    if not period_end:
        return {"ok": False, "error": f"No real filed period found for {ticker} {quarter} {year}."}

    # Group the requested variables by statement, so a statement shared
    # by more than one (e.g. Revenue and Gross Profit both need the
    # income statement) is only fetched once.
    variables_by_statement = {}
    for variable in variables:
        statement = next(s for s, vars_ in VARS_BY_STATEMENT.items() if variable in vars_)
        variables_by_statement.setdefault(statement, []).append(variable)

    results = []
    for statement, statement_variables in variables_by_statement.items():
        if quarter == "FY":
            rows = collect_annual_candidates(ticker, cik_int, fiscal_year_ends={period_end}, statements={statement})
        else:
            rows = collect_quarterly_candidates(ticker, cik_int, quarter_ends={period_end}, statements={statement})
        candidates = rows[0][statement] if rows else []
        value_for_label = dict(candidates)
        candidate_labels = list(value_for_label)

        statement_results = {}
        for variable in statement_variables:
            if not candidate_labels:
                statement_results[variable] = {"variable": variable, "error": "No real filing data found for this statement."}
                continue
            selected = _generate_json(make_match_prompt(candidate_labels, CLEAR_LABELS[variable]), r"\[.*?\]")
            if selected is None:
                statement_results[variable] = {"variable": variable, "error": "Model couldn't produce a valid match."}
                continue
            value = resolve_value(selected, value_for_label, per_share=(variable in PER_SHARE_VARS))
            statement_results[variable] = {"variable": variable, "selected": selected, "value": value}

        # Gross Profit isn't always reported as its own line item - when
        # it wasn't found directly, fall back to Revenue minus Cost of
        # Revenue, matching those two against the same candidates even
        # if the user didn't ask for them.
        if "Gross Profit" in statement_variables and statement_results["Gross Profit"].get("value") is None and candidate_labels:
            revenue = _match_one_value("Revenue", candidate_labels, value_for_label, statement_results)
            cost_of_revenue = _match_one_value("Cost of Revenue", candidate_labels, value_for_label, statement_results)
            if revenue is not None and cost_of_revenue is not None:
                statement_results["Gross Profit"] = {
                    "variable": "Gross Profit", "selected": "Revenue - Cost of Revenue",
                    "value": revenue - cost_of_revenue,
                }

        results.extend(statement_results.values())

    return {
        "ok": True, "ticker": ticker, "year": year, "quarter": quarter,
        "period_end": period_end, "results": results,
    }
