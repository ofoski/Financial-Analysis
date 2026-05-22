"""
FinancialDatabase: SQLite database manager for financial data storage and retrieval.
"""

import sqlite3
from datetime import datetime
from pathlib import Path


class FinancialDatabase:
    """Manages SQLite database for storing and retrieving financial data."""
    
    def __init__(self, db_path="data/financials.db"):
        """
        Initialize database connection and create tables if they don't exist.
        
        Args:
            db_path (str): Path to SQLite database file. Default: data/financials.db
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create database if it doesn't exist
        self._create_tables()
    
    def _get_connection(self):
        """Create and return a database connection."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row  # Enable column access by name
        return conn
    
    def _create_tables(self):
        """Create database tables with proper schema."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Create companies table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS companies (
                    ticker TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    sector TEXT,
                    industry TEXT
                )
            ''')
            
            # Create financials_annual table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS financials_annual (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    fiscal_year_end TEXT NOT NULL,
                    revenue REAL,
                    cost_of_revenue REAL,
                    gross_profit REAL,
                    rd_expense REAL,
                    sga_expense REAL,
                    operating_income REAL,
                    interest_expense REAL,
                    income_tax REAL,
                    net_income REAL,
                    eps_basic REAL,
                    cash REAL,
                    accounts_receivable REAL,
                    inventory REAL,
                    current_assets REAL,
                    total_assets REAL,
                    current_liabilities REAL,
                    long_term_debt REAL,
                    total_liabilities REAL,
                    equity REAL,
                    operating_cf REAL,
                    capex REAL,
                    dividends_paid REAL,
                    depreciation REAL,
                    stock_based_comp REAL,
                    stock_buybacks REAL,
                    shares_outstanding REAL,
                    stock_price_on_date REAL,
                    collected_date TEXT NOT NULL,
                    FOREIGN KEY(ticker) REFERENCES companies(ticker),
                    UNIQUE(ticker, fiscal_year_end)
                )
            ''')
            
            # Create financials_quarterly table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS financials_quarterly (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    quarter_end_date TEXT NOT NULL,
                    fiscal_year TEXT NOT NULL,
                    fiscal_quarter TEXT NOT NULL,
                    revenue REAL,
                    cost_of_revenue REAL,
                    gross_profit REAL,
                    rd_expense REAL,
                    sga_expense REAL,
                    operating_income REAL,
                    interest_expense REAL,
                    income_tax REAL,
                    net_income REAL,
                    eps_basic REAL,
                    cash REAL,
                    accounts_receivable REAL,
                    inventory REAL,
                    current_assets REAL,
                    total_assets REAL,
                    current_liabilities REAL,
                    long_term_debt REAL,
                    total_liabilities REAL,
                    equity REAL,
                    operating_cf REAL,
                    capex REAL,
                    dividends_paid REAL,
                    depreciation REAL,
                    stock_based_comp REAL,
                    stock_buybacks REAL,
                    shares_outstanding REAL,
                    stock_price_on_date REAL,
                    collected_date TEXT NOT NULL,
                    FOREIGN KEY(ticker) REFERENCES companies(ticker),
                    UNIQUE(ticker, quarter_end_date)
                )
            ''')
            
            conn.commit()
    
    def add_company(self, ticker, name, sector, industry):
        """
        Add a company to the database.
        
        Args:
            ticker (str): Stock ticker symbol (e.g., 'AAPL')
            name (str): Company name (e.g., 'Apple Inc.')
            sector (str): Industry sector (e.g., 'Technology')
            industry (str): Specific industry (e.g., 'Consumer Electronics')
        
        Returns:
            bool: True if company was added, False if already exists
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute('''
                    INSERT INTO companies (ticker, name, sector, industry)
                    VALUES (:ticker, :name, :sector, :industry)
                ''', {
                    'ticker': ticker,
                    'name': name,
                    'sector': sector,
                    'industry': industry
                })
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                # Company already exists
                return False
    
    def save_annual_data(self, ticker, fiscal_year_end, financial_data, stock_price):
        """
        Save annual financial data for a company.
        
        Args:
            ticker (str): Stock ticker symbol
            fiscal_year_end (str): Fiscal year end date (ISO format: YYYY-MM-DD)
            financial_data (dict): Dictionary with 26 financial variables
            stock_price (float): Stock price on date
        
        Returns:
            bool: True if data was saved, False if duplicate
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                params = {
                    'ticker': ticker,
                    'fiscal_year_end': fiscal_year_end,
                    'stock_price_on_date': stock_price,
                    'collected_date': datetime.now().isoformat(),
                }
                # Add all financial variables
                params.update(financial_data)
                
                # Build INSERT statement dynamically
                columns = ', '.join(params.keys())
                placeholders = ', '.join([f':{key}' for key in params.keys()])
                
                cursor.execute(f'''
                    INSERT INTO financials_annual ({columns})
                    VALUES ({placeholders})
                ''', params)
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                # Duplicate entry (ticker, fiscal_year_end already exists)
                return False
    
    def save_quarterly_data(self, ticker, quarter_end_date, fiscal_year, 
                           fiscal_quarter, financial_data, stock_price):
        """
        Save quarterly financial data for a company.
        
        Args:
            ticker (str): Stock ticker symbol
            quarter_end_date (str): Quarter end date (ISO format: YYYY-MM-DD)
            fiscal_year (str): Fiscal year (e.g., '2024')
            fiscal_quarter (str): Fiscal quarter (e.g., 'Q1', 'Q2', 'Q3', 'Q4')
            financial_data (dict): Dictionary with 26 financial variables
            stock_price (float): Stock price on date
        
        Returns:
            bool: True if data was saved, False if duplicate
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                params = {
                    'ticker': ticker,
                    'quarter_end_date': quarter_end_date,
                    'fiscal_year': fiscal_year,
                    'fiscal_quarter': fiscal_quarter,
                    'stock_price_on_date': stock_price,
                    'collected_date': datetime.now().isoformat(),
                }
                # Add all financial variables
                params.update(financial_data)
                
                # Build INSERT statement dynamically
                columns = ', '.join(params.keys())
                placeholders = ', '.join([f':{key}' for key in params.keys()])
                
                cursor.execute(f'''
                    INSERT INTO financials_quarterly ({columns})
                    VALUES ({placeholders})
                ''', params)
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                # Duplicate entry (ticker, quarter_end_date already exists)
                return False
    
    def get_incomplete_companies(self, limit=35):
        """
        Get companies with incomplete data.
        
        Args:
            limit (int): Maximum number of companies to return (default: 35)
        
        Returns:
            list: List of dicts with ticker, name, sector, industry
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            query = '''
                SELECT 
                    c.ticker,
                    c.name,
                    c.sector,
                    c.industry
                FROM companies c
                LEFT JOIN financials_annual a ON c.ticker = a.ticker
                LEFT JOIN financials_quarterly q ON c.ticker = q.ticker
                GROUP BY c.ticker
                HAVING COUNT(DISTINCT a.id) < 5 OR COUNT(DISTINCT q.id) < 12
                ORDER BY c.ticker
                LIMIT :limit
            '''
            
            cursor.execute(query, {'limit': limit})
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def get_stats(self):
        """
        Get database statistics.
        
        Returns:
            dict: Statistics including total companies, annual records, quarterly records
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            companies_count = cursor.execute(
                'SELECT COUNT(*) FROM companies'
            ).fetchone()[0]
            
            annual_count = cursor.execute(
                'SELECT COUNT(*) FROM financials_annual'
            ).fetchone()[0]
            
            quarterly_count = cursor.execute(
                'SELECT COUNT(*) FROM financials_quarterly'
            ).fetchone()[0]
            
            # Get companies with complete data (5+ annual AND 12+ quarterly)
            complete_query = '''
                SELECT COUNT(DISTINCT c.ticker)
                FROM companies c
                WHERE (SELECT COUNT(*) FROM financials_annual a WHERE a.ticker = c.ticker) >= 5
                AND (SELECT COUNT(*) FROM financials_quarterly q WHERE q.ticker = c.ticker) >= 12
            '''
            complete_count = cursor.execute(complete_query).fetchone()[0]
            
            return {
                'total_companies': companies_count,
                'annual_records': annual_count,
                'quarterly_records': quarterly_count,
                'complete_companies': complete_count,
                'incomplete_companies': companies_count - complete_count,
                'database_path': str(self.db_path)
            }
    
    def get_company(self, ticker):
        """
        Get company information by ticker.
        
        Args:
            ticker (str): Stock ticker symbol
        
        Returns:
            dict: Company information or None if not found
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM companies WHERE ticker = :ticker', {'ticker': ticker})
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def close(self):
        """Close database connection."""
        # Connection is managed by context manager, this is optional cleanup
        pass
