"""Given a resolved company (ticker, entry) and the year/quarter/
variables already extracted from the user's question, fetches the real
XBRL candidate list for each needed statement and runs the QLoRA
adapter to pick the matching tag(s) for each variable - the exact
prompt format qlora_adapter/prompt_format.py defines (CLEAR_LABELS,
STATEMENT_BY_VARIABLE, make_json_prompt are imported from there
directly, not redefined here, so this always matches whatever the
adapter was actually trained on).
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

import requests
import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "xbrl_pipeline"))
sys.path.insert(0, str(REPO_ROOT / "qlora_adapter"))

from collect_annual_xbrl import collect_annual_candidates  # noqa: E402
from collect_quarterly_xbrl import collect_quarterly_candidates  # noqa: E402
from xbrl_method import list_available_quarters  # noqa: E402
from prompt_format import CLEAR_LABELS, STATEMENT_BY_VARIABLE, make_json_prompt  # noqa: E402

MODEL_NAME = "Qwen/Qwen2.5-3B-Instruct"
ADAPTER_PATH = REPO_ROOT / "qlora_adapter" / "adapter"
PER_SHARE_VARS = {"EPS Diluted"}

_model = None
_tokenizer = None


def _load_model():
    """Loads the base model + v2 adapter once, on first use, and reuses
    it for every later call in this process."""
    global _model, _tokenizer  # noqa: PLW0603
    if _model is not None:
        return _model, _tokenizer

    _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
    )
    base_model = AutoModelForCausalLM.from_pretrained(MODEL_NAME, quantization_config=bnb_config, device_map={"": 0})
    _model = PeftModel.from_pretrained(base_model, str(ADAPTER_PATH))
    _model.eval()
    return _model, _tokenizer


def _generate_json(prompt, pattern=r"\[.*?\]"):
    model, tokenizer = _load_model()
    chat_text = tokenizer.apply_chat_template(
        [{"role": "user", "content": prompt}], tokenize=False, add_generation_prompt=True,
    )
    inputs = tokenizer(chat_text, return_tensors="pt").to(model.device)
    with torch.no_grad():
        output_ids = model.generate(
            **inputs, max_new_tokens=128, do_sample=False, pad_token_id=tokenizer.pad_token_id,
        )
    generated = tokenizer.decode(output_ids[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    match = re.search(pattern, generated, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


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


def resolve_value(selected_labels, value_for_label):
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
    return total


def get_candidates(ticker, cik, statement, year, quarter):
    """quarter is "FY", "Q1", "Q2", or "Q3" - SEC has no standalone Q4
    filing, only the cumulative annual report and the three 10-Qs.
    Returns (candidate_labels, value_for_label, period_end), or (None,
    None, None) if no real filed period exists for that year/quarter,
    or the filing itself is ambiguous (more than one real filed date
    for the same year/quarter slot)."""
    cik_int = int(cik)
    periods = list_available_quarters(cik, target_year=year)
    period_end = periods.get(str(year), {}).get(quarter)
    if not period_end or isinstance(period_end, list):
        return None, None, None

    if quarter == "FY":
        rows = collect_annual_candidates(
            ticker, cik_int, fiscal_year_ends={period_end}, statements={statement}, raise_on_error=True,
        )
    else:
        rows = collect_quarterly_candidates(
            ticker, cik_int, quarter_ends={period_end}, statements={statement}, raise_on_error=True,
        )

    candidates = rows[0][statement] if rows else []
    value_for_label = dict(candidates)
    return list(value_for_label), value_for_label, period_end


def match_variables(ticker, cik, variables, year, quarter):
    """For each requested variable, fetches the real candidates for its
    statement (once per statement, shared across variables that need
    it) and runs the adapter to pick the matching tag(s).

    Returns a list of dicts, one per variable:
      {"variable", "selected", "value", "period_end"} on success (value
        is None when the model's answer is empty, unreadable, or names
        a label that isn't in the candidates)
      {"variable", "error", "scope"} if the whole period ("period") or
        the variable's whole statement ("statement", with "statement"
        set) had a problem. result_lines() writes those once, not once
        per variable.
    """
    if quarter == "Q4":
        # SEC has no standalone Q4 filing - only the three 10-Qs (Q1-Q3)
        # and the annual 10-K, whose period end date is the same date a
        # Q4 filing would have used. Reported plainly rather than
        # guessed at: substituting the FY total would be flat-out wrong
        # for a flow variable (Revenue, Net Income, ...), since FY is
        # ~4 quarters' worth, not just Q4's.
        return [
            {
                "variable": variable, "scope": "period",
                "error": "There is no standalone Q4 filing. Q4's period end date is the same as the fiscal year end.",
            }
            for variable in variables
        ]

    variables_by_statement = {}
    for variable in variables:
        statement = STATEMENT_BY_VARIABLE[variable]
        variables_by_statement.setdefault(statement, []).append(variable)

    results = []
    for statement, statement_variables in variables_by_statement.items():
        try:
            candidate_labels, value_for_label, period_end = get_candidates(ticker, cik, statement, year, quarter)
        except requests.exceptions.RequestException:
            for variable in statement_variables:
                results.append({
                    "variable": variable, "scope": "statement", "statement": statement,
                    "error": "SEC didn't respond, please try again.",
                })
            continue
        if candidate_labels is None:
            if int(year) >= date.today().year:
                not_found_error = f"{ticker} has not filed {quarter} {year} with the SEC yet."
            else:
                not_found_error = f"No real filed period found for {ticker} {quarter} {year}."
            for variable in statement_variables:
                results.append({"variable": variable, "scope": "period", "error": not_found_error})
            continue

        for variable in statement_variables:
            if not candidate_labels:
                results.append({
                    "variable": variable, "scope": "statement", "statement": statement,
                    "error": "No real filing data found.",
                })
                continue
            prompt = make_json_prompt(candidate_labels, CLEAR_LABELS[variable])
            selected = _generate_json(prompt) or []
            value = resolve_value(selected, value_for_label)
            results.append({
                "variable": variable, "selected": selected, "value": value, "period_end": period_end,
            })

    return results


def result_lines(results, format_value):
    """Turns match_variables' results into display lines. A problem
    covering the whole period or a whole statement is written once, not
    once per variable."""
    lines = []
    seen = set()
    for r in results:
        scope = r.get("scope")
        if scope == "period":
            key, line = ("period", r["error"]), r["error"]
        elif scope == "statement":
            label = r["statement"].replace("_", " ").capitalize()
            key, line = (r["statement"], r["error"]), f"{label}: {r['error']}"
        else:
            key, line = None, f"{r['variable']}: {format_value(r['value'], r['variable'])}"
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        lines.append(line)
    return lines
