import sqlite3
import pandas as pd
import yfinance as yf
from pathlib import Path

DB_PATH = Path("data/financials.db")
SPLIT_THRESHOLD = 1.8


def _fetch_splits(ticker):
    """Use yfinance to get all confirmed stock splits for a ticker.

    Splits below 2 are company restructuring events that look like splits
    but do not actually change the share count in the same way.
    """
    try:
        splits = yf.Ticker(ticker).splits
        return splits[splits >= 2]
    except Exception:
        return pd.Series(dtype=float)


def _find_split_in_window(splits, date_prev, date_curr, applied_dates):
    """Find the timing and ratio of a split between two fiscal year end dates.

    Searches up to 24 months after date_curr because a split can happen after
    the fiscal year closes and still appear as a jump in the next report.
    For companies with multiple splits, applied_dates ensures each split is
    only counted once. Returns None if no split is found in the window.
    """
    start = pd.Timestamp(date_prev)
    end   = pd.Timestamp(date_curr) + pd.DateOffset(months=24)
    index = splits.index.tz_localize(None)
    mask  = (index > start) & (index <= end) & (~index.isin(applied_dates))
    window_vals  = splits.values[mask]
    window_dates = index[mask]
    if len(window_vals) == 0:
        return None, []
    compound = 1.0
    for r in window_vals:
        compound *= r
    return round(compound), list(window_dates)


def _build_ratio_series(df):
    """Find the split ratio for each row, returning 1.0 when no split occurred.

    Detects a large jump in share count between two years and confirms it is
    a real stock split via yfinance. Only the years before the split get a
    ratio greater than 1.
    """
    ratios = pd.Series(1.0, index=df.index)

    for ticker, group in df.groupby("ticker"):
        shares = group["shares_diluted"].values
        idx    = group.index.tolist()
        years  = group["fiscal_year_end"].tolist()

        splits        = _fetch_splits(ticker)
        applied_dates = []

        for i in range(1, len(shares)):
            prev, curr = shares[i - 1], shares[i]
            if not (pd.notna(prev) and pd.notna(curr) and curr / prev > SPLIT_THRESHOLD):
                continue

            yf_ratio, new_dates = _find_split_in_window(splits, years[i - 1], years[i], applied_dates)
            if yf_ratio is None:
                print(f"  {ticker}: jump at {years[i][:4]} not confirmed by yfinance, skipping (dilution)")
                continue

            applied_dates.extend(new_dates)
            corrected = [y[:4] for y in years[:i]]
            for j in range(i):
                ratios[idx[j]] *= yf_ratio

            print(f"  {ticker}: {yf_ratio}:1 split confirmed at {years[i][:4]}, correcting years: {', '.join(corrected)}")

    return ratios


def create_clean_table(db_path):
    """Apply split corrections to shares and EPS and save as financial_data_clean.

    Only shares and EPS are adjusted. All other columns are not affected by splits.
    """
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql(
            "SELECT * FROM financial_data_annual ORDER BY ticker, fiscal_year_end", conn
        )

        print("Scanning for stock splits...\n")
        ratios = _build_ratio_series(df)

        mask = ratios > 1
        df.loc[mask, "shares_basic"]   = (df.loc[mask, "shares_basic"]   * ratios[mask]).round(3)
        df.loc[mask, "shares_diluted"] = (df.loc[mask, "shares_diluted"] * ratios[mask]).round(3)
        df.loc[mask, "eps_basic"]      = (df.loc[mask, "eps_basic"]      / ratios[mask]).round(4)
        df.loc[mask, "eps_diluted"]    = (df.loc[mask, "eps_diluted"]    / ratios[mask]).round(4)

        conn.execute("DROP TABLE IF EXISTS financial_data_clean")
        df.to_sql("financial_data_clean", conn, if_exists="replace", index=False)

        print(f"\nfinancial_data_clean created: {len(df)} rows, "
              f"{df[mask]['ticker'].nunique()} companies with split corrections applied.")


if __name__ == "__main__":
    create_clean_table(DB_PATH)
