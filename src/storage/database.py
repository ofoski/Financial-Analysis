import sqlite3
from pathlib import Path

DB_PATH = Path("data/financials.db")

# Maps the display name used in FINANCIAL_VARIABLES to the DB column name
COLUMN_MAP = {
    "Revenue":            "revenue",
    "Cost of Revenue":    "cost_of_revenue",
    "Gross Profit":       "gross_profit",
    "R&D":                "rd",
    "SG&A":               "sga",
    "Operating Income":   "operating_income",
    "Interest Expense":   "interest_expense",
    "Pre-tax Income":     "pretax_income",
    "Income Tax":         "income_tax",
    "Net Income":         "net_income",
    "EPS Basic":          "eps_basic",
    "EPS Diluted":        "eps_diluted",
    "Cash":               "cash",
    "Accounts Receivable": "accounts_receivable",
    "Inventory":          "inventory",
    "Goodwill":           "goodwill",
    "Current Assets":     "current_assets",
    "Total Assets":       "total_assets",
    "Current Liabilities": "current_liabilities",
    "Total Debt":         "total_debt",
    "Total Liabilities":  "total_liabilities",
    "Equity":             "equity",
    "Operating CF":       "operating_cf",
    "CapEx":              "capex",
    "Depreciation":       "depreciation",
    "Stock-Based Comp":   "stock_based_comp",
    "Stock Buybacks":     "stock_buybacks",
    "Dividends Paid":     "dividends_paid",
}


def init_db(db_path=DB_PATH):
    """
    Create the database and both tables if they don't exist.
    - companies: one row per company (ticker, name, sector)
    - financial_data_annual: one row per company per fiscal year, one column per financial variable
    """
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
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
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
                ticker  TEXT NOT NULL,
                date    TEXT NOT NULL,
                price   REAL,
                PRIMARY KEY (ticker, date),
                FOREIGN KEY (ticker) REFERENCES companies(ticker)
            )
        """)

        conn.commit()
    return db_path


def _normalize_name(name):
    if name is None:
        return None
    return " ".join(w.capitalize() for w in name.split())


def upsert_company(db_path, ticker, name=None, sector=None):
    """
    Insert or update a company record.
    Only updates name/sector if a non-None value is provided.
    """
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            INSERT INTO companies (ticker, name, sector)
            VALUES (?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                name   = COALESCE(excluded.name,   name),
                sector = COALESCE(excluded.sector, sector)
        """, (ticker, _normalize_name(name), sector))
        conn.commit()


def upsert_annual(db_path, ticker, fiscal_year_end, data, collected_date=None):
    """
    Insert or update one year of annual financial data for a company.
    data is a dict mapping DB column names (from COLUMN_MAP values) to values.
    Any column not in data is left as NULL.
    """
    cols = list(data.keys()) + ["collected_date"]
    vals = list(data.values()) + [collected_date]

    col_names  = ", ".join(["ticker", "fiscal_year_end"] + cols)
    placeholders = ", ".join(["?", "?"] + ["?"] * len(cols))
    updates    = ", ".join(f"{c} = excluded.{c}" for c in cols)

    with sqlite3.connect(db_path) as conn:
        conn.execute(f"""
            INSERT INTO financial_data_annual ({col_names})
            VALUES ({placeholders})
            ON CONFLICT(ticker, fiscal_year_end) DO UPDATE SET {updates}
        """, [ticker, fiscal_year_end] + vals)
        conn.commit()
