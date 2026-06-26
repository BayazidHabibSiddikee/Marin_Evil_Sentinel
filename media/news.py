#!/usr/bin/env python3
# media/news.py — runs as its own process
# Opens a news website in the default browser.
import sys
import webbrowser
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.tts import speak_male as talk2


def open_news():
    # Try multiple news sources
    sources = [
        "https://www.bbc.com/news",
        "https://www.aljazeera.com",
        "https://www.ndtv.com",
    ]
    for url in sources:
        try:
            talk2(f"Opening news from {url.split('://')[1].split('.')[0]}.")
            webbrowser.open(url)
            return
        except Exception:
            continue
    talk2("Could not open news.")


if __name__ == '__main__':
    open_news()
