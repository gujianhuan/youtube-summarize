
import sys
from yt_dlp import YoutubeDL

def test_subs():
    url = "https://www.youtube.com/watch?v=ESk2j00FUy4"
    # Strategies from core_logic.py
    client_strategies = [["android"], ["ios"], ["web"]]
    
    for client_set in client_strategies:
        print(f"\n=== Testing Client: {client_set} ===")
        opts = {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en", "zh-Hans"],
            "subtitlesformat": "vtt",
            "quiet": False,
            "verbose": True,
            "ignore_config": True,
            "extractor_args": {"youtube": {"player_client": client_set}},
            "http_headers": {"Accept-Language": "en-US,en;q=0.9"},
        }
        
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                print("Success!")
                # Check if subs were found
                if 'subtitles' in info and info['subtitles']:
                    print(f"Subtitles found: {list(info['subtitles'].keys())}")
                elif 'automatic_captions' in info and info['automatic_captions']:
                    print(f"Auto-captions found: {list(info['automatic_captions'].keys())}")
                else:
                    print("No subtitles found.")
        except Exception as e:
            print(f"Failed: {e}")

if __name__ == "__main__":
    test_subs()
