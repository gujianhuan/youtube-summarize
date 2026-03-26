
import sys
import os

# Ensure we can import core_logic
sys.path.append(os.getcwd())

from core_logic import search_channels

if __name__ == "__main__":
    keyword = "李永乐"
    print(f"Searching for '{keyword}'...")
    # Timeout increased for test stability
    results = search_channels(keyword, limit=3, timeout_seconds=15.0)
    
    print("\n=== YouTube Results ===")
    for item in results.get("youtube", []):
        print(f"[{item['name']}] {item['url']} (ID: {item['id']})")
        
    print("\n=== Bilibili Results ===")
    for item in results.get("bilibili", []):
        print(f"[{item['name']}] {item['url']} (ID: {item['id']})")
