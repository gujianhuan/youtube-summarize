import json
import re
import time
import uuid
from pathlib import Path
import urllib.request

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


CHROME_PATH = Path(r"C:\Users\Administrator\AppData\Local\Google\Chrome\Application\chrome.exe")
CHROMEDRIVER_PATH = Path(r"C:\Users\Administrator\.cache\selenium\chromedriver\win64\121.0.6167.184\chromedriver.exe")
APP_URL = "http://localhost:8502/"
EXTENSION_DIR = Path(r"D:\Workspace\YouTubeSummarizer\chrome_extension_mvp")
PROFILE_DIR = Path(r"D:\Workspace\YouTubeSummarizer\chrome-profile-page-log-batch")
LOG_FILE = Path(r"D:\Workspace\YouTubeSummarizer\streamlit_8502.out.log")
OUTPUT_FILE = Path(r"D:\Workspace\YouTubeSummarizer\chrome_page_log_batch_summary.json")

DEFAULT_VIDEOS = [
    "https://www.youtube.com/watch?v=C14SVwWZ2fE",
    "https://www.youtube.com/watch?v=TDv56whosPQ",
    "https://www.youtube.com/watch?v=FIyzZoVLceo&t=6132s",
    "https://www.youtube.com/watch?v=brNEAlPN3zY",
    "https://www.youtube.com/watch?v=3W8w14IwAYY",
    "https://www.youtube.com/watch?v=G0o7ToVxOOs",
    "https://www.youtube.com/watch?v=4l97aNza_Zc",
]


def ensure_app_ready(timeout: int = 40) -> None:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
      try:
          with urllib.request.urlopen(APP_URL, timeout=5) as resp:
              if getattr(resp, "status", 0) == 200:
                  return
      except Exception as exc:
          last_error = f"{type(exc).__name__}: {exc}"
      time.sleep(1)
    raise RuntimeError(f"app_not_ready:{last_error or 'unknown'}")


def build_driver(profile_dir: Path) -> webdriver.Chrome:
    options = Options()
    if CHROME_PATH.exists():
        options.binary_location = str(CHROME_PATH)
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument(f"--disable-extensions-except={EXTENSION_DIR}")
    options.add_argument(f"--load-extension={EXTENSION_DIR}")
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1600,2600")
    options.add_argument("--lang=zh-CN")
    service = Service(executable_path=str(CHROMEDRIVER_PATH)) if CHROMEDRIVER_PATH.exists() else Service()
    return webdriver.Chrome(service=service, options=options)


def read_log_tail(start_offset: int) -> str:
    if not LOG_FILE.exists():
        return ""
    with LOG_FILE.open("r", encoding="utf-8", errors="ignore") as fh:
        fh.seek(start_offset)
        return fh.read()


def parse_success_snapshot(log_text: str, video_url: str) -> dict:
    lines = [line.strip() for line in str(log_text or "").splitlines() if line.strip()]
    received_line = ""
    summary_start_line = ""
    summary_success_line = ""
    transcript_len = 0
    summary_len = 0
    for line in lines:
        if "VideoBridgePayloadReceived:" in line and f"source_url={video_url}" in line:
            received_line = line
            match = re.search(r"transcript_len=(\d+)", line)
            if match:
                transcript_len = int(match.group(1))
        if "VideoSummarySingle:" in line and f"url={video_url}" in line and "enable_fact_check=False" in line:
            summary_start_line = line
        if "VideoSummarySingle: success" in line and f"url={video_url}" in line:
            summary_success_line = line
            match = re.search(r"summary_len=(\d+)", line)
            if match:
                summary_len = int(match.group(1))
    return {
        "received_line": received_line,
        "summary_start_line": summary_start_line,
        "summary_success_line": summary_success_line,
        "transcript_len": transcript_len,
        "summary_len": summary_len,
        "received": bool(received_line),
        "summary_started": bool(summary_start_line),
        "summary_succeeded": bool(summary_success_line),
    }


def run_one(video_url: str, timeout_seconds: int = 220) -> dict:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    profile_dir = PROFILE_DIR / f"run_{uuid.uuid4().hex}"
    profile_dir.mkdir(parents=True, exist_ok=True)

    log_offset = LOG_FILE.stat().st_size if LOG_FILE.exists() else 0
    ensure_app_ready()
    driver = build_driver(profile_dir)
    start_time = time.time()

    try:
        driver.get(APP_URL)
        WebDriverWait(driver, 90).until(
            lambda d: "处理中心" in (d.find_element(By.TAG_NAME, "body").text or "")
        )
        input_el = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//input[contains(@aria-label, '视频链接或 ID') or contains(@placeholder, 'youtube.com/watch')]",
                )
            )
        )
        input_el.clear()
        input_el.send_keys(video_url)
        WebDriverWait(driver, 20).until(lambda d: input_el.get_attribute("value") == video_url)
        button = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., '一键抓取并总结')]"))
        )
        button.click()

        deadline = time.time() + timeout_seconds
        last_body = ""
        snapshot = {
            "received": False,
            "summary_started": False,
            "summary_succeeded": False,
            "transcript_len": 0,
            "summary_len": 0,
            "received_line": "",
            "summary_start_line": "",
            "summary_success_line": "",
        }
        while time.time() < deadline:
            time.sleep(5)
            try:
                last_body = str(driver.find_element(By.TAG_NAME, "body").text or "")
            except Exception:
                pass
            log_text = read_log_tail(log_offset)
            snapshot = parse_success_snapshot(log_text, video_url)
            if snapshot["summary_succeeded"]:
                break

        return {
            "video_url": video_url,
            "elapsed_seconds": round(time.time() - start_time, 1),
            "final_state": "summary_success" if snapshot["summary_succeeded"] else "timeout",
            "received_payload": snapshot["received"],
            "summary_started": snapshot["summary_started"],
            "summary_succeeded": snapshot["summary_succeeded"],
            "transcript_len": snapshot["transcript_len"],
            "summary_len": snapshot["summary_len"],
            "received_line": snapshot["received_line"],
            "summary_start_line": snapshot["summary_start_line"],
            "summary_success_line": snapshot["summary_success_line"],
            "body_preview": last_body[:800],
        }
    finally:
        try:
            driver.quit()
        except Exception:
            pass


def run_batch(urls: list[str]) -> dict:
    results = []
    for url in urls:
        try:
            results.append(run_one(url))
        except Exception as exc:
            results.append(
                {
                    "video_url": url,
                    "final_state": "exception",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "count": len(results),
        "success_count": sum(1 for item in results if item.get("final_state") == "summary_success"),
        "results": results,
    }
    OUTPUT_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    import sys

    urls = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_VIDEOS
    result = run_batch(urls)
    print(json.dumps(result, ensure_ascii=True, indent=2))
