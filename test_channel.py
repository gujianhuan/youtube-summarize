
import sys
try:
    from yt_dlp import YoutubeDL
except ImportError:
    print("yt_dlp not installed")
    sys.exit(1)

def test_channel_fetch(url):
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,  # Don't download, just extract info
        'playlistend': 3,      # Just get last 3 videos
        'ignoreerrors': True,
    }
    
    with YoutubeDL(ydl_opts) as ydl:
        try:
            print(f"Fetching info for: {url}")
            info = ydl.extract_info(url, download=False)
            
            # Channel info might be in the root or 'channel'/'uploader' keys
            print(f"Type: {info.get('_type', 'video')}")
            print(f"Title: {info.get('title')}")
            print(f"Channel: {info.get('channel')}")
            print(f"Channel ID: {info.get('channel_id')}")
            print(f"Uploader ID: {info.get('uploader_id')}")
            
            if 'entries' in info:
                print(f"Entries found: {len(info['entries'])}")
                for i, entry in enumerate(info['entries']):
                    print(f"  {i+1}. {entry.get('title')} ({entry.get('id')})")
            
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    # Test with a known channel (e.g., OpenAI or similar, using a handle)
    # Using OpenAI's handle for testing
    test_channel_fetch("https://www.youtube.com/@OpenAI")
