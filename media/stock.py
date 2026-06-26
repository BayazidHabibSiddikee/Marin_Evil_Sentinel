#!/usr/bin/env python3
# media/stock.py — Stock price + graph, runs as its own process
# Usage: python stock.py "Apple"   OR   python stock.py --ticker AAPL

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
import arrow
import yfinance as yf
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from utils.tts import speak_male as talk2, speak_female as talk1


def get_ticker(company_name: str) -> str | None:
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={company_name}"
        res = requests.get(url, headers=headers, timeout=10).json()
        quotes = res.get('quotes', [])
        return quotes[0]['symbol'] if quotes else None
    except Exception as e:
        print(f"Ticker lookup error: {e}")
        return None


def show_stock(ticker_symbol: str):
    try:
        obj = yf.Ticker(ticker_symbol)
        price = obj.info.get("regularMarketPrice")
        name = obj.info.get("longName", ticker_symbol)
        if price is None:
            talk1(f"Could not retrieve price for {ticker_symbol}")
            return
        talk2(f"{name} stock price is ${price}")
        e_date = arrow.now().format("YYYY-MM-DD")
        s_date = arrow.now().shift(days=-30).format("YYYY-MM-DD")
        data = obj.history(start=s_date, end=e_date)
        if data.empty:
            talk1("No historical data found.")
            return
        data = data.reset_index()
        data['Date_num'] = mdates.date2num(data['Date'])
        fig, ax = plt.subplots(figsize=(10, 6), dpi=128)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d/%Y'))
        ax.plot(data['Date_num'], data['Close'], c='blue', linewidth=2, label='Close Price')
        ax.set_title(f"{name} ({ticker_symbol})", fontsize=16, fontweight='bold')
        ax.set_xlabel('Date'); ax.set_ylabel("Price ($)")
        fig.autofmt_xdate(rotation=45)
        ax.grid(True, alpha=0.3); ax.legend()
        plt.tight_layout(); plt.show()
    except Exception as e:
        talk2(f"Error: {e}")


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        talk1("No company provided.")
        sys.exit(1)
    if args[0] == '--ticker':
        show_stock(args[1].upper())
    else:
        company = ' '.join(args)
        talk2(f"Looking up ticker for {company}")
        ticker = get_ticker(company)
        if ticker:
            show_stock(ticker)
        else:
            talk1(f"Could not find ticker for {company}")
