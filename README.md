# Financial Analysis Pipeline

Fundamental financial data collection for US equities using SEC EDGAR XBRL, with a Gemini AI fallback for missing values.

## Overview

- **Data source:** SEC EDGAR XBRL API (free, no API key required)
- **Coverage:** Any US company that files with the SEC (10-K annual reports)
- **Fallback:** Gemini AI fills missing values when standard XBRL tags don't match
- **History:** Last 5 fiscal years per company (annual 10-K)
- **Storage:** SQLite (`data/financials.db`)
- **Progress:** Resumable — safe to stop and re-run at any time

## Financial Variables (28 total)

### Income Statement
Revenue, Cost of Revenue, Gross Profit, R&D, SG&A, Operating Income, Interest Expense, Pre-tax Income, Income Tax, Net Income, EPS Basic, EPS Diluted

### Balance Sheet
Cash, Accounts Receivable, Inventory, Goodwill, Current Assets, Total Assets, Current Liabilities, Total Debt, Total Liabilities, Equity

### Cash Flow Statement
Operating CF, CapEx, Depreciation, Stock-Based Comp, Stock Buybacks, Dividends Paid

---

## How It Works

### Pass 1 — Standard XBRL tag matching
Each of the 28 variables has an ordered list of known XBRL tag alternatives defined in `src/collectors/financial_variables.py`. The pipeline tries each tag in order and takes the first one that has a value for the target period (form, fiscal period, period-end date).

### Pass 2 — Gemini fallback
Variables still missing after Pass 1 are sent to Gemini in a **single batched call per fiscal year**. Gemini receives all available XBRL tags for that period with their values and reasons through which tags (if any) correspond to the missing variables.

Gemini follows strict accounting rules:
- A single tag covering the full amount is acceptable
- Aggregating multiple non-overlapping tags that sum to 100% of the amount is acceptable
- A partial value (one segment, one geography, one category) is never acceptable — returns null
- If not confident, returns null — a wrong value is worse than null

### Rate limiting
- **SEC EDGAR:** 1.5 s sleep after every HTTP request
- **Gemini API:** 15 s sleep after every API call (keeps usage under 4 RPM, within the 10 RPM free-tier limit)

---

## Progress & Resumability

Progress is tracked at **two levels**:

| Level | File | What it tracks |
|---|---|---|
| Company | `progress.json` | Companies fully processed across all 5 years |
| Year | `data/financials.db` | Individual fiscal years saved (via `collected_date`) |

If the pipeline crashes mid-company (e.g. Gemini API error), the years already saved to the DB are preserved. On the next run, those years are detected via the DB and skipped — only the remaining years are processed. This means no Gemini requests are wasted on retry.

---

## Gemini Fallback Logs

All Gemini activity is logged to the `logs/` folder for review and auditing:

**`logs/gemini_found.jsonl`** — variables Gemini successfully resolved:
```json
{"ticker": "AAPL", "fiscal_year_end": "2023-09-30", "form": "10-K", "fp": "FY",
 "variable": "Interest Expense", "value": 3933.0,
 "method": "single_tag", "tags_used": ["InterestExpenseDebt"],
 "tag_values": {"InterestExpenseDebt": 3933.0}}
```

**`logs/gemini_null.jsonl`** — variables Gemini could not resolve (with reasoning):
```json
{"ticker": "AAPL", "fiscal_year_end": "2020-09-26", "form": "10-K", "fp": "FY",
 "variable": "Interest Expense",
 "reasoning": "Interest expense is embedded in a net Other income/expense tag and cannot be isolated."}
```

---

## Project Structure

```
Financial-Analysis/
├── main.py                          # Pipeline runner
├── requirements.txt
├── progress.json                    # Completed tickers (auto-generated)
├── errors.log                       # Pipeline errors (auto-generated)
├── config/
│   ├── .env                         # API keys (not committed)
│   └── .env.example
├── data/
│   └── financials.db                # SQLite database (auto-generated)
├── logs/
│   ├── gemini_found.jsonl           # Gemini successes (auto-generated)
│   └── gemini_null.jsonl            # Gemini nulls with reasoning (auto-generated)
└── src/
    ├── collectors/
    │   ├── tags.py                  # SEC EDGAR fetching + find_value
    │   ├── annual.py                # Annual (10-K) extraction orchestrator
    │   ├── financial_variables.py   # XBRL tag lists per variable
    │   └── gemini_fallback.py       # Gemini fallback logic + logging
    └── storage/
        └── database.py              # SQLite schema + upsert helpers
```

---

## Database Schema

**`companies`** table — one row per company:

| Column | Type | Description |
|---|---|---|
| ticker | TEXT (PK) | Stock ticker |
| name | TEXT | Company name from SEC |
| sector | TEXT | Optional sector classification |
| industry | TEXT | Optional industry classification |

**`financial_data_annual`** table — one row per company per fiscal year:

| Column | Type | Description |
|---|---|---|
| ticker | TEXT | Foreign key → companies |
| fiscal_year_end | TEXT | Period-end date (e.g. `2023-09-30`) |
| revenue … dividends_paid | REAL | 28 financial variables (USD millions, EPS per-share) |
| collected_date | TEXT | Date this row was saved |

All monetary values are in **USD millions** except EPS Basic and EPS Diluted which are per-share amounts.

---

## Setup

### 1. Create and activate the virtual environment
```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Windows PowerShell
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Add your Gemini API key
Copy `config/.env.example` to `config/.env` and fill in your key:
```
GEMINI_API_KEY=your_key_here
```

Get a free key at [Google AI Studio](https://aistudio.google.com).
> **Note:** The free tier allows ~20 requests/day. For large runs enabling billing is recommended — cost is under $2 for 2,000 companies.

### 4. Choose your companies
Edit the `COMPANIES` list in `main.py`:
```python
COMPANIES = ["AAPL", "MSFT", "GOOGL"]
```

Any ticker that files annual reports with the SEC can be added to this list.

### 5. Run
```bash
python main.py
```
