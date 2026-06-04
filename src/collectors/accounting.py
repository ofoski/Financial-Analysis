import sqlite3


def apply_accounting_identities(db_path, ticker):
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

            # Gross Profit = Revenue - Cost of Revenue
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

            # Cost of Revenue = Revenue - Gross Profit
            effective_gp = updates.get("gross_profit", gp)
            if cogs is None and "cost_of_revenue" not in updates:
                if revenue is not None and effective_gp is not None:
                    derived = revenue - effective_gp
                    if derived >= 0:
                        updates["cost_of_revenue"] = derived

            # Pre-tax Income = Net Income + Income Tax
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
