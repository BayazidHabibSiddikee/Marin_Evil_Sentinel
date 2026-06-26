#!/usr/bin/env python3
# tools/resource_tool.py — Unified download/analyze: PDFs, webpages, repos

import os
import re
import time
import subprocess
import requests
from urllib.parse import urlparse

CACHE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "storage", "cache", "resources"))
BOOKS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "books"))


def _clean_old_caches():
    if not os.path.exists(CACHE_DIR):
        return
    now = time.time()
    for item in os.listdir(CACHE_DIR):
        p = os.path.join(CACHE_DIR, item)
        if os.path.isdir(p) and now - os.path.getmtime(p) > 172800:
            try:
                import shutil
                shutil.rmtree(p)
            except:
                pass


def resource_download_analyze(url: str) -> str:
    """
    Unified tool: download or analyze any URL.
    - .pdf → downloads to books/, indexes into RAG, returns summary
    - github/gitlab → clones repo, returns README + structure
    - other → fetches webpage content, caches text
    Then returns the content for Marin to analyze.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    os.makedirs(BOOKS_DIR, exist_ok=True)
    _clean_old_caches()

    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower()

    # ── PDF: download + index ──
    if path.endswith(".pdf") or _check_url_is_pdf(url):
        return _download_pdf(url)

    # ── Git repo: clone + README ──
    if any(d in domain for d in ["github.com", "gitlab.com"]) or url.endswith(".git"):
        return _clone_repo(url)

    # ── Webpage: fetch + extract text ──
    return _fetch_webpage(url)


def _check_url_is_pdf(url: str) -> bool:
    try:
        r = requests.head(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8, allow_redirects=True)
        ct = r.headers.get("Content-Type", "")
        return "pdf" in ct.lower()
    except:
        return False


def _extract_direct_pdf_url(url: str) -> str:
    m = re.match(r"https?://archive\.org/details/([^/?]+)", url)
    if m:
        return f"https://archive.org/download/{m.group(1)}/{m.group(1)}.pdf"
    if "drive.google.com" in url:
        m2 = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
        if m2:
            return f"https://drive.google.com/uc?export=download&id={m2.group(1)}"
    return url


def _download_pdf(url: str) -> str:
    filename = os.path.basename(urlparse(url).path)
    if not filename.lower().endswith(".pdf"):
        filename = "downloaded_book.pdf"

    filepath = os.path.join(BOOKS_DIR, filename)
    direct_url = _extract_direct_pdf_url(url)

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    for attempt_url in [direct_url, url]:
        try:
            r = requests.get(attempt_url, headers=headers, stream=True, timeout=30, allow_redirects=True)
            r.raise_for_status()

            total = 0
            with open(filepath, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
                    total += len(chunk)
                    if total > 50 * 1024 * 1024:
                        break

            with open(filepath, "rb") as f:
                if f.read(5) != b"%PDF-":
                    os.remove(filepath)
                    continue

            # Index into RAG
            rag_msg = ""
            try:
                import httpx
                with open(filepath, "rb") as f:
                    rr = httpx.post("http://127.0.0.1:5091/upload/book",
                                    files={"file": (filename, f, "application/pdf")}, timeout=30)
                rag_msg = " | Indexed into RAG" if rr.status_code == 200 else ""
            except:
                pass

            size_kb = os.path.getsize(filepath) / 1024
            size_str = f"{size_kb/1024:.1f} MB" if size_kb > 1024 else f"{size_kb:.0f} KB"
            return f"PDF downloaded: {filename} ({size_str}) to books/{rag_msg}"

        except Exception:
            continue

    return "Failed to download PDF. The URL may not point to a valid PDF file."


def _clone_repo(url: str) -> str:
    repo_name = url.rstrip("/").split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
    target_dir = os.path.join(CACHE_DIR, f"{repo_name}_{int(time.time())}")

    try:
        subprocess.run(["git", "clone", "--depth", "1", url, target_dir],
                       check=True, capture_output=True, timeout=60)

        readme = "No README found."
        for f in os.listdir(target_dir):
            if f.lower().startswith("readme"):
                try:
                    with open(os.path.join(target_dir, f), "r", encoding="utf-8") as fh:
                        readme = fh.read()[:3000]
                    break
                except:
                    pass

        structure = subprocess.run(["find", target_dir, "-maxdepth", "2", "-type", "f"],
                                   capture_output=True, text=True).stdout[:1500]
        return f"Repository: {repo_name}\n\nStructure:\n{structure}\n\nREADME:\n{readme}"

    except subprocess.TimeoutExpired:
        return f"Clone timed out for: {url}"
    except Exception as e:
        return f"Failed to clone: {e}"


def _fetch_webpage(url: str) -> str:
    from bs4 import BeautifulSoup

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        r = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")

        # Remove script/style/nav noise
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        title = soup.title.string.strip() if soup.title and soup.title.string else url
        text = soup.get_text(separator="\n", strip=True)

        # Clean excessive whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Cache it
        safe = re.sub(r'[^\w\s-]', '', title)[:60].strip()
        cache_file = os.path.join(CACHE_DIR, f"{safe}_{int(time.time())}.txt")
        with open(cache_file, "w", encoding="utf-8") as f:
            f.write(f"URL: {url}\nTitle: {title}\n\n{text}")

        return f"Webpage: {title}\nURL: {url}\n\nContent:\n{text[:4000]}"

    except Exception as e:
        # Fallback: curl
        try:
            res = subprocess.run(["curl", "-sL", "--max-time", "15", url],
                                 capture_output=True, text=True)
            text = res.stdout[:4000]
            return f"Fetched via curl: {url}\n\n{text}"
        except:
            return f"Failed to fetch: {e}"


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(resource_download_analyze(sys.argv[1]))
    else:
        print("Usage: python3 resource_tool.py <url>")
