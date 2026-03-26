
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
        'playlistend': 5,      # Just get last 5 videos
        'ignoreerrors': True,
    }
    
    with YoutubeDL(ydl_opts) as ydl:
        try:
            print(f"Fetching info for: {url}")
            info = ydl.extract_info(url, download=False)
            
            print(f"Type: {info.get('_type', 'video')}")
            print(f"Title: {info.get('title')}")
            
            if 'entries' in info:
                entries = list(info['entries'])
                print(f"Entries found: {len(entries)}")
                for i, entry in enumerate(entries):
                    print(f"  {i+1}. {entry.get('title')} ({entry.get('id')}) - {entry.get('url')}")
            
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    # Test with /videos endpoint
    test_channel_fetch("https://www.youtube.com/@OpenAI/videos")
