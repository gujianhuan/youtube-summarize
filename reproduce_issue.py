import sys
import os
import shutil
try:
    from yt_dlp import YoutubeDL
except ImportError:
    print("yt-dlp not installed")
    sys.exit(1)

url = "https://www.youtube.com/watch?v=ESk2j00FUy4"

def test_config(name, opts):
    print(f"\n--- Testing {name} ---")
    try:
        with YoutubeDL(opts) as ydl:
            # For transcribe, we usually download=True. 
            # Let's try download=True to see if it actually downloads.
            info = ydl.extract_info(url, download=True)
            print(f"[{name}] Success (extract_info + download)")
            
            # If successful, check if formats are available
            formats = info.get('formats', [])
            print(f"Formats count: {len(formats)}")
            
    except Exception as e:
        print(f"[{name}] Failed: {e}")

# Config from transcribe_video_audio_with_ytdlp
opts_transcribe = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "ignore_config": True,
    "http_headers": {"Accept-Language": "en-US,en;q=0.9"},
    "postprocessors": [{
        "key": "FFmpegExtractAudio",
        "preferredcodec": "wav",
    }],
}

client_sets_transcribe = [["android"]] # Only test android
for cs in client_sets_transcribe:
    opts = opts_transcribe.copy()
    opts["extractor_args"] = {"youtube": {"player_client": cs}}
    test_config(f"transcribe_video_audio_with_ytdlp - {cs}", opts)
