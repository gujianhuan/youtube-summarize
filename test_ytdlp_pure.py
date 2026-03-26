
import sys
from yt_dlp import YoutubeDL

def test_ytdlp_no_cookie():
    print("Testing yt-dlp with ignore_config=True and NO cookie args...")
    
    opts = {
        "skip_download": True,
        "quiet": False,
        "ignore_config": True, # The key fix
        "no_warnings": False,
        # "cookiesfrombrowser": ("chrome",), # Uncomment to force error
    }
    
    url = "https://www.youtube.com/watch?v=BaW_jenozKc" # generic video
    
    try:
        with YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=False)
        print("Success: No cookie error.")
    except Exception as e:
        print(f"Failed with error: {e}")

if __name__ == "__main__":
    test_ytdlp_no_cookie()
