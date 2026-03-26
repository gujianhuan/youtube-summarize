import sys
import os
try:
    from yt_dlp import YoutubeDL
except ImportError:
    print("yt-dlp not installed")
    sys.exit(1)

url = "https://www.youtube.com/watch?v=ESk2j00FUy4"

def test_new_logic():
    print("\n--- Testing New Logic for download_with_lang ---")
    
    # Mimic the loop in download_with_lang
    client_strategies = [["android"], ["ios"], ["web"]]
    last_err = None
    
    opts = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en"],
        "subtitlesformat": "vtt",
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "ignore_config": True,
        "format": "bestaudio/best",
        "http_headers": {"Accept-Language": "en-US,en;q=0.9"},
    }

    for attempt in range(2): # Try twice
        client_set = client_strategies[attempt % len(client_strategies)]
        print(f"Attempt {attempt}: Client {client_set}")
        
        current_opts = opts.copy()
        current_opts["extractor_args"] = {"youtube": {"player_client": client_set}}
        
        try:
            with YoutubeDL(current_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                print(f"  Success! Info extracted.")
                
                # Check for subtitles (simulating vtts check)
                subs = info.get('subtitles') or {}
                auto = info.get('automatic_captions') or {}
                has_subs = len(subs) > 0 or len(auto) > 0
                
                if has_subs:
                    print("  Subtitles found. Returning success.")
                    return # return last_video_id, vtts
                
                print("  No subtitles found.")
                last_err = RuntimeError("No subs found")
                
                # NEW LOGIC: Return empty list immediately
                print("  Returning empty list (stopping attempts).")
                return # return last_video_id, []
                
        except Exception as e:
            print(f"  Failed: {e}")
            last_err = e
            continue

    print(f"End of loop. Last error: {last_err}")

test_new_logic()
