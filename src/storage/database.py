import sqlite3
from pathlib import Path

COLUMN_MAP = {
    "Revenue":             "revenue",
    "Cost of Revenue":     "cost_of_revenue",
    "Gross Profit":        "gross_profit",
    "R&D":                 "rd",
    "SG&A":                "sga",
    "Operating Income":    "operating_income",
    "Interest Expense":    "interest_expense",
    "Pre-tax Income":      "pretax_income",
    "Income Tax":          "income_tax",
    "Net Income":          "net_income",
    "EPS Basic":           "eps_basic",
    "EPS Diluted":         "eps_diluted",
    "Shares Basic":        "shares_basic",
    "Shares Diluted":      "shares_diluted",
    "Cash":                "cash",
    "Accounts Receivable": "accounts_receivable",
    "Inventory":           "inventory",
    "Goodwill":            "goodwill",
    "Current Assets":      "current_assets",
    "Total Assets":        "total_assets",
    "Current Liabilities": "current_liabilities",
    "Total Debt":          "total_debt",
    "Total Liabilities":   "total_liabilities",
    "Equity":              "equity",
    "Operating CF":        "operating_cf",
    "CapEx":               "capex",
    "Depreciation":        "depreciation",
    "Stock-Based Comp":    "stock_based_comp",
    "Stock Buybacks":      "stock_buybacks",
    "Dividends Paid":      "dividends_paid",
}


def init_db(db_path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    columns = ",\n        ".join(f"{col} REAL" for col in COLUMN_MAP.values())

    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                ticker TEXT PRIMARY KEY,
                name   TEXT,
                sector TEXT
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS financial_data_annual (
                id              INTEGER PRIMARY KEY,
                ticker          TEXT NOT NULL,
                fiscal_year_end TEXT NOT NULL,
                {columns},
                collected_date  TEXT,
                FOREIGN KEY(ticker) REFERENCES companies(ticker),
                UNIQUE(ticker, fiscal_year_end)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                ticker TEXT NOT NULL,
                date   TEXT NOT NULL,
                price  REAL,
                PRIMARY KEY (ticker, date),
                FOREIGN KEY (ticker) REFERENCES companies(ticker)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS validation (
                ticker          TEXT NOT NULL,
                fiscal_year_end TEXT NOT NULL,
                check_name      TEXT NOT NULL,
                detail          TEXT,
                PRIMARY KEY (ticker, fiscal_year_end, check_name)
            )
        """)
        conn.commit()
    return db_path


def save_company(db_path, ticker, name=None, sector=None):
    name = " ".join(w.capitalize() for w in name.split()) if name else None
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            INSERT INTO companies (ticker, name, sector) VALUES (?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                name   = COALESCE(excluded.name,   name),
                sector = COALESCE(excluded.sector, sector)
        """, (ticker, name, sector))
        conn.commit()


def save_annual(db_path, ticker, fiscal_year_end, data, collected_date=None):
    cols   = list(data.keys()) + ["collected_date"]
    vals   = list(data.values()) + [collected_date]
    col_names    = ", ".join(["ticker", "fiscal_year_end"] + cols)
    placeholders = ", ".join(["?", "?"] + ["?"] * len(cols))
    updates      = ", ".join(f"{c} = COALESCE({c}, excluded.{c})" for c in data.keys())
    updates     += ", collected_date = excluded.collected_date"

    with sqlite3.connect(db_path) as conn:
        conn.execute(f"""
            INSERT INTO financial_data_annual ({col_names})
            VALUES ({placeholders})
            ON CONFLICT(ticker, fiscal_year_end) DO UPDATE SET {updates}
        """, [ticker, fiscal_year_end] + vals)
        conn.commit()
