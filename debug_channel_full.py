
import sys
import json
try:
    from yt_dlp import YoutubeDL
except ImportError:
    print("yt_dlp not installed")
    sys.exit(1)

def debug_channel(channel_url):
    print(f"Debugging channel: {channel_url}")
    
    # 1. Try default extract_flat=True
    print("\n--- Mode 1: extract_flat=True ---")
    opts1 = {
        "quiet": True,
        "extract_flat": True,
        "playlistend": 5,
        "ignoreerrors": True,
        "no_warnings": True,
    }
    
    with YoutubeDL(opts1) as ydl:
        info = ydl.extract_info(channel_url + "/videos", download=False)
        if info:
            entries = info.get("entries", [])
            for i, e in enumerate(entries):
                print(f"Video {i+1}:")
                print(f"  Title: {e.get('title')}")
                print(f"  Duration: {e.get('duration')} (type: {type(e.get('duration'))})")
                print(f"  Upload Date: {e.get('upload_date')}")
                print(f"  Timestamp: {e.get('timestamp')}")
                # Dump keys to see what's available
                # print(f"  Keys: {list(e.keys())}")

    # 2. Try extract_flat='in_playlist' (sometimes gives more info)
    print("\n--- Mode 2: extract_flat='in_playlist' ---")
    opts2 = {
        "quiet": True,
        "extract_flat": 'in_playlist',
        "playlistend": 5,
        "ignoreerrors": True,
        "no_warnings": True,
    }
    
    with YoutubeDL(opts2) as ydl:
        info = ydl.extract_info(channel_url + "/videos", download=False)
        if info:
            entries = info.get("entries", [])
            for i, e in enumerate(entries):
                print(f"Video {i+1}:")
                print(f"  Title: {e.get('title')}")
                print(f"  Duration: {e.get('duration')}")
                print(f"  Upload Date: {e.get('upload_date')}")

if __name__ == "__main__":
    # Wang Jian
    debug_channel("https://www.youtube.com/channel/UC8UCbiPrm2zN9nZHKdTevZA")
