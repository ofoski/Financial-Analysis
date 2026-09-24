# LLM Financial Extraction

![LLM: Qwen2.5-3B](https://img.shields.io/badge/LLM-Qwen2.5--3B-blueviolet)
![Fine-tuning: QLoRA](https://img.shields.io/badge/fine--tuning-QLoRA-blueviolet)
![Quantization: 4-bit](https://img.shields.io/badge/quantization-4--bit-blueviolet)
![MCP](https://img.shields.io/badge/MCP-000000?logo=modelcontextprotocol&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)
![CI: lint](https://img.shields.io/github/actions/workflow/status/ofoski/Financial-Analysis/lint.yml?label=CI%3A%20lint)
![CI: test](https://img.shields.io/github/actions/workflow/status/ofoski/Financial-Analysis/test.yml?label=CI%3A%20test)

Real financial data collected from real SEC EDGAR filings. Three separate, independently runnable pieces, sharing one fetch/parse pipeline and one fine-tuned model:

- **`variable_lookup/`**: pick a company, period, and variable(s) directly from dropdowns, and a fine-tuned Qwen2.5-3B model matches the real XBRL line items from that live SEC filing.
- **`filing_assistant/`**: the same real matching, as a free-text chat app. Ask a normal question ("What was Apple's revenue in Q1 2025?"), and a general-purpose model reads it first.
- **`services/mcp_server/`**: an MCP server that lets an AI assistant fetch the same kind of real data itself, real filing periods, real statement line items, and real (split-adjusted) stock prices, and reason over it directly, no separately hosted model involved.

## 🌐 Live demo

Try `variable_lookup/` online: [huggingface.co/spaces/Ofoski/filing-variable-lookup](https://huggingface.co/spaces/Ofoski/filing-variable-lookup). It runs on a shared GPU with a small daily limit per visitor, and may be taken offline at any time.

## ⚙️ How it works

### `variable_lookup/`

The company, period, and variable(s) are picked directly, so only one model is needed. **Matching** (Qwen2.5-3B fine-tuned via QLoRA, `qlora_adapter/`) is shown the real candidate line items from that company's actual filing, and picks which one (or combination, if a value has to be derived from multiple lines) represents each variable.

The company dropdown is a filtered, cached list of real domestic 10-K/10-Q filers (companies that file Form 20-F/6-K instead, mostly foreign private issuers, are excluded, since this pipeline only reads 10-K/10-Q filings). A real filing period is looked up from that company's own actual filing history before anything is matched.

### `filing_assistant/`

The same matching step, with a second model in front of it:

1. **Extraction** (Qwen2.5-7B-Instruct, general-purpose, no fine-tuning) reads your free-text question and pulls out the company name, period, and which of the 15 tracked variables you're asking about.
2. **Matching** is the same fine-tuned model as in `variable_lookup/`.

The company name is resolved against SEC's real, full company list (not a fixed list) before anything is matched.

### `services/mcp_server/`

The reasoning here is done by whatever MCP-connected AI agent (like Claude) is calling these tools. It already brings its own financial knowledge, gross margin, comparisons, trends, whatever the question needs, so these 3 tools only need to hand it real numbers, "what was Apple's revenue last quarter?", "compare Microsoft's and Google's cash flow", "what's Tesla's gross margin?" all work this way.

1. **Find the real period.** Fiscal quarters don't line up with calendar ones, so the agent first looks up which years and quarters a company has actually filed with the SEC, each with its own real period-end date.
2. **Fetch the real numbers.** Using that real date, it pulls the real line items from the company's income statement, balance sheet, or cash flow filing for that period.
3. **Get a real stock price, if needed.** Live, or on a specific date, split/dividend-adjusted so a real stock split never looks like the price crashed overnight.

## 📁 Project structure

```
Financial-Analysis/
├── variable_lookup/                 # Direct-selection app (dropdowns)
│   ├── app.py                       # Gradio UI (company/period/variable dropdowns)
│   ├── build_company_list.py        # One-time build: filters SEC's full company list to real 10-K/10-Q filers
│   └── companies_cache.json         # That build script's cached output
│
├── filing_assistant/                # Free-text chat app
│   ├── app.py                       # Gradio UI
│   ├── extract.py                   # Reads the question, extracts company/period/variables (Qwen2.5-7B)
│   ├── qa_backend.py                # Runs extract -> resolve -> pipeline for one question
│   ├── resolver.py                  # Resolves a company name to a real ticker/CIK
│   └── pipeline.py                  # Fetches real filing data, runs the fine-tuned adapter, resolves the real value (also used by variable_lookup)
│
├── qlora_adapter/                   # The fine-tuned model filing_assistant/variable_lookup both use
│   ├── adapter/                     # The trained LoRA adapter weights (Qwen2.5-3B base)
│   └── prompt_format.py             # The exact prompt format the adapter was trained on
│
├── services/
│   └── mcp_server/                  # MCP server service
│       ├── server.py                # MCP tools (list_periods, get_report, get_stock_price)
│       ├── financial_data.py        # Business logic behind list_periods/get_report
│       ├── stock_price.py           # Real stock price lookups (via yfinance)
│       ├── Dockerfile
│       └── requirements.txt
│
├── xbrl_pipeline/                   # Shared by every piece above
│   ├── edgar_helpers.py             # SEC EDGAR ticker/CIK lookup
│   ├── xbrl_method.py               # Finds/parses real SEC filings and their XBRL data
│   ├── collect_annual_xbrl.py       # Collects candidate line items from a 10-K
│   ├── collect_quarterly_xbrl.py    # Collects candidate line items from a 10-Q
│   └── collect_statement_xbrl.py    # Shared engine behind the two collectors above
│
├── .dockerignore                    # services/mcp_server/Dockerfile builds from the repo root, this keeps that build small
├── .mcp.json                        # Connects Claude Code to the MCP server locally
├── requirements.txt                 # Requirements for variable_lookup and filing_assistant
└── README.md
```

## 💻 Running locally

Clone the whole repo.

Before running anything, open `xbrl_pipeline/edgar_helpers.py` and replace the placeholder `HEADERS` User-Agent with your own name and email. SEC asks every program that downloads from EDGAR to identify itself this way.

Install the requirements for the first two apps once, from the repo root:
```bash
python -m venv venv
venv\Scripts\activate      # on Windows; source venv/bin/activate on macOS/Linux
pip install -r requirements.txt
```

**1. Variable lookup (direct selection)**:
```bash
cd variable_lookup
python app.py
```
Runs on port 7863. Benefits from a GPU: the model loads with 4-bit quantization, which needs CUDA to run at a reasonable speed. `build_company_list.py` can be rerun to refresh the cached, filtered `companies_cache.json`.

**2. Filing assistant (chat)**:
```bash
cd filing_assistant
python app.py
```
Runs on port 7860. Both of its models load with 4-bit quantization.

**3. MCP server**:
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
Runs on port 8000. With the server running, open a Claude Code session in this folder (`.mcp.json` already points to it) and run `/mcp` to check it's connected. The server window shows `200 OK` when Claude connects. Then ask a question like "what was AAPL's revenue last quarter?"

Claude decides on its own when to call the server, based on what you ask it. You never call it directly yourself.

## 📊 The 15 tracked variables

Collected from real 10-K (annual) and 10-Q (quarterly, Q1, Q2, Q3) SEC filings. The fine-tuned adapter was trained on 6,915 real, analyst-verified examples, validated during training on a further 759, and scores **92.4% exact-match accuracy** overall on a fully held-out test set of 1,440 examples across 48 companies (2 per sector, 24 sectors) never seen during training or validation:

| Variable | Accuracy |
|---|---|
| Total Current Assets | 100.0% |
| Total Current Liabilities | 100.0% |
| Cash and Cash Equivalents | 99.0% |
| Operating Cash Flow | 99.0% |
| Total Assets | 99.0% |
| Total Stockholders Equity | 99.0% |
| EPS Diluted | 94.8% |
| Revenue | 94.8% |
| Net Income | 92.7% |
| Cost of Revenue | 90.6% |
| Operating Income | 89.6% |
| Capital Expenditures | 87.5% |
| Gross Profit | 87.5% |
| Total Debt | 82.3% |
| Total Liabilities | 70.8% |
