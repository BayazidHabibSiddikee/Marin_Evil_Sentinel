import os
import shutil
import time
import subprocess
from urllib.parse import urlparse

CACHE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "storage", "cache", "repos"))

def clean_old_caches():
    """Deletes directories in CACHE_DIR older than 48 hours (172800 seconds)."""
    if not os.path.exists(CACHE_DIR):
        return
    now = time.time()
    for item in os.listdir(CACHE_DIR):
        item_path = os.path.join(CACHE_DIR, item)
        if os.path.isdir(item_path):
            try:
                mtime = os.path.getmtime(item_path)
                if now - mtime > 172800:
                    shutil.rmtree(item_path)
            except Exception as e:
                print(f"Error cleaning {item_path}: {e}")

def analyze_link(url: str) -> str:
    """Clones a git repo or fetches a webpage, summarizes it, and returns the summary."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    clean_old_caches()

    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    
    timestamp = str(int(time.time()))
    
    if "github.com" in domain or "gitlab.com" in domain or url.endswith(".git"):
        return _analyze_git_repo(url, timestamp)
    else:
        return _analyze_webpage(url, timestamp)

def _analyze_git_repo(url: str, timestamp: str) -> str:
    repo_name = url.rstrip("/").split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
        
    target_dir = os.path.join(CACHE_DIR, f"{repo_name}_{timestamp}")
    
    try:
        subprocess.run(["git", "clone", "--depth", "1", url, target_dir], check=True, capture_output=True)
        
        # Read README
        readme_content = "No README found."
        for file in os.listdir(target_dir):
            if file.lower().startswith("readme"):
                try:
                    with open(os.path.join(target_dir, file), "r", encoding="utf-8") as f:
                        readme_content = f.read()[:2000] # Limit to first 2000 chars
                    break
                except:
                    pass
        
        # Get structure
        structure = subprocess.run(["ls", "-la", target_dir], capture_output=True, text=True).stdout
        
        return f"Successfully cloned repository {repo_name}.\n\nRepository Structure:\n{structure}\n\nREADME Preview:\n{readme_content}"
    except subprocess.CalledProcessError as e:
        return f"Failed to clone repository: {e.stderr.decode()}"
    except Exception as e:
        return f"Error analyzing repository: {e}"

def _analyze_webpage(url: str, timestamp: str) -> str:
    try:
        from bs4 import BeautifulSoup
        import urllib.request
        
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            html = response.read()
            
        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text(separator='\n', strip=True)
        title = soup.title.string if soup.title else url
        
        # Save to cache
        safe_name = "".join(c for c in title if c.isalnum() or c in (' ', '_', '-')).strip()
        target_file = os.path.join(CACHE_DIR, f"{safe_name}_{timestamp}.txt")
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(text)
            
        return f"Successfully fetched webpage '{title}'.\n\nPreview:\n{text[:2000]}..."
    except Exception as e:
        # Fallback to curl
        try:
            target_file = os.path.join(CACHE_DIR, f"curl_fetch_{timestamp}.txt")
            res = subprocess.run(["curl", "-sL", url], capture_output=True, text=True)
            text = res.stdout
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(text)
            return f"Fetched raw content via curl. Preview:\n{text[:2000]}..."
        except Exception as curl_e:
            return f"Failed to fetch webpage: {e} | Curl fallback failed: {curl_e}"
