"""Reads a user's free-text financial question with a general-purpose
model (Qwen2.5-7B-Instruct, no fine-tuning) and pulls out the
structured fields the rest of the pipeline needs: company name,
period type, year, quarter, and which of the 15 trained variables are
being asked about.

A separate model from the one in pipeline.py on purpose: this is a
general language-understanding task (reading a casual question), not
the narrow XBRL tag-selection task the qlora_adapter model was
trained for - the 3B adapter isn't a general instruction-follower
anymore after fine-tuning, so a plain, larger base model handles
extraction instead.
"""
import gc
import json
import re

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"

SYSTEM_PROMPT = (
    "You extract structured information from a user's financial question. "
    "Given the question, return ONLY a JSON object with these fields:\n"
    '  "company": the company name mentioned (as written in the question)\n'
    '  "period_type": either "annual" or "quarterly"\n'
    '  "year": the year as a 4-digit number if stated, else null\n'
    '  "quarter": the quarter number (1-4) if period_type is "quarterly" and stated, else null\n'
    '  "variables": a list of financial variables asked about, using ONLY these exact labels where applicable: '
    '"Revenue", "Cost of Revenue", "Gross Profit", "Operating Income", "Net Income", "EPS Diluted", '
    '"Cash and Cash Equivalents", "Operating Cash Flow", "Capital Expenditures", "Total Assets", '
    '"Total Current Assets", "Total Current Liabilities", "Total Liabilities", "Total Stockholders Equity", "Total Debt"\n\n'
    "Return ONLY the JSON object, no other text."
)

_model = None
_tokenizer = None


def load_model():
    """Loads the extraction model once, on first use, and reuses it for
    every later call in this process."""
    global _model, _tokenizer  # noqa: PLW0603
    if _model is not None:
        return _model, _tokenizer

    _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
    )
    _model = AutoModelForCausalLM.from_pretrained(MODEL_NAME, quantization_config=bnb_config, device_map={"": 0})
    _model.eval()
    return _model, _tokenizer


def unload_model():
    """Frees the extraction model's GPU memory. The 6GB GPU this runs
    on can't hold both this model and the qlora_adapter model at
    once, so the caller unloads this one before pipeline.py loads the
    adapter, and vice versa."""
    global _model, _tokenizer  # noqa: PLW0603
    if _model is None:
        return
    del _model, _tokenizer
    _model, _tokenizer = None, None
    gc.collect()
    torch.cuda.empty_cache()


def extract(question):
    """Returns a dict with "company", "period_type", "year", "quarter",
    and "variables", or None if the model didn't produce valid JSON."""
    model, tokenizer = load_model()
    chat_text = tokenizer.apply_chat_template(
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": question}],
        tokenize=False, add_generation_prompt=True,
    )
    inputs = tokenizer(chat_text, return_tensors="pt").to(model.device)
    with torch.no_grad():
        output_ids = model.generate(
            **inputs, max_new_tokens=200, do_sample=False, pad_token_id=tokenizer.pad_token_id,
        )
    generated = tokenizer.decode(output_ids[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)

    match = re.search(r"\{.*\}", generated, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
