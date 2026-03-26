
import sys
import os
import json

# Ensure we can import core_logic
sys.path.append(os.getcwd())

from core_logic import search_channels

if __name__ == "__main__":
    keyword = "李永乐"
    print(f"Searching for '{keyword}'...")
    results = search_channels(keyword, limit=2, timeout_seconds=15.0)
    
    print("\n=== YouTube Raw Data (Full Keys) ===")
    
    # Temporarily modify core_logic behavior or just copy the logic here to inspect
    from yt_dlp import YoutubeDL
    opts = {
        "quiet": True,
        "extract_flat": True,
        "nocheckcertificate": True,
        "ignoreerrors": True,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info("ytsearch2:李永乐", download=False)
        if info and "entries" in info:
            for e in info["entries"][:1]:
                print(json.dumps(e, indent=2, ensure_ascii=False))
