
import sys
try:
    from yt_dlp import YoutubeDL
except ImportError:
    print("yt_dlp not installed")
    sys.exit(1)

def check_channel_avatar(url):
    print(f"Checking avatar for: {url}")
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlistend": 1,
    }
    
    with YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            if not info:
                print("No info")
                return
            
            # Print available keys to find the avatar
            print("Keys:", info.keys())
            
            # Check common locations for thumbnails
            if 'thumbnails' in info:
                print("\nThumbnails found:")
                for t in info['thumbnails']:
                    print(f"  - {t.get('url')} ({t.get('id')})")
            
            if 'channel_follower_count' in info:
                print(f"Followers: {info['channel_follower_count']}")

        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    check_channel_avatar("https://www.youtube.com/@OpenAI")
