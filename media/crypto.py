#!/usr/bin/env python3
# media/crypto.py — Live crypto price tracker, runs as its own process
# Usage: python crypto.py bitcoin

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tkinter as tk
import requests
import arrow

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def run(currency: str = "bitcoin"):
    url = (f"https://api.coingecko.com/api/v3/simple/price"
           f"?ids={currency}&vs_currencies=usd")
    root = tk.Tk()
    root.title(f"{currency.title()} Watch")
    root.geometry("400x200")

    label_time  = tk.Label(root, text='', fg='Blue',  font=("Helvetica", 24))
    label_price = tk.Label(root, text='', fg='Red',   font=("Helvetica", 22))
    label_time.pack(pady=10)
    label_price.pack()

    def update():
        try:
            data = requests.get(url, headers=HEADERS, timeout=5).json()
            if currency in data:
                price = data[currency]['usd']
                label_time.configure(
                    text=f"{arrow.now().format('DD-MM-YYYY')}\n{arrow.now().format('HH:mm:ss')}"
                )
                label_price.configure(text=f"{currency.title()}: ${price:,.2f}")
            else:
                label_price.configure(text=f"'{currency}' not found")
        except Exception as e:
            label_price.configure(text=f"Error: {e}")
        root.after(1000, update)

    update()
    root.mainloop()


if __name__ == '__main__':
    currency = sys.argv[1] if len(sys.argv) > 1 else "bitcoin"
    run(currency)
