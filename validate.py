import sqlite3
from pathlib import Path

DB_PATH = Path("data/financials.db")


def run_validation(db_path):
    """Check every row in financial_data_clean against accounting identities, sign, bound, and year-over-year rules."""
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE IF NOT EXISTS validation (
                ticker          TEXT NOT NULL,
                fiscal_year_end TEXT NOT NULL,
                check_name      TEXT NOT NULL,
                detail          TEXT,
                PRIMARY KEY (ticker, fiscal_year_end, check_name)
            )
        """)
        conn.execute("DELETE FROM validation")

        rows = conn.execute(
            "SELECT * FROM financial_data_clean ORDER BY ticker, fiscal_year_end"
        ).fetchall()

        failures = []
        prev = {}

        for row in rows:
            ticker = row["ticker"]
            fy_end = row["fiscal_year_end"]

            def fail(check_name, detail):
                failures.append((ticker, fy_end, check_name, detail))

            # ── Accounting identities ──────────────────────────────────────────────

            # Formula: Revenue - Cost of Revenue = Gross Profit (tolerance ±0.5%)
            if all(row[c] is not None for c in ["revenue", "cost_of_revenue", "gross_profit"]) and row["revenue"] != 0:
                pct = abs(row["revenue"] - row["cost_of_revenue"] - row["gross_profit"]) / abs(row["revenue"])
                if pct > 0.005:
                    fail("gross_identity", f"revenue {row['revenue']} - cost_of_revenue {row['cost_of_revenue']} != gross_profit {row['gross_profit']} (diff {pct:.1%})")

            # Formula: Net Income / Shares Basic ≈ EPS Basic (tolerance ±30% — accounts for noncontrolling interests)
            if all(row[c] is not None for c in ["net_income", "shares_basic", "eps_basic"]) and row["shares_basic"] and row["eps_basic"]:
                calculated = row["net_income"] / row["shares_basic"]
                pct = abs(calculated - row["eps_basic"]) / abs(row["eps_basic"])
                if pct > 0.30:
                    fail("eps_basic_crosscheck", f"net_income/shares_basic = {calculated:.2f} != eps_basic {row['eps_basic']} (diff {pct:.1%})")

            # Formula: Net Income / Shares Diluted ≈ EPS Diluted (tolerance ±30%)
            if all(row[c] is not None for c in ["net_income", "shares_diluted", "eps_diluted"]) and row["shares_diluted"] and row["eps_diluted"]:
                calculated = row["net_income"] / row["shares_diluted"]
                pct = abs(calculated - row["eps_diluted"]) / abs(row["eps_diluted"])
                if pct > 0.30:
                    fail("eps_diluted_crosscheck", f"net_income/shares_diluted = {calculated:.2f} != eps_diluted {row['eps_diluted']} (diff {pct:.1%})")

            # ── Sign checks ────────────────────────────────────────────────────────

            # Revenue, Total Assets, Shares Basic, CapEx must always be positive
            for col in ["revenue", "total_assets", "shares_basic", "capex"]:
                if row[col] is not None and row[col] <= 0:
                    fail(f"sign_{col}", f"{col} = {row[col]}")

            # Total Debt must be zero or positive (cannot owe negative debt)
            if row["total_debt"] is not None and row["total_debt"] < 0:
                fail("sign_total_debt", f"total_debt = {row['total_debt']}")

            # ── Bound checks ───────────────────────────────────────────────────────

            # Formula: Gross Profit / Revenue — must be between -50% and 100%
            if row["revenue"] and row["gross_profit"] is not None:
                margin = row["gross_profit"] / row["revenue"]
                if not (-0.5 <= margin <= 1.0):
                    fail("gross_margin_bound", f"gross_profit {row['gross_profit']} / revenue {row['revenue']} = {margin:.1%}")

            # Formula: Operating Income / Revenue — must be between -200% and 100%
            if row["revenue"] and row["operating_income"] is not None:
                margin = row["operating_income"] / row["revenue"]
                if not (-2.0 <= margin <= 1.0):
                    fail("operating_margin_bound", f"operating_income {row['operating_income']} / revenue {row['revenue']} = {margin:.1%}")

            # ── Relationship checks ────────────────────────────────────────────────

            # Operating Income = Gross Profit - Operating Expenses, so it can never exceed Gross Profit
            if row["operating_income"] is not None and row["gross_profit"] is not None:
                if row["operating_income"] > row["gross_profit"]:
                    fail("operating_vs_gross", f"operating_income {row['operating_income']} > gross_profit {row['gross_profit']}")

            # ── Year-over-year checks ──────────────────────────────────────────────

            # Formula: (Revenue_this - Revenue_prev) / Revenue_prev — flag if change > 300%
            prev_row = prev.get(ticker)
            if prev_row and row["revenue"] is not None and prev_row["revenue"] is not None and prev_row["revenue"] != 0:
                change = (row["revenue"] - prev_row["revenue"]) / abs(prev_row["revenue"])
                if abs(change) > 3.0:
                    fail("revenue_yoy", f"change {change:.1%}")
                # Flag if revenue is identical to previous year — likely a copy error
                elif row["revenue"] == prev_row["revenue"]:
                    fail("revenue_duplicate", "same value as previous year")

            prev[ticker] = dict(row)

        conn.executemany(
            "INSERT INTO validation (ticker, fiscal_year_end, check_name, detail) VALUES (?, ?, ?, ?)",
            failures,
        )
        conn.commit()

    print(f"Validation complete: {len(failures)} issues flagged.")


if __name__ == "__main__":
    run_validation(DB_PATH)
