
import sys
import core_logic
from core_logic import transcribe_video_audio_with_ytdlp

def test_transcribe():
    print("Testing transcribe_video_audio_with_ytdlp...")
    try:
        transcribe_video_audio_with_ytdlp(
            video_url="https://www.youtube.com/watch?v=BaW_jenozKc",
            proxy_url="",
            timeout_seconds=10,
            retries=1,
            cookies_file="",
            cookies_from_browser="chrome",
            model_name="tiny",
            language="en"
        )
    except Exception as e:
        print(f"Caught exception: {e}")

if __name__ == "__main__":
    test_transcribe()
