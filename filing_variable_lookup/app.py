"""Selection-based alternative to filing_assistant's chat interface: the
company, year, quarter, and variable(s) are all picked directly from
dropdowns/checkboxes instead of parsed from a free-text question, so
this mode needs no extraction model at all - only pipeline.py (real
filing data + the fine-tuned adapter), reused directly from
filing_assistant rather than duplicated here.

The company dropdown is the full real SEC company list (~10,000
companies, the same source resolver.py's resolve_company() uses via
edgar_helpers.get_cik_map()) - not limited to any project-specific
file. Since the dropdown forces an exact, unambiguous real company
name, there's no name-matching ambiguity to resolve here the way
resolve_company() has to handle for free-text questions - the
ticker/CIK is looked up directly from the same map.

A separate app/folder from filing_assistant on purpose, so the finished
chat interface there stays untouched.
"""
import json
import sys
import threading
import time
from pathlib import Path

import gradio as gr

# CPython's default GIL switch interval (5ms) can make a lightweight
# spinner thread visibly stutter while another thread holds the GIL
# for long stretches doing GPU/model work. Lowering it makes the
# interpreter hand control between threads more readily, so the
# spinner keeps updating on schedule even while the worker is busy.
sys.setswitchinterval(0.001)

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "filing_assistant"))
sys.path.insert(0, str(REPO_ROOT / "xbrl_pipeline"))

import pipeline  # noqa: E402
from edgar_helpers import get_cik_map  # noqa: E402

COMPANY_CACHE_PATH = Path(__file__).parent / "companies_cache.json"

VARIABLES = [
    "Revenue", "Cost of Revenue", "Gross Profit", "Operating Income", "Net Income", "EPS Diluted",
    "Cash and Cash Equivalents", "Operating Cash Flow", "Capital Expenditures",
    "Total Assets", "Total Current Assets", "Total Current Liabilities",
    "Total Liabilities", "Total Stockholders Equity", "Total Debt",
]

# FY, Q1, Q2, Q3 only - SEC has no standalone Q4 filing (see pipeline.py),
# so it's left out of the choices entirely rather than offered and then
# rejected after the fact.
PERIODS = ["FY", "Q1", "Q2", "Q3"]

YEARS = [str(y) for y in range(2025, 2019, -1)]  # 2025 down to 2020


def load_companies():
    """Uses the pre-built, filtered, name-normalized cache
    (build_company_list.py's output: only real 10-K/10-Q filers) once
    it exists. Until that finishes building (it takes a while - one
    real request per company), falls back to SEC's live full list
    (unfiltered, raw casing) so the app still works in the meantime.
    Builds a display name -> (ticker, entry) map either way, for
    direct lookup once a dropdown choice is made."""
    if COMPANY_CACHE_PATH.exists():
        with open(COMPANY_CACHE_PATH, encoding="utf-8") as f:
            cik_map = json.load(f)["kept"]
    else:
        cik_map = get_cik_map()

    name_to_company = {}
    for ticker, entry in cik_map.items():
        # display_name only exists once the cache is built; the live
        # fallback (raw SEC data) has no normalized name yet, so it
        # falls back to the real name as the dropdown label too - the
        # real "name" itself is never altered either way.
        label = entry.get("display_name", entry["name"])
        name_to_company[label] = (ticker, entry)
    return name_to_company


NAME_TO_COMPANY = load_companies()
COMPANIES = sorted(NAME_TO_COMPANY)


def format_value(value, variable):
    if value is None:
        return "N/A"
    if variable == "EPS Diluted":
        return f"${value:,.2f}"
    return f"${value:,.0f}"


def answer(company, year, quarter, variables):
    if not company:
        return "Pick a company."
    if not variables:
        return "Pick at least one variable."

    ticker, entry = NAME_TO_COMPANY[company]

    period_label = str(year) if quarter == "FY" else f"{quarter} {year}"
    results = pipeline.match_variables(ticker, entry["cik"], variables, str(year), quarter)

    display_name = entry.get("display_name", entry["name"])
    lines = [f"{display_name} ({ticker}), {period_label}", ""]
    for r in results:
        if "error" in r:
            lines.append(f"{r['variable']}: {r['error']}")
        else:
            lines.append(f"{r['variable']}: {format_value(r['value'], r['variable'])}")
    return "\n".join(lines)


SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
LABEL = "Searching..."


def run(company, year, quarter, variables):
    """Runs answer() in a background thread while a spinner animates
    in this one. sys.setswitchinterval() above is what keeps this
    smooth - without it, this thread can get starved of GIL time
    while the worker thread is doing GPU/model work, making the
    animation stutter unpredictably."""
    result = {}

    def worker():
        try:
            result["text"] = answer(company, year, quarter, variables)
        except Exception as e:  # noqa: BLE001
            result["text"] = f"Something went wrong answering that: {e}"

    thread = threading.Thread(target=worker)
    thread.start()

    locked = gr.update(interactive=False)
    frame = 0
    while thread.is_alive():
        yield f"{SPINNER_FRAMES[frame % len(SPINNER_FRAMES)]} {LABEL}", locked
        frame += 1
        time.sleep(0.1)

    thread.join()
    yield result.get("text", "Something went wrong answering that."), gr.update(interactive=True)


CSS = """
.gradio-container { max-width: 900px !important; margin: 0 auto !important; padding-top: 0.5rem !important; }
#title { text-align: center; margin-bottom: 0; font-size: 1.6rem !important; }
#subtitle { text-align: center; color: var(--body-text-color-subdued); margin-top: 0; margin-bottom: 1rem; font-size: 0.85rem !important; }
#result { font-size: 0.85rem !important; white-space: pre-wrap; border: 1px solid var(--border-color-primary); border-radius: 12px; padding: 1rem; min-height: 160px; background: var(--background-fill-secondary); }
"""

with gr.Blocks(theme=gr.themes.Soft(primary_hue="indigo", neutral_hue="slate"), css=CSS, title="Filing Variable Lookup") as demo:
    gr.Markdown("# Filing Variable Lookup", elem_id="title")
    gr.Markdown("Pick a company, period, and variable(s) directly.", elem_id="subtitle")

    with gr.Row():
        company = gr.Dropdown(choices=COMPANIES, label="Company", filterable=True, scale=2)
        year = gr.Dropdown(choices=YEARS, label="Year", value=YEARS[0], scale=1)
        quarter = gr.Dropdown(choices=PERIODS, label="Period", value="FY", scale=1)

    variables = gr.CheckboxGroup(choices=VARIABLES, label="Variables")

    submit = gr.Button("Get Values", variant="primary")

    result = gr.Textbox(label="Result", elem_id="result", show_label=False, interactive=False)

    submit.click(run, [company, year, quarter, variables], [result, submit])

if __name__ == "__main__":
    demo.queue().launch(server_port=7863, footer_links=["settings"])
