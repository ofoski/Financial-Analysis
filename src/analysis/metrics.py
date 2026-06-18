import sqlite3

_METRICS_VIEW_SQL = """
    CREATE VIEW IF NOT EXISTS metrics AS
    SELECT
        f.ticker,
        f.fiscal_year_end,
        ROUND(
            (f.revenue - LAG(f.revenue) OVER (PARTITION BY f.ticker ORDER BY f.fiscal_year_end))
            / NULLIF(ABS(LAG(f.revenue) OVER (PARTITION BY f.ticker ORDER BY f.fiscal_year_end)), 0),
            4
        ) AS revenue_growth,
        ROUND(f.gross_profit     / NULLIF(f.revenue, 0), 4) AS gross_margin,
        ROUND(f.operating_income / NULLIF(f.revenue, 0), 4) AS operating_margin,
        ROUND((f.operating_cf - f.capex) / NULLIF(f.revenue, 0), 4) AS fcf_margin,
        ROUND(f.shares_basic * p.price / NULLIF(f.revenue, 0), 4) AS ps_ratio,
        ROUND(f.total_debt / NULLIF(f.equity, 0), 4) AS debt_equity,
        p.price
    FROM financial_data_annual f
    LEFT JOIN prices p ON f.ticker = p.ticker AND f.fiscal_year_end = p.date
"""


def create_metrics_view(db_path):
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP VIEW IF EXISTS metrics")
        conn.execute(_METRICS_VIEW_SQL)
        conn.commit()
