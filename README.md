# Financial Analysis Pipeline

Fundamental financial data collection for US equities using SEC EDGAR XBRL.

## Overview

- **Data source:** SEC EDGAR XBRL API (free, no API key required)
- **Coverage:** Starting with S&P 100, expanding to S&P 500 → Russell 1000 → Russell 2000
- **History:** 5 fiscal years (annual) + 9 quarters (Q1, Q2, Q3 per year)
- **Fallback:** Gemini AI fills missing values when XBRL tags are unavailable
- **Storage:** SQLite database

## Financial Variables

### Income Statement
Revenue, Cost of Revenue, Gross Profit, R&D, SG&A, Operating Income,
Interest Expense, Pre-tax Income, Income Tax, Net Income, EPS Basic, EPS Diluted

### Balance Sheet
Cash, Accounts Receivable, Inventory, Goodwill, Current Assets, Total Assets,
Current Liabilities, Total Debt, Total Liabilities, Equity

### Cash Flow Statement
Operating CF, CapEx, Depreciation, Stock-Based Comp, Stock Buybacks, Dividends Paid

## How It Works

**Pass 1 — TAG_MAP extraction**
Each variable has an ordered list of XBRL tag alternatives. The pipeline
tries each tag in order and takes the first one with a value for the target period.

**Pass 2 — Gemini fallback**
Variables still missing after Pass 1 are sent to Gemini in a single batched
call per company per period. Gemini either finds the value directly from
available tags or derives it from its exact components.

**Q4 computation**
Q4 is not reported in 10-Q filings. It is computed as:
`Q4 = Annual − Q1 − Q2 − Q3`

## Collection Progress

| Tier        | Companies | Status      |
|-------------|-----------|-------------|
| S&P 100     | ~100      | In progress |
| S&P 500     | ~500      | Pending     |
| Russell 1000| ~1,000    | Pending     |
| Russell 2000| ~2,000    | Pending     |

## Data Source

SEC EDGAR XBRL API — `https://data.sec.gov/api/xbrl/companyfacts/`

All data is sourced directly from official SEC filings. No third-party
data provider or subscription required.