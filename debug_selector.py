
import sys
from yt_dlp import YoutubeDL

def test_selectors():
    url = "https://www.youtube.com/watch?v=ESk2j00FUy4"
    client = "android"
    
    selectors = ["worstaudio/worst", "bestaudio/best"]
    
    for fmt in selectors:
        print(f"\n--- Testing selector: {fmt} on {client} ---")
        opts = {
            "skip_download": True,
            "ignore_config": True,
            "extractor_args": {"youtube": {"player_client": [client]}},
            "quiet": True,
            "format": fmt,
        }
        
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                print(f"Success! Selected format: {info.get('format_id')} - {info.get('ext')}")
        except Exception as e:
            print(f"Failed: {e}")

if __name__ == "__main__":
    test_selectors()
