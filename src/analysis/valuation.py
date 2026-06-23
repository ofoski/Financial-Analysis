import sqlite3
import numpy as np
import pandas as pd


def load_data(db_path):
    """Load annual financials joined with prices from the database."""
    with sqlite3.connect(db_path) as conn:
        return pd.read_sql("""
            SELECT f.*, p.price
            FROM financial_data_clean f
            LEFT JOIN prices p ON f.ticker = p.ticker AND f.fiscal_year_end = p.date
            ORDER BY f.ticker, f.fiscal_year_end
        """, conn)


def compute_valuations(df):
    """Compute Graham Number, Owner Earnings Value, and PEG Fair Value per company per year."""
    df = df.copy()

    # Revenue growth per ticker — needed for PEG Fair Value
    df["revenue_growth"] = df.groupby("ticker")["revenue"].pct_change()

    # ── Graham Number ──────────────────────────────────────────────────────────
    # Formula: sqrt(22.5 × EPS Diluted × Book Value per Share)
    # 22.5 = Graham's constant (15× P/E × 1.5× P/B)
    # Only valid when EPS and equity are both positive
    graham_valid = (df["eps_diluted"] > 0) & (df["equity"] > 0) & (df["shares_diluted"] > 0)
    df["graham_number"] = np.nan
    df.loc[graham_valid, "graham_number"] = np.sqrt(
        22.5
        * df.loc[graham_valid, "eps_diluted"]
        * df.loc[graham_valid, "equity"]
        / df.loc[graham_valid, "shares_diluted"]
    ).round(4)

    # ── Owner Earnings Value ───────────────────────────────────────────────────
    # Formula: (Net Income + Depreciation − CapEx) / Shares Diluted × 15
    # 15× multiple = 6.7% earnings yield (Buffett's minimum acceptable return)
    # Only valid when owner earnings are positive
    owner_earnings = df["net_income"] + df["depreciation"] - df["capex"]
    oe_valid = (df["shares_diluted"] > 0) & (owner_earnings > 0)
    df["owner_earnings_value"] = np.nan
    df.loc[oe_valid, "owner_earnings_value"] = (
        owner_earnings[oe_valid] / df.loc[oe_valid, "shares_diluted"] * 15
    ).round(4)

    # ── PEG Fair Value ─────────────────────────────────────────────────────────
    # Formula: EPS Diluted × revenue_growth%
    # Fair P/E equals the growth rate (Peter Lynch principle)
    # Only valid when EPS and revenue growth are both positive
    peg_valid = (df["eps_diluted"] > 0) & (df["revenue_growth"] > 0)
    df["peg_fair_value"] = np.nan
    df.loc[peg_valid, "peg_fair_value"] = (
        df.loc[peg_valid, "eps_diluted"] * (df.loc[peg_valid, "revenue_growth"] * 100)
    ).round(4)

    # ── Price ratios ───────────────────────────────────────────────────────────
    # Actual price divided by fair value — below 1.0 means potentially undervalued
    df["price_to_graham"]         = (df["price"] / df["graham_number"]).round(4)
    df["price_to_owner_earnings"] = (df["price"] / df["owner_earnings_value"]).round(4)
    df["price_to_peg"]            = (df["price"] / df["peg_fair_value"]).round(4)

    # Replace any division-by-zero infinities with NaN
    df = df.replace([np.inf, -np.inf], np.nan)

    return df[["ticker", "fiscal_year_end", "price", "graham_number",
               "owner_earnings_value", "peg_fair_value",
               "price_to_graham", "price_to_owner_earnings", "price_to_peg"]]


def save_valuations(db_path, df):
    """Write the valuations table to the database, replacing any previous run."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP VIEW IF EXISTS valuations")
        df.to_sql("valuations", conn, if_exists="replace", index=False)


def create_valuation_table(db_path):
    """Load financial data, compute all valuations, and save to the valuations table."""
    df = load_data(db_path)
    df = compute_valuations(df)
    save_valuations(db_path, df)
