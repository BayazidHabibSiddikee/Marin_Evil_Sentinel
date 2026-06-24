import requests
from bs4 import BeautifulSoup


def search_web(query: str, num_results: int = 5) -> str:
    """
    Searches the web and returns formatted results.
    Tries DuckDuckGo first, falls back to Google.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # Try DuckDuckGo first
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers=headers,
            timeout=8
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        result_blocks = soup.select(".result")

        if result_blocks:
            lines = []
            for i, block in enumerate(result_blocks[:num_results], 1):
                title_el = block.select_one(".result__a")
                snippet_el = block.select_one(".result__snippet")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                lines.append(f"{i}. {title}")
                if href:
                    lines.append(f"   {href}")
                if snippet:
                    lines.append(f"   {snippet}")
                lines.append("")
            if lines:
                return "\n".join(lines)
    except Exception:
        pass

    # Fallback: Google
    try:
        resp = requests.get(
            "https://www.google.com/search",
            params={"q": query, "num": num_results},
            headers=headers,
            timeout=10
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        lines = []
        count = 0
        for g in soup.select("div.g"):
            title_el = g.select_one("h3")
            link_el = g.select_one("a")
            snippet_el = g.select_one("div[data-sncf], div.VwiC3b, span.st")

            if not title_el or not link_el:
                continue

            count += 1
            title = title_el.get_text(strip=True)
            href = link_el.get("href", "")
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            lines.append(f"{count}. {title}")
            if href:
                lines.append(f"   {href}")
            if snippet:
                lines.append(f"   {snippet}")
            lines.append("")

            if count >= num_results:
                break

        if lines:
            return "\n".join(lines)
    except Exception:
        pass

    return "Search unavailable — DuckDuckGo and Google both failed."


def search_pdfs(query: str, num_results: int = 5) -> str:
    """Search specifically for downloadable PDFs."""
    return search_web(f"{query} filetype:pdf free download", num_results)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(search_web(" ".join(sys.argv[1:])))
    else:
        print("Usage: python3 web_search.py <query>")
