
import sys
import os

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core_logic import get_channel_recent_videos

def test_rowing_captain():
    # Rowing Captain (赛艇队长)
    url = "https://www.youtube.com/channel/UC1TCQQXn4_VVKGhHl2e8yyg"
    print(f"Testing video fetch for: {url}")
    
    try:
        # Step 1: Check without filtering to see what we get raw
        print("\n--- Raw Fetch (First 10) ---")
        raw_videos = get_channel_recent_videos(
            url, 
            limit=10, 
            filter_longest=False,
            timeout_seconds=30
        )
        for v in raw_videos:
            print(f"Title: {v.get('title')[:30]}...")
            print(f"Date:  {v.get('upload_date')}")
            print(f"Dur:   {v.get('duration')}")
            print(f"URL:   {v.get('url')}")
            print("-" * 10)

        # Step 2: Check with filtering
        print("\n--- Filtered Fetch (Top 1) ---")
        videos = get_channel_recent_videos(
            url, 
            limit=5, 
            filter_longest=True,
            timeout_seconds=30
        )
        
        print(f"Found {len(videos)} videos after filtering.")
        
        if not videos:
            print("No videos found.")
        
        for v in videos:
            print(f"Title: {v.get('title')}")
            print(f"Date:  {v.get('upload_date')}")
            print(f"Dur:   {v.get('duration')}")
            print(f"URL:   {v.get('url')}")
            print("-" * 30)
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_rowing_captain()
