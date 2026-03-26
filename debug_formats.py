
import sys
from yt_dlp import YoutubeDL

def list_formats():
    url = "https://www.youtube.com/watch?v=ESk2j00FUy4"
    clients = ["android", "ios", "web"]
    
    for client in clients:
        print(f"\n--- Testing client: {client} ---")
        opts = {
            "skip_download": True,
            "ignore_config": True,
            "extractor_args": {"youtube": {"player_client": [client]}},
            "quiet": True,
        }
        
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                formats = info.get('formats', [])
                print(f"Found {len(formats)} formats.")
                for f in formats:
                    fid = f.get('format_id')
                    ext = f.get('ext')
                    acodec = f.get('acodec')
                    vcodec = f.get('vcodec')
                    note = f.get('format_note')
                    print(f"  {fid}: {ext} (a:{acodec}, v:{vcodec}) - {note}")
        except Exception as e:
            print(f"Error with {client}: {e}")

if __name__ == "__main__":
    list_formats()
