"""Two-tab app: LLM Extraction (ticker -> year -> quarter -> which
variables, then collects the real candidate lists for exactly the
statements those variables need, and asks the fine-tuned model to
resolve each variable's actual value from those candidates) and
Financial Data API (a static docs page for the separate REST API).
"""
import re

import gradio as gr

from edgar_helpers import get_cik_map
from xbrl_method import list_available_quarters
from xbrl_llm_match import VARS_BY_STATEMENT, collect_candidates_for_quarter, match_variables
from collect_annual_xbrl import collect_annual_candidates
from split_check import find_splits_since
from query_log import log_match

CIK_MAP = get_cik_map()
ALL_VARIABLES = [v for statement_vars in VARS_BY_STATEMENT.values() for v in statement_vars]

# Display-only renames, for the checkbox labels and results. The internal
# names (VARS_BY_STATEMENT, clear_labels, DB_COL_BY_VAR elsewhere) stay
# the short originals, since other code already depends on those exact
# strings.
VAR_DISPLAY_NAMES = {
    "Cash": "Cash and Cash Equivalents",
    "Operating CF": "Operating Cash Flow",
    "CapEx": "Capital Expenditure",
}
CHECKBOX_CHOICES = [VAR_DISPLAY_NAMES.get(v, v) for v in ALL_VARIABLES]
DISPLAY_TO_INTERNAL = {VAR_DISPLAY_NAMES.get(v, v): v for v in ALL_VARIABLES}


def load_years(ticker):
    empty_period = gr.update(choices=[], value=None)
    yield gr.update(choices=[], value=None), {}, "🔍 Searching...", empty_period

    entry = CIK_MAP.get(ticker.strip().upper())
    if not entry:
        yield gr.update(choices=[], value=None), {}, f"Ticker '{ticker}' not found.", empty_period
        return

    quarters = list_available_quarters(entry["cik"])
    years = sorted(quarters.keys(), reverse=True)
    # value=None here on purpose: switching tickers shouldn't auto-pick a
    # year (and therefore a period), that made it easy to miss that the
    # ticker had actually changed when testing one after another.
    yield gr.update(choices=years, value=None), quarters, f"{entry['name']} (CIK {entry['cik']})", empty_period


def load_periods(year, quarters):
    if not year or year not in quarters:
        return gr.update(choices=[], value=None)

    year_data = quarters[year]
    choices = [f"{label} ({year_data[label]})" for label in ["Q1", "Q2", "Q3", "FY"] if label in year_data]
    return gr.update(choices=choices, value=choices[0] if choices else None)


def collect(ticker, quarter_choice, display_variables):
    empty_state = {}
    hide_table = gr.update(value=[], visible=False)
    hide_split = gr.update(visible=False)
    if not (entry := CIK_MAP.get(ticker.strip().upper())):
        yield f"Ticker '{ticker}' not found.", hide_table, hide_split, hide_split, empty_state, ""
        return
    if not quarter_choice:
        yield "Pick a quarter first.", hide_table, hide_split, hide_split, empty_state, ""
        return
    if not display_variables:
        yield "Pick at least one variable first.", hide_table, hide_split, hide_split, empty_state, ""
        return

    yield "🔍 Searching...", hide_table, hide_split, hide_split, empty_state, ""

    variables = [DISPLAY_TO_INTERNAL[v] for v in display_variables]

    period_end = re.search(r"\((\d{4}-\d{2}-\d{2})\)", quarter_choice).group(1)
    cik_int = int(entry["cik"])
    if quarter_choice.startswith("FY"):
        needed_statements = {
            statement for statement, statement_vars in VARS_BY_STATEMENT.items()
            if any(v in variables for v in statement_vars)
        }
        annual_rows = collect_annual_candidates(
            ticker.strip().upper(), cik_int, fiscal_year_ends={period_end}, statements=needed_statements,
        )
        candidates_by_statement = {
            statement: annual_rows[0][statement] for statement in needed_statements
        } if annual_rows else {}
    else:
        candidates_by_statement = collect_candidates_for_quarter(ticker.strip().upper(), cik_int, period_end, variables)

    if not candidates_by_statement:
        yield "No candidates found.", hide_table, hide_split, hide_split, empty_state, ""
        return

    matched = {}
    for statement, candidates in candidates_by_statement.items():
        statement_vars = [v for v in VARS_BY_STATEMENT[statement] if v in variables]
        statement_matched = match_variables(candidates, variables_to_collect=statement_vars)
        matched.update(statement_matched)
        for var, info in statement_matched.items():
            log_match(ticker.strip().upper(), period_end, var, candidates, info["selected"], info["value"])

    rows = []
    for var in variables:
        info = matched.get(var, {"selected": None, "value": None})
        unit = "$/share" if var == "EPS Diluted" else "$M"
        rows.append([f"{VAR_DISPLAY_NAMES.get(var, var)} ({unit})", info["value"], info["selected"]])

    # The "Check for stock split" button only appears once EPS Diluted
    # was actually collected and has a real value -- this is a separate
    # step the user triggers afterward, not something that runs as part
    # of this same collection.
    eps_info = matched.get("EPS Diluted")
    has_eps = eps_info is not None and eps_info["value"] is not None
    state = {"ticker": ticker.strip().upper(), "cik_int": cik_int, "quarter_end": period_end, "eps_value": eps_info["value"]} if has_eps else empty_state
    # Clears out any leftover result text from a previous "Check for
    # stock split" click -- otherwise a stale result from a different
    # ticker/quarter would stay on screen after a new Collect.
    show_split = gr.update(visible=has_eps)
    yield "", gr.update(value=rows, visible=True), show_split, show_split, state, ""


def check_split(state):
    if not state:
        return "Nothing to check."

    yield "Checking for a stock split..."

    splits = find_splits_since(state["ticker"], state["cik_int"], state["quarter_end"])
    if not splits:
        yield f"No stock split found for {state['ticker']} since {state['quarter_end']}."
        return

    lines = [f"Stock split detected: {s['split_ratio_label']}, effective {s['effective_date']}," for s in splits]

    # More than one real split can happen after the selected quarter (a
    # real example: ANET had one in 2021 and another in 2024) -- each
    # one's ratio has to be multiplied together to get the true
    # cumulative adjustment, not just the first one applied alone.
    combined_ratio = 1
    for s in splits:
        combined_ratio *= s["ratio"]
    restated = state["eps_value"] / combined_ratio
    lines.append(f"Restated EPS value: {state['eps_value']:.2f} → {restated:.2f}")

    yield "\n".join(lines)


with gr.Blocks(title="Quarter Selector Demo") as extraction_demo:
    gr.Markdown("# Ticker → Year → Period → Variables\nPick a company, a real fiscal quarter or full year, and which variables you want, then collect the real candidate data for just the statements those variables need.")

    with gr.Row():
        ticker_input = gr.Textbox(label="Ticker", placeholder="e.g. MSFT")
        year_dropdown = gr.Dropdown(label="Year", choices=[], interactive=True)
        quarter_dropdown = gr.Dropdown(label="Period", choices=[], interactive=True)
    company_label = gr.Markdown("")
    quarters_state = gr.State({})

    variables_checkboxes = gr.CheckboxGroup(label="Variables", choices=CHECKBOX_CHOICES)
    collect_button = gr.Button("Collect")
    status = gr.Markdown("")
    results_table = gr.Dataframe(headers=["Variable", "Value", "Source"], value=[], visible=False)

    split_state = gr.State({})
    split_note = gr.Markdown(
        "*A stock split changes share count, so EPS before the split isn't "
        "directly comparable to EPS after it until restated.*",
        visible=False,
    )
    split_button = gr.Button("Check for stock split", visible=False)
    split_output = gr.Markdown("")

    ticker_input.submit(
        load_years, inputs=ticker_input, outputs=[year_dropdown, quarters_state, company_label, quarter_dropdown],
        show_progress="hidden",
    )
    year_dropdown.change(
        load_periods, inputs=[year_dropdown, quarters_state], outputs=quarter_dropdown,
        show_progress="hidden",
    )
    collect_button.click(
        collect, inputs=[ticker_input, quarter_dropdown, variables_checkboxes], outputs=[status, results_table, split_note, split_button, split_state, split_output],
        show_progress="hidden",
    )
    split_button.click(
        check_split, inputs=split_state, outputs=split_output,
    )

API_URL = "http://127.0.0.1:8001"

PYTHON_EXAMPLE = f'''import requests
import pandas as pd

BASE_URL = "{API_URL}"

# Annual financials for one ticker, a range of fiscal years
resp = requests.get(f"{{BASE_URL}}/annual/AAPL", params={{"year": 2023, "end_year": 2024}})
annual_df = pd.DataFrame(resp.json())

# Just one fiscal year (omit end_year)
resp = requests.get(f"{{BASE_URL}}/annual/AAPL", params={{"year": 2023}})
annual_df = pd.DataFrame(resp.json())

# Quarterly financials (10-Q filings only), a range of real fiscal quarters
resp = requests.get(f"{{BASE_URL}}/quarterly/AAPL", params={{"year": 2025, "quarter": "Q1", "end_year": 2025, "end_quarter": "Q3"}})
quarterly_df = pd.DataFrame(resp.json())

# Just one quarter (omit end_year/end_quarter)
resp = requests.get(f"{{BASE_URL}}/quarterly/AAPL", params={{"year": 2025, "quarter": "Q1"}})
quarterly_df = pd.DataFrame(resp.json())
'''

CURL_EXAMPLE = f'''curl "{API_URL}/annual/AAPL?year=2023&end_year=2024"

curl "{API_URL}/quarterly/AAPL?year=2025&quarter=Q1&end_year=2025&end_quarter=Q3"'''

with gr.Blocks(title="Financial Data API Docs") as data_api_docs:
    gr.Markdown(f"""# Financial Data API
Real annual and quarterly financials for 187 tracked tickers: Revenue, Gross Profit, Cost of Revenue, Operating Income, Net Income, EPS Diluted, Cash, Operating CF, CapEx. No authentication required, `GET` only.

## Endpoints

| Endpoint | Description | Example |
|---|---|---|
| `GET /annual/{{ticker}}` | One row per fiscal year, from 10-K filings | `/annual/AAPL?year=2023&end_year=2024` |
| `GET /quarterly/{{ticker}}` | One row per real fiscal quarter (Q1-Q3), from 10-Q filings, each labeled e.g. `"Q2 2025"` | `/quarterly/AAPL?year=2025&quarter=Q1&end_year=2025&end_quarter=Q3` |

`year` (annual) and `year`+`quarter` (quarterly) are required and identify one specific period. `end_year` (annual) and `end_year`+`end_quarter` (quarterly) are optional - add them to get a range instead of just that one period.

## Python

```python
{PYTHON_EXAMPLE}
```

## curl

```bash
{CURL_EXAMPLE}
```

## Interactive docs

Every endpoint is also browsable and testable at [{API_URL}/docs]({API_URL}/docs), auto-generated from the API itself.
""")

MCP_URL = "https://<your-space>.hf.space/mcp"

with gr.Blocks(title="MCP Docs") as mcp_docs:
    gr.Markdown(f"""# MCP (for AI Assistants)
Same underlying data as the Financial Data API, but for connecting an AI assistant (e.g. Claude) directly, so it can answer questions conversationally instead of you writing code.

## Server URL

```
{MCP_URL}
```

## How to connect

On claude.ai: Settings -> Connectors -> Add custom connector -> paste the URL above. Other MCP-compatible AI clients have their own equivalent "add a server by URL" setting.

## Available tools

| Tool | Does |
|---|---|
| `get_annual_financials(ticker, year, end_year)` | One company's annual financials |
| `get_quarterly_financials(ticker, year, quarter, end_year, end_quarter)` | One company's quarterly financials |
| `compare_growth(tickers, variable, start_year, end_year)` | Year-over-year percent change across companies |
| `compare_margins(tickers, margin, year, end_year)` | Gross/operating/net/operating CF/FCF margin or CapEx ratio across companies |

`compare_growth` and `compare_margins` only exist here, not in the REST API - the REST API is intentionally raw data only, no formulas.
""")

demo = gr.TabbedInterface(
    [extraction_demo, data_api_docs, mcp_docs],
    ["LLM Extraction", "Financial Data API", "MCP"],
    title="Financial Analysis",
)

if __name__ == "__main__":
    demo.launch()
