from src.collectors.financial_variables import FINANCIAL_VARIABLES

# Variables that do not apply to Real Estate or Financials.
# Verified by checking XBRL data for 10 representative companies per sector.
_NOT_APPLICABLE = {"Cost of Revenue", "Gross Profit", "R&D"}


def get_variables(sector):
    """
    Return the financial variable set for the given sector.
    Sectors not listed fall back to the full default FINANCIAL_VARIABLES.
    """
    if sector == "Real Estate":
        return {k: v for k, v in FINANCIAL_VARIABLES.items() if k not in _NOT_APPLICABLE}

    if sector == "Financials":
        variables = {k: v for k, v in FINANCIAL_VARIABLES.items() if k not in _NOT_APPLICABLE}
        # Banks report net interest income under this tag — add it before the default revenue tags
        variables["Revenue"] = ["RevenuesNetOfInterestExpense"] + FINANCIAL_VARIABLES["Revenue"]
        # Remove AccretionNet — negative for some insurers/PE firms (KKR, RNR)
        variables["Depreciation"] = [
            t for t in FINANCIAL_VARIABLES["Depreciation"]
            if t != "DepreciationAmortizationAndAccretionNet"
        ]
        return variables

    return FINANCIAL_VARIABLES
