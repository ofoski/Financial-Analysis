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


def apply_accounting_identities(db_path, ticker):
    """
    Fill null values using accounting identities (pure arithmetic on DB values).
    Only fills a column if it is currently null and both inputs are present.
    Runs after XBRL extraction is complete for a ticker.
    """
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, revenue, cost_of_revenue, gross_profit, "
            "operating_income, rd, sga, "
            "net_income, income_tax, pretax_income, "
            "total_assets, equity, total_liabilities "
            "FROM financial_data_annual WHERE ticker = ?",
            (ticker,)
        ).fetchall()

        for row in rows:
            id_, revenue, cogs, gp, op_inc, rd, sga, net_inc, tax, pretax, assets, eq, liabs = row
            updates = {}

            # Gross Profit = Revenue - Cost of Revenue (and permutations)
            if gp is None and revenue is not None and cogs is not None:
                updates["gross_profit"] = revenue - cogs
            if cogs is None and revenue is not None and gp is not None:
                derived = revenue - gp
                if derived >= 0:
                    updates["cost_of_revenue"] = derived
            if revenue is None and gp is not None and cogs is not None:
                updates["revenue"] = gp + cogs

            # Gross Profit = Operating Income + R&D + SG&A
            if gp is None and "gross_profit" not in updates:
                if op_inc is not None and rd is not None and sga is not None:
                    derived_gp = op_inc + rd + sga
                    if derived_gp >= 0:
                        updates["gross_profit"] = derived_gp

            # Cost of Revenue = Revenue - Gross Profit (using newly derived GP if needed)
            effective_gp = updates.get("gross_profit", gp)
            if cogs is None and "cost_of_revenue" not in updates:
                if revenue is not None and effective_gp is not None:
                    derived = revenue - effective_gp
                    if derived >= 0:
                        updates["cost_of_revenue"] = derived

            # Pre-tax Income = Net Income + Income Tax (and permutations)
            if pretax is None and net_inc is not None and tax is not None:
                updates["pretax_income"] = net_inc + tax
            if net_inc is None and pretax is not None and tax is not None:
                updates["net_income"] = pretax - tax
            if tax is None and pretax is not None and net_inc is not None:
                updates["income_tax"] = pretax - net_inc

            # Total Liabilities = Total Assets - Equity
            if liabs is None and assets is not None and eq is not None:
                derived = assets - eq
                if derived >= 0:
                    updates["total_liabilities"] = derived

            if updates:
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE financial_data_annual SET {set_clause} WHERE id = ?",
                    [*updates.values(), id_]
                )

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
