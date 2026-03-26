
import yt_dlp
import sys

url = "https://www.youtube.com/watch?v=XSAQySJV4yo"
print(f"Testing URL: {url}")

def test_download(format_selector=None):
    print(f"\n--- Testing format: {format_selector} ---")
    opts = {
        "quiet": False,
        "noplaylist": True,
        # "verbose": True,
    }
    if format_selector:
        opts["format"] = format_selector
    
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=False) # Just extraction first
            print("✅ Extraction successful")
    except Exception as e:
        print(f"❌ Failed: {e}")

# Test 1: No format (default)
test_download(None)

# Test 2: bestaudio/best
test_download("bestaudio/best")

# Test 3: best
test_download("best")

# Test 4: worst
test_download("worst")
