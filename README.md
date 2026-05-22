# Financial Data Pipeline

![Daily Collection](https://github.com/ofoski/Financial-Analysis/actions/workflows/daily-collection.yml/badge.svg)

Automated collection of financial data for Russell 2000 companies.

## Overview

- 2,000 companies (Russell 2000 Index)
- 5 years of annual data
- 12 quarters of quarterly data  
- Historical stock prices on report dates
- 26 financial variables per period

## Collection Progress

![Companies Collected](https://img.shields.io/badge/companies-0%2F2000-blue)
![Success Rate](https://img.shields.io/badge/success%20rate-0%25-green)
![Last Updated](https://img.shields.io/badge/last%20updated-never-lightgrey)

**Status:** Collection not started  
**Successfully collected:** 0/2,000 companies  
**Failed:** 0 companies  
**Database size:** 0 MB

*Last collection run: Never*

## Financial Data Collected

Data is collected from three core financial statements:

### **Income Statement**
Revenue, Cost of Revenue, Gross Profit, R&D, SG&A, Operating Income, Interest Expense, Income Tax, Net Income, EPS Basic ($)

### **Balance Sheet**
Cash, Accounts Receivable, Inventory, Current Assets, Total Assets, Current Liabilities, Long-Term Debt, Total Liabilities, Equity

### **Cash Flow Statement**
Operating CF, CapEx, Dividends Paid, Depreciation, Stock-Based Comp, Stock Buybacks

### **Market Data**
Shares Outstanding (Basic), Stock prices on report dates

## Quick Links

- [View Collection Status](https://github.com/ofoski/Financial-Analysis/actions)
- [Download Database](https://github.com/ofoski/Financial-Analysis/actions)

## How It Works

Daily automated collection via GitHub Actions:
1. Runs at 2 AM UTC
2. Collects 35 companies per day
3. Saves to SQLite database
4. Uploads as downloadable artifact

## Setup

```bash
git clone https://github.com/YOUR-USERNAME/Financial-Analysis.git
cd Financial-Analysis
pip install -r requirements.txt
# Add FMP_API_KEY to config/.env
python collect_data.py
```

## Data Source

Financial Modeling Prep (FMP) API
