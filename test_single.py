
import sys
try:
    from yt_dlp import YoutubeDL
except ImportError:
    print("yt_dlp not installed")
    sys.exit(1)

def test_single_video(video_id):
    url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"Testing single video: {url}")
    
    opts = {
        "quiet": True,
        "no_warnings": True,
        # "extract_flat": True, # Do NOT use flat for detail fetch
    }
    
    with YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            print(f"Title: {info.get('title')}")
            print(f"Upload Date: {info.get('upload_date')}")
            print(f"Duration: {info.get('duration')}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    # Test with one of Wang Jian's videos
    test_single_video("yzvEYnRwhtE")
