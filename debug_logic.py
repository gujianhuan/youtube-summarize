
import sys
from datetime import datetime
try:
    from yt_dlp import YoutubeDL
except ImportError:
    print("yt_dlp not installed")
    sys.exit(1)

def get_channel_recent_videos_debug(channel_url):
    print(f"Debugging logic for: {channel_url}")
    
    base_url = channel_url.strip()
    if base_url.endswith("/"):
        base_url = base_url[:-1]
        
    target_urls = [base_url + "/videos", base_url + "/streams"]
    all_candidates = []
    
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlistend": 10,
        "ignoreerrors": True,
        "nocheckcertificate": True,
    }
    
    for url in target_urls:
        print(f"Fetching: {url}")
        with YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                if not info:
                    print("  No info")
                    continue
                
                entries = info.get("entries", [])
                print(f"  Found {len(entries)} entries")
                
                for e in entries:
                    if not e: continue
                    v_id = e.get("id")
                    title = e.get("title")
                    duration = e.get("duration")
                    timestamp = e.get("timestamp")
                    upload_date = e.get("upload_date")
                    
                    print(f"    - [{v_id}] {title[:30]}... | Dur: {duration} | Date: {upload_date} | TS: {timestamp}")
                    
                    item = {
                        "id": v_id,
                        "title": title,
                        "url": e.get("url"),
                        "upload_date": upload_date,
                        "timestamp": timestamp,
                        "duration": duration or 0,
                    }
                    if not any(x['id'] == v_id for x in all_candidates):
                        all_candidates.append(item)
            except Exception as e:
                print(f"  Error: {e}")

    print(f"\nTotal candidates: {len(all_candidates)}")
    
    # Simulate logic
    def get_sort_key(x):
        if x.get("timestamp"): return x.get("timestamp")
        if x.get("upload_date"): return int(x.get("upload_date"))
        return 0

    all_candidates.sort(key=get_sort_key, reverse=True)
    
    print("\nSorted Candidates (Top 5):")
    for x in all_candidates[:5]:
        print(f"  {x['title']} (Dur: {x['duration']})")

    long_candidates = [x for x in all_candidates if x["duration"] > 900]
    print(f"\nLong Candidates (>900s): {len(long_candidates)}")
    for x in long_candidates:
        print(f"  {x['title']} (Dur: {x['duration']})")
    
    if long_candidates:
        best = long_candidates[0]
        print(f"\nWinner (Latest Long): {best['title']}")
    else:
        best = all_candidates[0] if all_candidates else None
        print(f"\nWinner (Fallback): {best['title'] if best else 'None'}")

if __name__ == "__main__":
    # Wang Jian
    get_channel_recent_videos_debug("https://www.youtube.com/channel/UC8UCbiPrm2zN9nZHKdTevZA")
