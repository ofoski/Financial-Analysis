"""Real stock prices via yfinance - works for any real, currently
listed ticker, not just the companies in this project's local
database. Split/dividend-adjusted (auto_adjust=True) so a real stock
split (e.g. NVDA's 10-for-1 split in June 2024) doesn't look like the
price crashed 90% overnight - the adjusted price stays a true,
continuous reflection of what one share was actually worth the whole
time.
"""
from datetime import date as date_cls
from datetime import timedelta

import yfinance as yf


def get_live_price(ticker):
    """The real, current price right now. Returns None if the ticker
    isn't real/known."""
    info = yf.Ticker(ticker).fast_info
    try:
        price = info["lastPrice"]
        currency = info["currency"]
    except KeyError:
        return None
    return {"ticker": ticker, "date": "live", "price": price, "currency": currency}


def get_historical_price(ticker, on_date):
    """The real, split/dividend-adjusted closing price on the given
    date (YYYY-MM-DD). Markets aren't open every calendar day
    (weekends, holidays), so this looks at the real trading days in
    the week leading up to on_date and returns the closest one at or
    before it - the same "most recent real trading day" idea used
    elsewhere in this project for period-end dates. Returns None if no
    real trading day is found in that window, or the ticker isn't
    real/known."""
    target = date_cls.fromisoformat(on_date)
    start = target - timedelta(days=7)
    end = target + timedelta(days=1)
    hist = yf.Ticker(ticker).history(start=start.isoformat(), end=end.isoformat(), auto_adjust=True)
    if hist.empty:
        return None
    real_date = hist.index[-1].strftime("%Y-%m-%d")
    price = float(hist["Close"].iloc[-1])
    return {"ticker": ticker, "date": real_date, "price": price}


def get_price(ticker, on_date=None):
    """Real stock price for a ticker - the current live price if
    on_date is omitted, otherwise the real adjusted closing price on
    or just before that date."""
    ticker = ticker.strip().upper()
    if on_date is None:
        return get_live_price(ticker)
    return get_historical_price(ticker, on_date)
