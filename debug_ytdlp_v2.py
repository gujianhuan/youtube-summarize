
import yt_dlp
import sys
import os

url = "https://www.youtube.com/watch?v=XSAQySJV4yo"
print(f"Testing URL: {url}")

# Check ffmpeg
print(f"PATH: {os.environ['PATH']}")
import shutil
ffmpeg_path = shutil.which("ffmpeg")
print(f"ffmpeg found at: {ffmpeg_path}")

def test_download(client_name):
    print(f"\n--- Testing client: {client_name} ---")
    opts = {
        "quiet": False,
        "noplaylist": True,
        # "format": "bestaudio/best", # Let's simulate what we have in code (commented out means None)
        "extractor_args": {"youtube": {"player_client": [client_name]}},
    }
    
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=False)
            print(f"✅ Extraction successful for {client_name}")
    except Exception as e:
        print(f"❌ Failed for {client_name}: {e}")

test_download("android")
test_download("ios")
test_download("web")
