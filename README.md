# Financial Analysis Pipeline

Fundamental financial data collection for US equities using SEC EDGAR XBRL, with a Gemini AI fallback for missing values.

## Overview

- **Data source:** SEC EDGAR XBRL API (free, no API key required)
- **Coverage:** Russell 3000 US equities (annual 10-K filings)
- **History:** Last 5 fiscal years per company
- **Storage:** SQLite (`data/financials.db`)
- **Sector-aware:** Real Estate and Financials use tailored variable sets
- **Progress:** Resumable — safe to stop and re-run at any time

## Financial Variables (28 total)

### Income Statement
Revenue, Cost of Revenue, Gross Profit, R&D, SG&A, Operating Income, Interest Expense, Pre-tax Income, Income Tax, Net Income, EPS Basic, EPS Diluted

### Balance Sheet
Cash, Accounts Receivable, Inventory, Goodwill, Current Assets, Total Assets, Current Liabilities, Total Debt, Total Liabilities, Equity

### Cash Flow Statement
Operating CF, CapEx, Depreciation, Stock-Based Comp, Stock Buybacks, Dividends Paid

> Real Estate and Financials sectors omit Cost of Revenue, Gross Profit, and R&D — these concepts do not apply to those sectors.

---

## How It Works

### Pass 1 — XBRL tag matching
Each variable has an ordered list of XBRL tag alternatives in `src/collectors/financial_variables.py`. The pipeline tries each tag in order and takes the first match for the target period. Payment-type tags (interest expense, capex, buybacks, dividends paid) automatically have their sign corrected if filed as negative outflows.

### Pass 2 — Accounting identities
Missing values are derived from known ones using standard accounting relationships:
- `Gross Profit = Revenue − Cost of Revenue`
- `Gross Profit = Operating Income + R&D + SG&A` (when the first is unavailable)
- `Cost of Revenue = Revenue − Gross Profit`
- `Pre-tax Income = Net Income + Income Tax`
- `Total Liabilities = Total Assets − Equity`

### Pass 3 — Gemini fallback
Variables still missing are sent to Gemini in a single batched call per fiscal year. Gemini returns null rather than guessing — a missing value is better than a wrong one.

---

## Project Structure

```
Financial-Analysis/
├── main.py                          # Pipeline runner
├── config/
│   └── .env                         # API keys (not committed)
├── data/
│   └── financials.db                # SQLite database
└── src/
    ├── collectors/
    │   ├── tags.py                  # SEC EDGAR fetching
    │   ├── annual.py                # 10-K extraction
    │   ├── financial_variables.py   # XBRL tag lists
    │   ├── sector_variables.py      # Sector-specific variable sets
    │   └── gemini_fallback.py       # Gemini fallback
    └── storage/
        └── database.py              # Schema and upsert helpers
```

---

> **Status:** In progress. Usage instructions will be shared once complete.
