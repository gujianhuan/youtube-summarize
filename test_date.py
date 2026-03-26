
import sys
try:
    from yt_dlp import YoutubeDL
except ImportError:
    print("yt_dlp not installed")
    sys.exit(1)

def test_recent_videos(channel_url):
    print(f"Testing channel: {channel_url}")
    
    # 模拟 core_logic.py 中的 get_channel_recent_videos 逻辑
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True, # 这是关键参数
        "playlistend": 5,
        "nocheckcertificate": True,
        "ignoreerrors": True,
    }
    
    if "/videos" not in channel_url:
        channel_url += "/videos"

    with YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(channel_url, download=False)
            if not info:
                print("No info returned")
                return
            
            entries = info.get("entries", [])
            print(f"Entries found: {len(entries)}")
            
            for i, e in enumerate(entries):
                print(f"\nVideo {i+1}:")
                print(f"  Title: {e.get('title')}")
                print(f"  ID: {e.get('id')}")
                print(f"  Upload Date (raw): '{e.get('upload_date')}'")
                print(f"  Keys available: {list(e.keys())}")
                
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    # 使用用户提到的 "王剑" 频道 (ID: UC8UCbiPrm2zN9nZHKdTevZA)
    test_recent_videos("https://www.youtube.com/channel/UC8UCbiPrm2zN9nZHKdTevZA")
