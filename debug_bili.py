
import requests
import json

def debug_bilibili(keyword):
    print(f"Debugging Bilibili search for '{keyword}'...")
    api_url = "https://api.bilibili.com/x/web-interface/search/type"
    params = {
        "search_type": "bili_user",
        "keyword": keyword,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://search.bilibili.com/"
    }
    try:
        resp = requests.get(api_url, params=params, headers=headers, timeout=5)
        print(f"Status: {resp.status_code}")
        try:
            data = resp.json()
            print(f"Code: {data.get('code')}")
            result = data.get("data", {}).get("result")
            if result:
                print(f"Found {len(result)} items")
                for item in result[:2]:
                    print(f" - {item.get('uname')} (mid: {item.get('mid')})")
            else:
                print("No result in data")
                # print(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"JSON parse error: {e}")
            print(resp.text[:500])
    except Exception as e:
        print(f"Request error: {e}")

if __name__ == "__main__":
    debug_bilibili("李永乐")
