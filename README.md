# Financial Analysis

Real financial data (Revenue, Gross Profit, Cost of Revenue, Operating Income, Net Income, EPS Diluted, Cash, Operating CF, CapEx) for 187 tracked tickers, collected from real SEC EDGAR filings. Three separate, independently runnable pieces:

- **`deployment/`** — a Gradio app with two tabs: LLM Extraction (pick a ticker/period/variables, and a fine-tuned Qwen2.5-3B model matches them against real XBRL line items from a live SEC filing) and docs for the two services below.
- **`services/rest_api/`** — a FastAPI REST API serving the already-collected, stored data (`GET /annual/{ticker}`, `GET /quarterly/{ticker}`).
- **`services/mcp_server/`** — an MCP server exposing the same data, plus cross-company comparison tools (`compare_growth`, `compare_margins`), for use by an AI assistant.

## Running locally

Each piece is separate and needs its own Python environment and its own terminal. For the REST API and MCP tabs in the Gradio app to actually work when you click their examples, all three need to be running at the same time.

**1. REST API** (from `services/rest_api/`):
```bash
pip install -r requirements.txt
uvicorn api:app --port 8001
```
Test it: open `http://127.0.0.1:8001/docs` in a browser, or `curl "http://127.0.0.1:8001/annual/AAPL?year=2023"`.

**2. MCP server** (from `services/mcp_server/`):
```bash
pip install -r requirements.txt
python server.py
```
Runs on port 8000. Meant to be used through an AI assistant, not directly — see `.mcp.json` for connecting Claude Code to it locally.

**3. LLM Extraction app** (from `deployment/`):
```bash
pip install -r requirements.txt
python app.py
```
Runs on port 7860. This one needs real GPU + CUDA for reasonable speed (it uses 4-bit quantization) — on CPU, a single variable extraction takes close to 15 minutes, which isn't usable interactively.

Each folder's `data.py`/`financials.db` (REST API, MCP server) is a self-contained copy of the same underlying data — that's intentional, so each service can be deployed independently later.

## The 9 tracked variables

Revenue, Gross Profit, Cost of Revenue, Operating Income, Net Income, EPS Diluted, Cash, Operating CF, CapEx — collected from real 10-K (annual) and 10-Q (quarterly, Q1-Q3 only) SEC filings.
