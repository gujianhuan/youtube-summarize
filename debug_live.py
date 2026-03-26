
import sys
try:
    from yt_dlp import YoutubeDL
except ImportError:
    print("yt_dlp not installed")
    sys.exit(1)

def debug_live(channel_url):
    print(f"Debugging Live tab: {channel_url}")
    
    # Check /streams
    live_url = channel_url + "/streams"
    
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True, # Or 'in_playlist'
        "playlistend": 5,
        "ignoreerrors": True,
    }
    
    with YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(live_url, download=False)
            if not info:
                print("No info returned")
                return
            
            entries = info.get("entries", [])
            print(f"\nEntries found in /streams: {len(entries)}")
            
            for i, e in enumerate(entries):
                print(f"Stream {i+1}:")
                print(f"  Title: {e.get('title')}")
                print(f"  Duration: {e.get('duration')}")
                print(f"  ID: {e.get('id')}")
                
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    # Wang Jian
    debug_live("https://www.youtube.com/channel/UC8UCbiPrm2zN9nZHKdTevZA")
