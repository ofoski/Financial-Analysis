# Financial Analysis

Real financial data (Revenue, Gross Profit, Cost of Revenue, Operating Income, Net Income, EPS Diluted, Cash, Operating CF, CapEx) for 187 tracked tickers, collected from real SEC EDGAR filings. Three separate, independently runnable pieces:

- **`deployment/`**: a Gradio app with two tabs. LLM Extraction lets you pick a ticker, period, and variables, and a fine-tuned Qwen2.5-3B model matches them against real XBRL line items from a live SEC filing. The second tab has docs for the two services below.
- **`services/rest_api/`**: a FastAPI REST API serving the already-collected data (`GET /annual/{ticker}`, `GET /quarterly/{ticker}`).
- **`services/mcp_server/`**: an MCP server that lets an AI assistant query the same data and compare companies (`compare_growth`, `compare_margins`).

## Running locally

Each piece runs separately, in its own terminal, with its own Python environment. For the REST API and MCP tabs in the Gradio app to work when you click their examples, all three need to be running at the same time.

**1. REST API**:
```bash
cd services/rest_api
pip install -r requirements.txt
uvicorn api:app --port 8001
```
Runs on port 8001. Open `http://127.0.0.1:8001/docs` in a browser to try it.

**2. MCP server**:
```bash
cd services/mcp_server
pip install -r requirements.txt
python server.py
```
Runs on port 8000. This isn't a website you open in a browser. To actually use it, connect it to Claude Code: this repo's `.mcp.json` already points to it. Open a Claude Code session in this project folder while the server is running, run `/mcp` to confirm it shows as connected, then just ask a normal question like "what was AAPL's revenue in 2023?"

Claude decides on its own when to call the server, based on what you ask it. You never call it directly yourself.

**3. LLM Extraction app**:
```bash
cd deployment
pip install -r requirements.txt
python app.py
```
Runs on port 7860. Requires a GPU, since it uses 4-bit quantization to run the model efficiently.

## The 9 tracked variables

Revenue, Gross Profit, Cost of Revenue, Operating Income, Net Income, EPS Diluted, Cash, Operating CF, CapEx, collected from real 10-K (annual) and 10-Q (quarterly, Q1-Q3 only) SEC filings.
