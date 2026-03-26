
import sys
import os
import core_logic # This will run the environment setup
from yt_dlp import YoutubeDL

def test_worst_selector():
    print(f"PATH: {os.environ['PATH']}")
    url = "https://www.youtube.com/watch?v=ESk2j00FUy4"
    client = "android"
    
    print(f"\n--- Testing selector: worstaudio/worst on {client} ---")
    opts = {
        "skip_download": True,
        "ignore_config": True,
        "extractor_args": {"youtube": {"player_client": [client]}},
        "quiet": False,
        "verbose": True,
        "format": "worstaudio/worst",
    }
    
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            print(f"Success! Selected format: {info.get('format_id')} - {info.get('ext')}")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_worst_selector()
