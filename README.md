# Financial Analysis Pipeline

Collects 10 years of fundamental financial data for Russell 3000 companies from SEC EDGAR, extracted by DeepSeek V4 Flash LLM.

## How It Works

1. **Fetch filings** — `edgar.py` downloads `FilingSummary.xml` for each 10-K to locate the income statement, balance sheet, and cash flow HTML files.
2. **Extract data** — `extractor.py` sends the three HTML tables as plain text to DeepSeek V4 Flash (Azure), which returns all 30 variables for every fiscal year shown in the filing.
3. **Every-2nd-filing strategy** — each 10-K covers 2–3 years. By selecting every other filing (e.g. 2025, 2023, 2021, 2019, 2017), 10 complete years are collected with balance sheet overlap filled in.
4. **Store** — results are saved to SQLite (`data/financials.db`). Re-runs are safe — existing rows are preserved.
5. **Audit log** — every extracted value, its source label, and the raw tables are written to `logs/audit.jsonl` for inspection and future fine-tuning.

## Financial Variables (30 total)

**Income Statement:** Revenue, Cost of Revenue, Gross Profit, R&D, SG&A, Operating Income, Interest Expense, Pre-tax Income, Income Tax, Net Income, EPS Basic, EPS Diluted, Shares Basic, Shares Diluted

**Balance Sheet:** Cash, Accounts Receivable, Inventory, Goodwill, Current Assets, Total Assets, Current Liabilities, Total Debt, Total Liabilities, Equity

**Cash Flow:** Operating CF, CapEx, Depreciation, Stock-Based Comp, Stock Buybacks, Dividends Paid

## Data Validation

Run `validate.py` after collection to check data quality. Failures are written to the `validation` table in the database. Empty table means clean data.

**Checks performed:**

| Check | Formula |
|---|---|
| `gross_identity` | Revenue − Cost of Revenue = Gross Profit (±0.5%) |
| `eps_basic_crosscheck` | Net Income / Shares Basic ≈ EPS Basic (±30%) |
| `eps_diluted_crosscheck` | Net Income / Shares Diluted ≈ EPS Diluted (±30%) |
| `sign_revenue` | Revenue > 0 |
| `sign_total_assets` | Total Assets > 0 |
| `sign_shares_basic` | Shares Basic > 0 |
| `sign_capex` | CapEx > 0 |
| `sign_total_debt` | Total Debt ≥ 0 |
| `gross_margin_bound` | Gross Profit / Revenue between −50% and 100% |
| `operating_margin_bound` | Operating Income / Revenue between −200% and 100% |
| `operating_vs_gross` | Operating Income ≤ Gross Profit |
| `revenue_yoy` | YoY revenue change ≤ 300% |
| `revenue_duplicate` | Revenue not identical to previous year |


## Metrics View

A SQL view `metrics` is created automatically with: `revenue_growth`, `gross_margin`, `operating_margin`, `fcf_margin`, `ps_ratio`, `debt_equity`, `price`.

## Project Structure

```
Financial-Analysis/
├── main.py                        # Pipeline runner
├── validate.py                    # Data quality checks
├── collect_prices.py              # Stock price collection (run after main.py)
├── requirements.txt
├── config/
│   └── .env                       # API keys (not committed)
├── data/
│   └── financials.db              # SQLite output
├── logs/
│   └── audit.jsonl                # Extracted values with source labels and raw tables
└── src/
    ├── collectors/
    │   ├── edgar.py               # SEC EDGAR fetching
    │   └── extractor.py           # DeepSeek V4 Flash extraction
    ├── storage/
    │   └── database.py            # Schema and save helpers
    └── analysis/
        └── metrics.py             # SQL metrics view
```

## Setup

```bash
pip install -r requirements.txt
```

Create `config/.env`:
```
AZURE_DEEPSEEK_V4_ENDPOINT=https://...
AZURE_DEEPSEEK_V4_API_KEY=...
```

## Usage

```bash
# Collect financial data
python main.py

# Check data quality
python validate.py

# Collect stock prices (after financial data is collected)
python collect_prices.py
```

Configure `main.py` before running:
```python
SECTOR_FILTER = ["Information Technology"]   # [] for all sectors
N_ANNUAL      = 10                           # years per company
TRIAL_LIMIT   = None                         # set to N to test on first N companies
```

Progress is saved to `progress.json` — safe to stop and re-run at any time.
