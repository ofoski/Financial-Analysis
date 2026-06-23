import sqlite3
import pandas as pd
from pathlib import Path

DB_PATH = Path("data/financials.db")
SPLIT_THRESHOLD = 1.8  # year-over-year share increase above this is treated as a split


def _build_ratio_series(df):
    """Return a Series of cumulative split ratios (1.0 = no adjustment) indexed like df."""
    ratios = pd.Series(1.0, index=df.index)

    for ticker, group in df.groupby("ticker"):
        shares = group["shares_diluted"].values
        idx    = group.index.tolist()
        years  = group["fiscal_year_end"].tolist()

        for i in range(1, len(shares)):
            prev, curr = shares[i - 1], shares[i]
            if pd.notna(prev) and pd.notna(curr) and curr / prev > SPLIT_THRESHOLD:
                ratio = round(curr / prev)
                if 2 <= ratio <= 25:
                    corrected_years = [y[:4] for y in years[:i]]
                    for j in range(i):
                        ratios[idx[j]] *= ratio
                    print(f"  {ticker}: {ratio}:1 split detected at {years[i][:4]}"
                          f" — correcting years: {', '.join(corrected_years)}")

    return ratios


def create_clean_table(db_path):
    """Read raw data, apply split corrections in memory, write to financial_data_clean.

    financial_data_annual is never modified — it stays as the original collected data.
    """
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql(
            "SELECT * FROM financial_data_annual ORDER BY ticker, fiscal_year_end", conn
        )

        print("Scanning for stock splits...")
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
