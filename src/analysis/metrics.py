import sqlite3
import numpy as np
import pandas as pd


def load_data(db_path):
    """Load annual financials joined with prices from the database."""
    with sqlite3.connect(db_path) as conn:
        return pd.read_sql("""
            SELECT f.*, p.price
            FROM financial_data_annual f
            LEFT JOIN prices p ON f.ticker = p.ticker AND f.fiscal_year_end = p.date
            ORDER BY f.ticker, f.fiscal_year_end
        """, conn)


def compute_metrics(df):
    """Compute all per-company per-year metrics from raw financial and price data."""
    df = df.copy()

    # Revenue growth: year-over-year % change within each ticker
    df["revenue_growth"] = (
        df.groupby("ticker")["revenue"]
        .pct_change()
        .round(4)
    )

    # Margin ratios: each as a fraction of revenue
    df["gross_margin"]     = (df["gross_profit"]     / df["revenue"]).round(4)
    df["operating_margin"] = (df["operating_income"] / df["revenue"]).round(4)
    df["fcf_margin"]       = ((df["operating_cf"] - df["capex"]) / df["revenue"]).round(4)

    # P/S ratio: market cap (shares × price) divided by revenue
    df["ps_ratio"]    = (df["shares_diluted"] * df["price"] / df["revenue"]).round(4)

    # Debt to equity: financial risk indicator
    df["debt_equity"] = (df["total_debt"] / df["equity"]).round(4)

    # ROIC: operating profit per dollar of invested capital (equity + debt - cash)
    invested_capital = df["equity"] + df["total_debt"] - df["cash"]
    df["roic"]        = (df["operating_income"] / invested_capital).round(4)

    # Rule of 40: revenue growth % + FCF margin % — above 40 is healthy for growth companies
    df["rule_of_40"] = (df["revenue_growth"] * 100 + df["fcf_margin"] * 100).round(1)

    # Replace any division-by-zero infinities with NaN
    df = df.replace([np.inf, -np.inf], np.nan)

    return df[["ticker", "fiscal_year_end", "revenue_growth", "gross_margin",
               "operating_margin", "fcf_margin", "ps_ratio", "debt_equity",
               "roic", "rule_of_40", "price"]]


def save_metrics(db_path, df):
    """Write the metrics table to the database, replacing any previous run."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP VIEW IF EXISTS metrics")
        df.to_sql("metrics", conn, if_exists="replace", index=False)


def create_metrics_table(db_path):
    """Load financial data, compute all metrics, and save to the metrics table."""
    df = load_data(db_path)
    df = compute_metrics(df)
    save_metrics(db_path, df)
