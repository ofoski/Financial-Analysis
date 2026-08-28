# LLM Financial Extraction

Real financial data for 187 Information Technology sector tickers (see [the 9 tracked variables](#the-9-tracked-variables)), collected from real SEC EDGAR filings. The model was trained and fine-tuned on real XBRL tags used by Information Technology companies specifically. Three separate, independently runnable pieces:

- **`deployment/`**: a Gradio app. Pick a ticker, period, and variables, and a fine-tuned Qwen2.5-3B model matches them against real XBRL line items from a live SEC filing.
- **`services/rest_api/`**: a FastAPI REST API serving the already-collected data (`GET /annual/{ticker}`, `GET /quarterly/{ticker}`).
- **`services/mcp_server/`**: an MCP server that lets an AI assistant query the same data and compare companies (`compare_growth`, `compare_margins`).

## How it works

The LLM Extraction app is the core pipeline. Given a ticker, a fiscal period, and which variables you want:

1. **Find the filing.** The ticker is resolved to a CIK (SEC's company ID), then the app looks up that company's real 10-K or 10-Q filings from SEC EDGAR.
2. **Fetch it.** The actual filing is downloaded, once, for that period.
3. **Find the real line items.** The filing's XBRL data is parsed to pull out the real candidate line items, but only from the statements the requested variables actually need (e.g. asking only for CapEx skips the income statement entirely).
4. **Match with the fine-tuned model.** For each variable, the candidate line items are shown to a fine-tuned Qwen2.5-3B model, which picks which one (or which combination, if a value has to be summed from multiple lines) actually represents that variable.
5. **Resolve the value.** The picked line item's real reported value is looked up directly from the filing, no further computation needed beyond unit conversion.
6. **Return the result.** You see the real value, and which real line item it came from.

`services/rest_api/` and `services/mcp_server/` don't repeat this process. They read from a small, already-collected database of the same 9 variables across 187 tickers, so they answer instantly instead of fetching a live filing each time.

## Project structure

```
Financial-Analysis/
├── deployment/                     # LLM Extraction app
│   ├── app.py                      # Gradio UI
│   ├── xbrl_llm_match.py           # Loads the fine-tuned model, matches candidates to variables
│   ├── xbrl_method.py              # Finds/parses real SEC filings and their XBRL data
│   ├── collect_annual_xbrl.py      # Collects candidate line items from a 10-K
│   ├── collect_quarterly_xbrl.py   # Collects candidate line items from a 10-Q
│   ├── collect_statement_xbrl.py   # Shared engine behind the two collectors above
│   ├── edgar_helpers.py            # SEC EDGAR ticker/CIK lookup
│   ├── split_check.py              # Detects stock splits since a given quarter
│   ├── split_detection.py          # Finds real split-related filings
│   ├── split_confirmation.py       # Confirms a detected split and its ratio
│   ├── query_log.py                # Logs every real match for later review
│   ├── adapter/                    # The fine-tuned LoRA adapter weights
│   └── requirements.txt
│
├── services/
│   ├── rest_api/                   # REST API service
│   │   ├── api.py                  # FastAPI app (the actual endpoints)
│   │   ├── data.py                 # SQL queries against financials.db
│   │   ├── financials.db           # Self-contained copy of the 9 tracked variables
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   │
│   └── mcp_server/                 # MCP server service
│       ├── server.py               # MCP tools (get_annual_financials, compare_growth, ...)
│       ├── data.py                 # SQL queries against financials.db
│       ├── financials.db           # Self-contained copy of the 9 tracked variables
│       ├── Dockerfile
│       └── requirements.txt
│
├── .mcp.json                       # Connects Claude Code to the MCP server locally
└── README.md
```

## Running locally

Each piece has its own `Dockerfile` and runs in its own container. They don't depend on each other to run. Requires [Docker](https://www.docker.com/) installed and running.

**1. LLM Extraction app**:
```bash
cd deployment
docker build -t llm-extraction .
docker run --gpus all -p 7860:7860 llm-extraction
```
Runs on port 7860. Requires a GPU: the model is loaded with 4-bit quantization, which only works on CUDA. `--gpus all` passes your GPU through to the container (needs the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) set up); without it, the container falls back to CPU, and we measured matching a single variable on CPU taking close to 15 minutes, not usable interactively. On GPU, matching one variable takes about 4 seconds once the model is loaded (loading itself takes under a minute).

**2. REST API**:
```bash
cd services/rest_api
docker build -t rest-api .
docker run -p 8001:7860 rest-api
```
Runs on port 8001. Open `http://127.0.0.1:8001/docs` in a browser to try it.

**3. MCP server**:
```bash
cd services/mcp_server
docker build -t mcp-server .
docker run -p 8000:7860 mcp-server
```
Runs on port 8000. This isn't a website you open in a browser. To actually use it, connect it to Claude Code: this repo's `.mcp.json` already points to it. Open a Claude Code session in this project folder while the server is running, run `/mcp` to confirm it shows as connected, then just ask a normal question like "what was AAPL's revenue in 2023?"

Claude decides on its own when to call the server, based on what you ask it. You never call it directly yourself.

## The 9 tracked variables

Revenue, Gross Profit, Cost of Revenue, Operating Income, Net Income, EPS Diluted, Cash, Operating CF, CapEx, collected from real 10-K (annual) and 10-Q (quarterly, Q1-Q3 only) SEC filings.
