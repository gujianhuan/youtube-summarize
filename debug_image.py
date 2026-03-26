
import requests

url = "http://i2.hdslb.com/bfs/face/496a4c529c6a171d2079fb7694a6d66cce35c253.jpg"

print(f"Testing URL: {url}")

# Test 1: No Referer
try:
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=5)
    print(f"No Referer: Status {r.status_code}, Length {len(r.content)}")
except Exception as e:
    print(f"No Referer Failed: {e}")

# Test 2: With Referer (simulate Streamlit)
try:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "http://localhost:8501/"
    }
    r = requests.get(url, headers=headers, timeout=5)
    print(f"With Referer: Status {r.status_code}, Length {len(r.content)}")
except Exception as e:
    print(f"With Referer Failed: {e}")
