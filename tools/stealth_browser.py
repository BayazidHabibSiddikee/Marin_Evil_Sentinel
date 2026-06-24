import sys
import os
import requests

# Configuration
CAMOFOX_URL = "http://localhost:9377"
USER_ID = "bayazid_agent"

def stealth_search(query):
    """
    Performs a stealth search using Camoufox HTTP API and extracts results.
    """
    print(f"[*] Starting stealth search for: {query}")
    
    try:
        # 1. Open a new tab directly with DuckDuckGo query
        search_url = f"https://duckduckgo.com/?q={query.replace(' ', '+')}"
        open_res = requests.post(
            f"{CAMOFOX_URL}/tabs/open",
            json={"userId": USER_ID, "url": search_url, "timeout": 90000}
        )
        open_data = open_res.json()
        
        if not open_data.get("ok"):
            return f"Failed to open tab: {open_data.get('error')}"
            
        tab_id = open_data["tabId"]
        print(f"[*] Search tab opened: {tab_id}")
        
        # 2. Extract page text using evaluate (more reliable than /extract for search results)
        eval_res = requests.post(
            f"{CAMOFOX_URL}/tabs/{tab_id}/evaluate",
            json={"userId": USER_ID, "expression": "document.body.innerText"}
        )
        eval_data = eval_res.json()
        
        if not eval_data.get("ok"):
            return f"Failed to extract data: {eval_data.get('error')}"
            
        text = eval_data["result"]
        
        # 3. Simple parsing of search results from raw text
        # This is a basic approach; more advanced regex could be used.
        lines = text.split('\n')
        results = []
        current_result = {}
        
        for line in lines:
            line = line.strip()
            if not line: continue
            
            # Simple heuristic: lines starting with http are likely links/domains
            if line.startswith('http') and '›' in line:
                if current_result: results.append(current_result)
                current_result = {"source": line}
            elif current_result and "title" not in current_result and len(line) > 10:
                current_result["title"] = line
            elif current_result and "snippet" not in current_result and len(line) > 20:
                current_result["snippet"] = line
                
        if current_result: results.append(current_result)
        
        # Clean up: close the tab
        # (Assuming there's a close endpoint, but we can just leave it for session management)
        
        if not results:
            # Fallback: just return the first 1000 chars of text if parsing failed
            return f"### Search results for '{query}':\n\n" + text[:1000] + "..."
            
        output = f"### Stealth Search Results for '{query}':\n\n"
        for i, res in enumerate(results[:5], 1):
            title = res.get('title', 'No Title')
            snippet = res.get('snippet', 'No snippet available.')
            source = res.get('source', 'Unknown source')
            output += f"{i}. **{title}**\n   - {snippet}\n   - Source: {source}\n\n"
            
        return output

    except Exception as e:
        return f"Error during stealth search: {str(e)}"

if __name__ == "__main__":
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        print(stealth_search(query))
    else:
        print("Usage: python3 stealth_browser.py <search query>")
