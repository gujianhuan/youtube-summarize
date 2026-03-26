
import sys
import os
import traceback

sys.path.append(os.getcwd())

from core_logic import get_channel_info

if __name__ == "__main__":
    url = "https://space.bilibili.com/476605517"
    print(f"Testing get_channel_info for: {url}")
    try:
        cid, cname, curl, cavatar, cplatform = get_channel_info(url, proxy_url="", timeout_seconds=10)
        print(f"Success!")
        print(f"ID: {cid}")
        print(f"Name: {cname}")
        print(f"URL: {curl}")
        print(f"Avatar: {cavatar}")
        print(f"Platform: {cplatform}")
    except Exception as e:
        print(f"Failed: {e}")
        traceback.print_exc()
