
import sys
import os
import json

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core_logic import get_channel_recent_videos

def verify_all_subscriptions():
    with open("subscriptions.json", "r", encoding="utf-8") as f:
        subs = json.load(f)
    
    print(f"Verifying {len(subs)} subscriptions...")
    
    for sub in subs:
        print(f"\nChecking: {sub['name']} ({sub['url']})")
        try:
            videos = get_channel_recent_videos(
                sub['url'], 
                limit=5, 
                filter_longest=True,
                timeout_seconds=30
            )
            
            if not videos:
                print("  [WARNING] No videos found.")
            else:
                v = videos[0]
                print(f"  [SELECTED] {v['title']}")
                print(f"  [DATE]     {v['upload_date']}")
                print(f"  [DURATION] {v.get('duration')}s")
                print(f"  [URL]      {v['url']}")
        except Exception as e:
            print(f"  [ERROR] {e}")

if __name__ == "__main__":
    verify_all_subscriptions()
