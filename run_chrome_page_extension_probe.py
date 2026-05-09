import json
import time
import traceback
import urllib.request
import uuid
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


CHROME_PATH = Path(r"C:\Users\Administrator\AppData\Local\Google\Chrome\Application\chrome.exe")
CHROMEDRIVER_PATH = Path(r"C:\Users\Administrator\.cache\selenium\chromedriver\win64\121.0.6167.184\chromedriver.exe")
APP_URL = "http://localhost:8502/"
EXTENSION_DIR = Path(r"D:\Workspace\YouTubeSummarizer\chrome_extension_mvp")
PROFILE_DIR = Path(r"D:\Workspace\YouTubeSummarizer\chrome-profile-page-e2e")
OUTPUT_DIR = Path(r"D:\Workspace\YouTubeSummarizer")
TRACE_FILE = OUTPUT_DIR / "chrome_page_probe_trace.log"
SUMMARY_FILE = OUTPUT_DIR / "chrome_page_probe_summary.json"
FINAL_TEXT_FILE = OUTPUT_DIR / "chrome_page_probe_final.txt"
ERROR_FILE = OUTPUT_DIR / "chrome_page_probe_error.txt"
SCREENSHOT_FILE = OUTPUT_DIR / "chrome_page_probe_final.png"


def trace(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {message}\n"
    with TRACE_FILE.open("a", encoding="utf-8") as fh:
        fh.write(line)


def ensure_app_ready(timeout: int = 30) -> None:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(APP_URL, timeout=5) as resp:
                if getattr(resp, "status", 0) == 200:
                    trace("app_ready")
                    return
        except Exception as exc:
            last_error = f"{type(exc).__name__}:{exc}"
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
    options.add_argument("--window-size=1440,2200")
    options.add_argument("--lang=zh-CN")
    if CHROMEDRIVER_PATH.exists():
        service = Service(executable_path=str(CHROMEDRIVER_PATH))
    else:
        service = Service()  # Let Selenium Manager resolve chromedriver
    return webdriver.Chrome(service=service, options=options)


def wait_for_page_ready(driver: webdriver.Chrome, timeout: int = 90) -> None:
    WebDriverWait(driver, timeout).until(
        lambda d: "处理中心" in (d.find_element(By.TAG_NAME, "body").text or "")
    )
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.XPATH, "//button[contains(., '一键抓取并总结')]"))
    )


def fill_video_url(driver: webdriver.Chrome, video_url: str) -> None:
    trace("fill_video_url_start")
    input_el = WebDriverWait(driver, 30).until(
        EC.presence_of_element_located(
            (
                By.XPATH,
                "//input[contains(@aria-label, '视频链接或 ID') or contains(@placeholder, 'youtube.com/watch')]",
            )
        )
    )
    trace("fill_video_url_input_found")
    input_el.clear()
    trace("fill_video_url_cleared")
    input_el.send_keys(video_url)
    try:
        WebDriverWait(driver, 8).until(lambda d: input_el.get_attribute("value") == video_url)
        trace("fill_video_url_send_keys_ok")
        return
    except TimeoutException:
        trace("fill_video_url_send_keys_timeout_fallback_js")
    driver.execute_script(
        """
        const input = arguments[0];
        const value = arguments[1];
        input.focus();
        input.value = value;
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        """,
        input_el,
        video_url,
    )
    WebDriverWait(driver, 20).until(lambda d: input_el.get_attribute("value") == video_url)
    trace("fill_video_url_js_ok")


def click_fetch(driver: webdriver.Chrome) -> None:
    trace("click_fetch_start")
    button = WebDriverWait(driver, 30).until(
        EC.element_to_be_clickable((By.XPATH, "//button[contains(., '一键抓取并总结')]"))
    )
    trace("click_fetch_button_found")
    try:
        button.click()
        trace("click_fetch_normal_click_ok")
        return
    except Exception as exc:
        trace(f"click_fetch_normal_click_failed={type(exc).__name__}:{exc}")
    driver.execute_script("arguments[0].click();", button)
    trace("click_fetch_js_click_ok")


def read_body_text(driver: webdriver.Chrome) -> str:
    try:
        return str(driver.find_element(By.TAG_NAME, "body").text or "")
    except Exception:
        return ""


def wait_for_probe_result(driver: webdriver.Chrome, timeout: int = 120) -> dict:
    initial_text = read_body_text(driver)
    started = False

    start_deadline = time.time() + 20
    while time.time() < start_deadline:
        body_text = read_body_text(driver)
        if "已向插件发起抓取请求" in body_text or "已调用插件抓取" in body_text:
            started = True
            trace("bridge_started_visible")
            break
        time.sleep(1)

    trace(f"waiting_for_final_seconds={timeout}")
    final_deadline = time.time() + timeout
    last_text = initial_text
    while time.time() < final_deadline:
        body_text = read_body_text(driver)
        last_text = body_text
        if "📝 AI 总结" in body_text or ("\nAI 总结\n" in body_text) or ("⏱️" in body_text and "文本抓取" in body_text):
            trace("summary_marker_visible")
            return {
                "final_state": "summary_ready",
                "bridge_started": started,
                "body_text": body_text,
            }
        if "插件抓取未接管" in body_text or "extension_request_timeout" in body_text:
            trace("extension_failure_visible")
            return {
                "final_state": "extension_failed",
                "bridge_started": started,
                "body_text": body_text,
            }
        trace("waiting_heartbeat")
        time.sleep(5)
    trace("probe_wait_timeout")
    return {
        "final_state": "timeout" if last_text != initial_text else "no_state_change",
        "bridge_started": started,
        "body_text": last_text,
    }


def run_probe(video_url: str) -> dict:
    TRACE_FILE.write_text("", encoding="utf-8")
    if ERROR_FILE.exists():
        ERROR_FILE.unlink()
    for stale_file in [SUMMARY_FILE, FINAL_TEXT_FILE, SCREENSHOT_FILE]:
        if stale_file.exists():
            stale_file.unlink()
    trace(f"probe_start video_url={video_url}")
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    profile_dir = PROFILE_DIR / f"run_{uuid.uuid4().hex}"
    profile_dir.mkdir(parents=True, exist_ok=True)
    trace(f"profile_dir={profile_dir}")

    driver = None
    try:
        trace(f"chrome_binary_exists={CHROME_PATH.exists()}")
        trace(f"chromedriver_exists={CHROMEDRIVER_PATH.exists()}")
        ensure_app_ready()
        driver = build_driver(profile_dir)
        trace("chrome_started")
        driver.get(APP_URL)
        trace("page_opened")
        wait_for_page_ready(driver)
        trace("page_ready")
        fill_video_url(driver, video_url)
        trace("video_url_filled")
        input_xpath = "//input[contains(@aria-label, '视频链接或 ID') or contains(@placeholder, 'youtube.com/watch')]"
        trace(f"input_value={driver.find_element(By.XPATH, input_xpath).get_attribute('value')}")
        click_fetch(driver)
        trace("fetch_clicked")
        trace("post_click_sleep_start")
        time.sleep(2)
        trace("post_click_sleep_done")
        trace("wait_for_probe_result_start")
        result = wait_for_probe_result(driver, timeout=180)
        trace(f"final_state={result['final_state']}")

        body_text = str(result.get("body_text") or "")
        FINAL_TEXT_FILE.write_text(body_text, encoding="utf-8")
        driver.save_screenshot(str(SCREENSHOT_FILE))
        summary = {
            "video_url": video_url,
            "final_state": result["final_state"],
            "bridge_started": bool(result.get("bridge_started")),
            "has_summary": "AI 总结" in body_text,
            "has_extension_failure": "插件抓取未接管" in body_text,
            "has_timeout": "extension_request_timeout" in body_text or "bridge_waited_60s_no_plugin_reply" in body_text,
            "has_payload_reading": "主站正在读取 bridge 回传" in body_text,
        }
        SUMMARY_FILE.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary
    except Exception:
        ERROR_FILE.write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                trace("driver_quit_failed")


if __name__ == "__main__":
    import sys

    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=C14SVwWZ2fE"
    run_probe(url)
