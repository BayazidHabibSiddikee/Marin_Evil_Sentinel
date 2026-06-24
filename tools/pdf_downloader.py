import os
import re
import requests
import urllib.parse


# Common direct PDF URL patterns
PDF_DIRECT_PATTERNS = [
    r"https?://[^/]+/[^/]+\.pdf(?:\?.*)?$",
]

# Sites that need special handling
ARCHIVE_ORG_PATTERN = r"https?://archive\.org/details/([^/?]+)"


def _extract_direct_pdf_url(url: str) -> str:
    """Try to extract a direct PDF download URL from common sources."""
    # Archive.org — try the direct download link
    m = re.match(ARCHIVE_ORG_PATTERN, url)
    if m:
        item_id = m.group(1)
        return f"https://archive.org/download/{item_id}/{item_id}.pdf"

    # Google Docs — extract file ID and construct download URL
    if "docs.google.com" in url or "drive.google.com" in url:
        m = re.search(r"/d/([a-zA-Z0-9_-]+)", url)
        if m:
            return f"https://drive.google.com/uc?export=download&id={m.group(1)}"

    # Already a direct PDF link
    for pattern in PDF_DIRECT_PATTERNS:
        if re.match(pattern, url):
            return url

    return url


def _check_url_is_pdf(url: str) -> bool:
    """Quick HEAD check to see if URL points to a PDF."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.head(url, headers=headers, timeout=8, allow_redirects=True)
        ct = r.headers.get("Content-Type", "")
        return "pdf" in ct.lower()
    except Exception:
        return False


def download_pdf(url: str, filename: str = None) -> str:
    """
    Downloads a PDF from a URL and saves it to the doc/ folder.
    """
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        doc_dir = os.path.join(base_dir, "doc")
        os.makedirs(doc_dir, exist_ok=True)

        if not filename:
            parsed = urllib.parse.urlparse(url)
            filename = os.path.basename(parsed.path)
            if not filename.lower().endswith(".pdf"):
                filename = "downloaded_book.pdf"

        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"

        filepath = os.path.join(doc_dir, filename)

        # Get direct URL
        direct_url = _extract_direct_pdf_url(url)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        # Try each URL
        for attempt_url in [direct_url, url]:
            try:
                response = requests.get(attempt_url, headers=headers, stream=True,
                                       timeout=20, allow_redirects=True)
                response.raise_for_status()

                content_type = response.headers.get("Content-Type", "")

                # Save to file
                total = 0
                with open(filepath, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                        total += len(chunk)
                        if total > 50 * 1024 * 1024:  # 50MB limit
                            break

                # Verify it's a PDF
                with open(filepath, "rb") as f:
                    header = f.read(5)
                if header != b"%PDF-":
                    os.remove(filepath)
                    continue

                # Success — index into RAG
                rag_msg = _index_to_rag(filepath, filename)
                size_kb = os.path.getsize(filepath) / 1024
                if size_kb > 1024:
                    size_str = f"{size_kb/1024:.1f} MB"
                else:
                    size_str = f"{size_kb:.0f} KB"
                return f"Downloaded '{filename}' ({size_str}) to doc/ {rag_msg}"

            except Exception:
                continue

        return "Failed: URL doesn't point to a downloadable PDF. Try a direct .pdf link."

    except Exception as e:
        return f"Download failed: {e}"


def _index_to_rag(filepath: str, filename: str) -> str:
    """Try to index the downloaded file into the RAG system."""
    try:
        import httpx
        with open(filepath, "rb") as f:
            r = httpx.post(
                "http://127.0.0.1:5091/upload/doc",
                files={"file": (filename, f, "application/pdf")},
                timeout=30.0
            )
        return "and indexed into RAG" if r.status_code == 200 else "(RAG index skipped)"
    except Exception:
        return "(RAG server offline)"


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        url = sys.argv[1]
        name = sys.argv[2] if len(sys.argv) > 2 else None
        print(download_pdf(url, name))
    else:
        print("Usage: python3 pdf_downloader.py <url> [filename]")
