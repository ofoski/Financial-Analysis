# LLM Financial Extraction

![LLM: Qwen2.5-3B](https://img.shields.io/badge/LLM-Qwen2.5--3B-blueviolet)
![Fine-tuning: QLoRA](https://img.shields.io/badge/fine--tuning-QLoRA-blueviolet)
![Quantization: 4-bit](https://img.shields.io/badge/quantization-4--bit-blueviolet)
![MCP](https://img.shields.io/badge/MCP-000000?logo=modelcontextprotocol&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)
![CI: lint](https://img.shields.io/github/actions/workflow/status/ofoski/Financial-Analysis/lint.yml?label=CI%3A%20lint)
![CI: test](https://img.shields.io/github/actions/workflow/status/ofoski/Financial-Analysis/test.yml?label=CI%3A%20test)

Real financial data collected from real SEC EDGAR filings. Two separate, independently runnable pieces, sharing one fetch/parse pipeline:

- **`guided_app/`**: a guided chat app. Answer three short questions, company, period, and which variables, one at a time, and a fine-tuned Qwen2.5-3B model matches them against real XBRL line items from a live SEC filing.
- **`services/mcp_server/`**: an MCP server that lets an AI assistant fetch the same kind of real data itself, real filing periods, real statement line items, and real (split-adjusted) stock prices, and reason over it directly, no separately hosted model involved.

## ⚙️ How it works

### `guided_app/`

A fine-tuned Qwen2.5-3B model, hosted inside this app, is what actually reads your replies and picks out the real line items. It asks for company, then period, then which of the 9 tracked variables you want, one question at a time, and reads each short reply on its own:

1. **Company** - resolves whatever you typed to a real ticker (an exact match or a real SEC company name), or asks again if nothing matches.
2. **Period** - pulls out a year and, if mentioned, a quarter (Q1-Q3 or FY for a full year); no quarter mentioned defaults to a full year.
3. **Variables** - matches your reply against the 9 tracked variables directly where possible; free-form replies fall back to the fine-tuned model to pick out which ones you meant.

Once all three are known, it fetches the real filing for that period, and for each variable, shows the fine-tuned model the real candidate line items from that filing so it can pick which one (or combination, if a value has to be summed from multiple lines) actually represents that variable. You see the real value, and which real line item it came from.

### `services/mcp_server/`

The reasoning here is done by whatever MCP-connected AI agent (like Claude) is calling these tools. It already brings its own financial knowledge, gross margin, comparisons, trends, whatever the question needs, so these 3 tools only need to hand it real numbers, "what was Apple's revenue last quarter?", "compare Microsoft's and Google's cash flow", "what's Tesla's gross margin?" all work this way.

1. **Find the real period.** Fiscal quarters don't line up with calendar ones, so the agent first looks up which years and quarters a company has actually filed with the SEC, each with its own real period-end date.
2. **Fetch the real numbers.** Using that real date, it pulls the real line items from the company's income statement, balance sheet, or cash flow filing for that period.
3. **Get a real stock price, if needed.** Live, or on a specific date, split/dividend-adjusted so a real stock split never looks like the price crashed overnight.

## 📁 Project structure

```
Financial-Analysis/
├── guided_app/                     # Guided chat app
│   ├── app.py                      # Gradio UI
│   ├── extraction.py               # Reads each reply, extracts company/period/variables, drives the flow
│   ├── resolver.py                 # Resolves a company to a real ticker; fetches and matches real filing data
│   ├── adapter/                    # The fine-tuned LoRA adapter weights
│   ├── Dockerfile
│   └── requirements.txt
│
├── services/
│   └── mcp_server/                 # MCP server service
│       ├── server.py               # MCP tools (list_periods, get_report, get_stock_price)
│       ├── financial_data.py       # Business logic behind list_periods/get_report
│       ├── stock_price.py          # Real stock price lookups (via yfinance)
│       ├── Dockerfile
│       └── requirements.txt
│
├── xbrl_pipeline/                  # Shared by guided_app/ and services/mcp_server/
│   ├── edgar_helpers.py            # SEC EDGAR ticker/CIK lookup
│   ├── xbrl_method.py              # Finds/parses real SEC filings and their XBRL data
│   ├── collect_annual_xbrl.py      # Collects candidate line items from a 10-K
│   ├── collect_quarterly_xbrl.py   # Collects candidate line items from a 10-Q
│   └── collect_statement_xbrl.py   # Shared engine behind the two collectors above
│
├── .dockerignore                   # Both Dockerfiles build from the repo root, this keeps that build small
├── .mcp.json                       # Connects Claude Code to the MCP server locally
└── README.md
```

## 💻 Running locally

Both pieces need `xbrl_pipeline/` alongside them (they import it directly), so clone the whole repo rather than just one folder. Each has its own `requirements.txt`, they don't depend on each other to run. Either run them directly with Python, or with Docker, both `Dockerfile`s build from the **repo root** (not their own folder), since that's the only place both a piece and `xbrl_pipeline/` are both reachable.

**1. Guided chat app**:
```bash
# with Python
cd guided_app
python -m venv venv
venv\Scripts\activate      # on Windows; source venv/bin/activate on macOS/Linux
pip install -r requirements.txt
python app.py

# with Docker (run from the repo root)
docker build -f guided_app/Dockerfile -t guided-app .
docker run --gpus all -p 7860:7860 guided-app
```
Runs on port 7860. Benefits from a GPU: the model is loaded with 4-bit quantization, which needs CUDA to run at a reasonable speed; it'll fall back to CPU otherwise, but noticeably slower. `--gpus all` passes your GPU through to the container (needs the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) set up); leave it off to run on CPU instead.

**2. MCP server**:
```bash
# with Python
cd services/mcp_server
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python server.py

# with Docker (run from the repo root)
docker build -f services/mcp_server/Dockerfile -t mcp-server .
docker run -p 8000:8000 mcp-server
```
Runs on port 8000 by default. This isn't a website you open in a browser. To actually use it, connect it to Claude Code: this repo's `.mcp.json` already points to it. Open a Claude Code session in this project folder while the server is running, run `/mcp` to confirm it shows as connected, then just ask a normal question like "what was AAPL's revenue last quarter?"

Claude decides on its own when to call the server, based on what you ask it. You never call it directly yourself.

## 📊 The 9 tracked variables

Revenue, Gross Profit, Cost of Revenue, Operating Income, Net Income, EPS Diluted, Cash, Operating CF, CapEx, collected from real 10-K (annual) and 10-Q (quarterly, Q1-Q3 only) SEC filings.
