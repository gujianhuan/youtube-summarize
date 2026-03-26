
import sys
import time
import re

# Mock classes
class DownloadError(Exception):
    pass

class YoutubeDL:
    def __init__(self, params):
        self.params = params
        self.cookiefile = params.get("cookiefile")
        self.cookiesfrombrowser = params.get("cookiesfrombrowser")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def extract_info(self, url, download=True):
        # Simulate behavior
        if not self.cookiefile and not self.cookiesfrombrowser:
            print(">> Attempting NO COOKIE")
            raise DownloadError("HTTP Error 429: Too Many Requests")
        else:
            browser = self.cookiesfrombrowser[0] if self.cookiesfrombrowser else "file"
            print(f">> Attempting WITH COOKIE ({browser})")
            raise DownloadError("yt_dlp.utils.DownloadError: ytdl-org/youtube-dl: error: could not copy chrome cookie database")

def strip_ansi(s):
    return re.sub(r"\x1B\[[0-?]*[ -/]*[@-~]", "", s)

def is_cookie_error(msg: str) -> bool:
    s = strip_ansi(str(msg or "")).lower()
    return (
        ("could not copy" in s and "cookie" in s) or 
        ("cookie database" in s) or 
        ("database is locked" in s) or 
        ("permission denied" in s) or
        ("access is denied" in s) or
        ("used by another process" in s) or
        ("winerror 32" in s) or
        ("winerror 5" in s) or
        ("sqlite3" in s and "locked" in s)
    )

def test_logic():
    cookies_file = ""
    cookies_from_browser = "chrome"
    retries = 1
    timeout_seconds = 10
    
    def cookie_sources():
        file_path = (cookies_file or "").strip()
        browser = (cookies_from_browser or "").strip()
        if file_path:
            return [(file_path, "")]
        if not browser:
            return [("", "")]
        
        sources = [("", "")]
        browsers_to_try = []
        if browser == "chrome":
            browsers_to_try = ["chrome", "edge", "firefox"]
        else:
            browsers_to_try = [browser]
        
        for b in browsers_to_try:
            sources.append(("", b))
        return sources

    last_err = None
    no_cookie_error = None
    
    print(f"Sources: {cookie_sources()}")

    for attempt in range(max(1, int(retries))):
        for cookiefile, cfb in cookie_sources():
            opts = {}
            if cookiefile: opts["cookiefile"] = cookiefile
            elif cfb: opts["cookiesfrombrowser"] = (cfb,)
            
            try:
                with YoutubeDL(opts) as ydl:
                    ydl.extract_info("http://example.com")
            except DownloadError as e:
                msg = strip_ansi(str(e))
                print(f"Caught error: {msg}")
                
                if not cookiefile and not cfb:
                    print("-> Setting no_cookie_error")
                    no_cookie_error = e
                    last_err = e
                else:
                    if is_cookie_error(msg):
                        print("-> Is Cookie Error")
                        if no_cookie_error:
                            print("-> Reverting to no_cookie_error")
                            last_err = no_cookie_error
                        else:
                            last_err = e
                    else:
                        last_err = e
                
                if cfb and is_cookie_error(msg):
                    print("-> Continuing due to cookie error")
                    continue
                continue

    print("-" * 20)
    print(f"Final last_err: {last_err}")

if __name__ == "__main__":
    test_logic()
