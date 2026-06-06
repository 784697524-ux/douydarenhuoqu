#!/usr/bin/env python3
"""Collect Douyin Life talent-square data through Selenium attached to Chrome CDP."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

DEFAULT_URL = (
    "https://life.douyin.com/p/liteapp/alliance_merchant/merchant/talent/square"
    "?enter_from=pc_menu_daren_square"
)


def groupid_from_url(url: str) -> str:
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return (query.get("groupid") or [""])[0]


def url_with_groupid(url: str, groupid: str) -> str:
    if not groupid:
        return url
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    query["groupid"] = [groupid]
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=True)))


def cdp_json_url(cdp_url: str, path: str) -> str:
    return cdp_url.rstrip("/") + path


def cdp_read(cdp_url: str, path: str) -> Any:
    with urllib.request.urlopen(cdp_json_url(cdp_url, path), timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def cdp_new_page(cdp_url: str, url: str) -> None:
    encoded = urllib.parse.quote(url, safe="")
    request = urllib.request.Request(cdp_json_url(cdp_url, f"/json/new?{encoded}"), method="PUT")
    with urllib.request.urlopen(request, timeout=5):
        return


def ensure_page_target(cdp_url: str, url: str) -> None:
    targets = cdp_read(cdp_url, "/json/list")
    pages = [target for target in targets if target.get("type") == "page"]
    if not pages:
        cdp_new_page(cdp_url, url)


def browser_version(cdp_url: str) -> str:
    version = cdp_read(cdp_url, "/json/version")
    browser = str(version.get("Browser") or "")
    return browser.split("/", 1)[-1]


def find_cached_chromedriver(major: str) -> str:
    root = Path.home() / ".wdm" / "drivers" / "chromedriver"
    if root.exists():
        matches = sorted(root.glob(f"**/{major}.*/*/chromedriver"), reverse=True)
        if matches:
            return str(matches[0])
    return ""


def chromedriver_path(cdp_url: str) -> str:
    version = browser_version(cdp_url)
    major = version.split(".", 1)[0]
    cached = find_cached_chromedriver(major)
    if cached:
        return cached
    try:
        from webdriver_manager.chrome import ChromeDriverManager

        return ChromeDriverManager(driver_version=major).install()
    except Exception:
        from webdriver_manager.chrome import ChromeDriverManager

        return ChromeDriverManager().install()


def connect_driver(cdp_url: str, url: str) -> webdriver.Chrome:
    ensure_page_target(cdp_url, url)
    host = urllib.parse.urlparse(cdp_url).netloc or cdp_url.replace("http://", "").replace("https://", "")
    opts = Options()
    opts.add_experimental_option("debuggerAddress", host)
    path = chromedriver_path(cdp_url)
    return webdriver.Chrome(service=Service(path), options=opts)


@dataclass
class BrowserRunConfig:
    city: str
    category: str
    video_levels: list[str]
    has_contact: str
    talent_type: str


def select_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("text") or value.get("id") or "")
    if isinstance(value, list):
        return ",".join(select_name(item) for item in value if select_name(item))
    return "" if value is None else str(value)


def normalize_level(value: str) -> str:
    text = value.strip().upper()
    if text.startswith("LV"):
        return "Lv" + text[2:]
    return value.strip()


def levels_from_config(value: Any) -> list[str]:
    raw = select_name(value)
    return [normalize_level(item) for item in re.findall(r"Lv\d+|LV\d+", raw)]


def config_from_prepare(prepare: dict[str, Any]) -> BrowserRunConfig:
    fields = prepare.get("config", {})
    return BrowserRunConfig(
        city=select_name(fields.get("常驻城市")),
        category=select_name(fields.get("优势品类")),
        video_levels=levels_from_config(fields.get("视频带货力")),
        has_contact=select_name(fields.get("有微信/电话")),
        talent_type=select_name(fields.get("达人类型")) or "全部达人",
    )


def clean_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def join_cell(text: str) -> str:
    return "；".join(clean_lines(text))


def talent_cell_offset(cells: list[str]) -> int:
    for index, cell in enumerate(cells[:3]):
        if "抖音号：" in cell:
            return index
    return 1 if len(cells) >= 19 else 0


def parse_row_cells(cells: list[str], row_number: int = 0) -> dict[str, Any] | None:
    offset = talent_cell_offset(cells)
    metric_cells = cells[offset:]
    if len(metric_cells) < 18:
        return None
    info = clean_lines(metric_cells[0])
    if not info:
        return None
    douyin_line = next((line for line in info if line.startswith("抖音号：")), "")
    douyin_id = douyin_line.replace("抖音号：", "").strip()
    return {
        "row": row_number,
        "nickname": info[0],
        "douyin_id": douyin_id,
        "city": info[2] if len(info) > 2 else "",
        "category": info[3] if len(info) > 3 else "",
        "followers": join_cell(metric_cells[1]),
        "video_power": metric_cells[2].strip(),
        "live_power": metric_cells[3].strip(),
        "content_power": metric_cells[4].strip(),
        "credit_score": metric_cells[5].strip(),
        "verification_rate_30d": metric_cells[6].strip(),
        "avg_sales_per_video": join_cell(metric_cells[7]),
        "avg_seed_sales": metric_cells[8].strip(),
        "avg_views_per_video": join_cell(metric_cells[9]),
        "avg_gmv_per_k_impression": metric_cells[10].strip(),
        "avg_completion_rate": metric_cells[11].strip(),
        "poi_click_rate": join_cell(metric_cells[12]),
        "avg_live_sales": join_cell(metric_cells[13]),
        "avg_live_watchers": metric_cells[14].strip(),
        "avg_live_watch_time": metric_cells[15].strip(),
        "avg_live_comments": metric_cells[16].strip(),
    }


def dedupe_key(talent: dict[str, Any]) -> str:
    douyin_id = str(talent.get("douyin_id") or "").strip()
    if douyin_id:
        return f"dy:{douyin_id.lower()}"
    raw = "|".join(str(talent.get(key) or "").strip().lower() for key in ("nickname", "city", "category"))
    return "profile:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def body_text(driver: webdriver.Chrome) -> str:
    try:
        return driver.find_element(By.TAG_NAME, "body").text
    except Exception:
        return ""


def classify_page_state(url: str, title: str, text: str) -> dict[str, Any]:
    if not text.strip():
        logged_in: bool | None = None
        ready = False
        status = "blank_or_loading"
        next_action = "reload_or_wait"
    elif "/p/login" in url or "立即登录" in text or "发送验证码" in text:
        logged_in = False
        ready = False
        status = "login_required"
        next_action = "login_douyin_life"
    elif "达人广场" in text and ("常驻城市" in text or ("查询" in text and "达人" in text and "粉丝数" in text)):
        logged_in = True
        ready = True
        status = "ready"
        next_action = "run_task"
    else:
        logged_in = True
        ready = False
        status = "not_ready"
        next_action = "wait_or_open_talent_square"
    return {
        "url": url,
        "title": title,
        "status": status,
        "logged_in": logged_in,
        "talent_square_ready": ready,
        "next_action": next_action,
    }


def inspect_page(driver: webdriver.Chrome) -> dict[str, Any]:
    WebDriverWait(driver, 30).until(lambda d: d.execute_script("return document.readyState") in {"interactive", "complete"})
    text = body_text(driver)
    if not text.strip():
        driver.refresh()
        time.sleep(3)
        text = body_text(driver)
    state = classify_page_state(driver.current_url, driver.title, text)
    state["body_sample"] = " ".join(clean_lines(text))[:200]
    return state


def current_account(driver: webdriver.Chrome) -> str:
    lines = clean_lines(body_text(driver))
    candidates: list[str] = []
    for index, line in enumerate(lines):
        if line != "下载手机端":
            continue
        for candidate in lines[index + 1 : index + 10]:
            if candidate in {"消息", "顾客咨询", "更新记录", "输码核销", "验券历史", "验券"}:
                continue
            if re.fullmatch(r"\d+", candidate):
                continue
            candidates.append(candidate)
        break
    if not candidates:
        return ""
    for candidate in candidates:
        if any(marker in candidate for marker in ("公司", "百货", "商场", "超市", "门店", "店")):
            return candidate
    return candidates[0]


def account_identity(driver: webdriver.Chrome) -> dict[str, str]:
    name = current_account(driver)
    groupid = groupid_from_url(driver.current_url)
    account = name
    if groupid:
        account = f"{name}|{groupid}" if name else groupid
    return {"account": account, "account_name": name, "groupid": groupid}


def handle_urls(driver: webdriver.Chrome) -> list[tuple[str, str]]:
    current = driver.current_window_handle
    urls = []
    for handle in driver.window_handles:
        driver.switch_to.window(handle)
        urls.append((handle, driver.current_url))
    driver.switch_to.window(current)
    return urls


def current_groupid(driver: webdriver.Chrome, fallback_url: str) -> str:
    urls = handle_urls(driver)
    for _handle, url in reversed(urls):
        if "life.douyin.com/p/" not in url or "/merchant/talent/square" in url:
            continue
        groupid = groupid_from_url(url)
        if groupid:
            return groupid
    for _handle, url in reversed(urls):
        if "life.douyin.com/p/" in url:
            groupid = groupid_from_url(url)
            if groupid:
                return groupid
    return groupid_from_url(fallback_url)


def first_page(driver: webdriver.Chrome, url: str) -> None:
    target_groupid = current_groupid(driver, url)
    target_url = url_with_groupid(url, target_groupid)
    for handle, current_url in handle_urls(driver):
        if "/merchant/talent/square" in current_url:
            if target_groupid and groupid_from_url(current_url) != target_groupid:
                continue
            driver.switch_to.window(handle)
            driver.get(target_url)
            return
    driver.execute_script("window.open(arguments[0], '_blank')", target_url)
    driver.switch_to.window(driver.window_handles[-1])


def wait_ready(driver: webdriver.Chrome, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + max(timeout_seconds, 0)
    last_state: dict[str, Any] = {}
    last_text = ""
    refreshed_error_page = False
    while True:
        last_text = body_text(driver)
        if "加载失败" in last_text and "重新加载" in last_text and not refreshed_error_page:
            refreshed_error_page = True
            driver.refresh()
            time.sleep(3)
            continue
        last_state = classify_page_state(driver.current_url, driver.title, last_text)
        if last_state["talent_square_ready"]:
            return last_state
        if time.monotonic() >= deadline:
            break
        time.sleep(1)
    if last_state.get("status") == "login_required":
        raise RuntimeError("Dedicated Chrome profile is not logged in to Douyin Life. Log in once in the CDP Chrome window, then rerun the task.")
    snippet = " ".join(clean_lines(last_text))[:200]
    raise RuntimeError(f"Talent square is not ready. status={last_state.get('status')!r} title={driver.title!r} url={driver.current_url!r} body={snippet!r}")


def js(driver: webdriver.Chrome, script: str, *args: Any) -> Any:
    return driver.execute_script(script, *args)


def close_popovers(driver: webdriver.Chrome) -> None:
    ActionChains(driver).send_keys("\ue00c").perform()
    ActionChains(driver).send_keys("\ue00c").perform()
    js(driver, "if (document.activeElement && document.activeElement.blur) document.activeElement.blur();")
    time.sleep(0.3)


def scroll_filters_into_view(driver: webdriver.Chrome) -> None:
    js(driver, """
        window.scrollTo(0, 0);
        for (const el of document.querySelectorAll('*')) {
          if (el.scrollTop) el.scrollTop = 0;
        }
        const label = Array.from(document.querySelectorAll('span,div,label'))
          .find(el => (el.innerText || '').trim() === '常驻城市');
        if (label) label.scrollIntoView({ block: 'center', inline: 'nearest' });
    """)
    time.sleep(0.3)


def click_text(driver: webdriver.Chrome, text: str, exact: bool = True, last: bool = True) -> bool:
    return bool(js(driver, """
        const wanted = arguments[0], exact = arguments[1], last = arguments[2];
        const visible = el => {
          const r = el.getBoundingClientRect();
          const s = getComputedStyle(el);
          return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0
            && r.top < innerHeight && r.left < innerWidth
            && s.visibility !== 'hidden' && s.display !== 'none';
        };
        const nodes = Array.from(document.querySelectorAll('button,[role=button],span,div,label,li'))
          .filter(el => visible(el))
          .filter(el => {
            const t = (el.innerText || '').trim();
            return exact ? t === wanted : t.includes(wanted);
        });
        const el = last ? nodes[nodes.length - 1] : nodes[0];
        if (!el) return false;
        el.scrollIntoView({ block: 'center', inline: 'center' });
        const r = el.getBoundingClientRect();
        const x = Math.min(Math.max(r.left + r.width / 2, 1), innerWidth - 1);
        const y = Math.min(Math.max(r.top + r.height / 2, 1), innerHeight - 1);
        const target = document.elementFromPoint(x, y) || el;
        const mk = type => type.startsWith('pointer')
          ? new PointerEvent(type, { bubbles: true, cancelable: true, composed: true, clientX: x, clientY: y, pointerType: 'mouse', button: 0, buttons: type.endsWith('down') ? 1 : 0 })
          : new MouseEvent(type, { bubbles: true, cancelable: true, composed: true, clientX: x, clientY: y, button: 0, buttons: type.endsWith('down') ? 1 : 0 });
        for (const type of ['pointerover','mouseover','pointermove','mousemove','pointerdown','mousedown','pointerup','mouseup','click']) {
          target.dispatchEvent(mk(type));
        }
        return true;
    """, text, exact, last))


def click_button(driver: webdriver.Chrome, name: str) -> None:
    if not click_text(driver, name, exact=True, last=False):
        raise RuntimeError(f"button not found: {name}")


def cdp_click(driver: webdriver.Chrome, x: float, y: float) -> None:
    driver.execute_cdp_cmd("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
    driver.execute_cdp_cmd(
        "Input.dispatchMouseEvent",
        {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1},
    )
    driver.execute_cdp_cmd(
        "Input.dispatchMouseEvent",
        {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1},
    )


def click_control_arrow(driver: webdriver.Chrome, label: str, selectors: str) -> str:
    info = js(driver, """
        const label = arguments[0], selectors = arguments[1];
        const visible = el => {
          const r = el.getBoundingClientRect();
          const s = getComputedStyle(el);
          return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0
            && r.top < innerHeight && r.left < innerWidth
            && s.visibility !== 'hidden' && s.display !== 'none';
        };
        const el = Array.from(document.querySelectorAll(selectors))
          .find(el => visible(el) && (el.innerText || '').includes(label));
        if (!el) return null;
        el.scrollIntoView({ block: 'center', inline: 'nearest' });
        const r = el.getBoundingClientRect();
        return { className: String(el.className || ''), x: r.left + r.width - 26, y: r.top + r.height / 2 };
    """, label, selectors)
    if not info:
        return ""
    cdp_click(driver, float(info["x"]), float(info["y"]))
    return str(info.get("className") or "")


def filter_control_visible(driver: webdriver.Chrome, label: str = "常驻城市") -> bool:
    return bool(js(driver, """
        const label = arguments[0];
        const visible = el => {
          const r = el.getBoundingClientRect();
          const s = getComputedStyle(el);
          return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0
            && r.top < innerHeight && r.left < innerWidth
            && s.visibility !== 'hidden' && s.display !== 'none';
        };
        return Array.from(document.querySelectorAll('.byted-cascader-select,.byted-select'))
          .some(el => visible(el) && (el.innerText || '').includes(label));
    """, label))


def ensure_filters_visible(driver: webdriver.Chrome) -> None:
    scroll_filters_into_view(driver)
    if filter_control_visible(driver):
        return
    click_text(driver, "展开更多", exact=True, last=False)
    time.sleep(0.6)
    scroll_filters_into_view(driver)
    if not filter_control_visible(driver):
        text = body_text(driver)
        if "常驻城市" in text and "视频带货力" in text and "查询" in text:
            return
        raise RuntimeError("filter controls are not visible")


def click_filter_by_label(driver: webdriver.Chrome, label: str) -> None:
    ensure_filters_visible(driver)
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        class_name = click_control_arrow(driver, label, ".byted-cascader-select,.byted-select")
        if not class_name:
            break
        time.sleep(0.4)
        if "byted-cascader" in class_name and js(driver, """
            const visible = el => {
              const r = el.getBoundingClientRect();
              const s = getComputedStyle(el);
              return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0
                && r.top < innerHeight && r.left < innerWidth
                && s.visibility !== 'hidden' && s.display !== 'none';
            };
            return Array.from(document.querySelectorAll('.byted-cascader-popover-search-input input')).some(visible);
        """):
            return
        if "byted-cascader" not in class_name and js(driver, """
            const visible = el => {
              const r = el.getBoundingClientRect();
              const s = getComputedStyle(el);
              return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0
                && r.top < innerHeight && r.left < innerWidth
                && s.visibility !== 'hidden' && s.display !== 'none';
            };
            return Array.from(document.querySelectorAll('.byted-popover-show,.byted-popover-wrapper,[role=listbox]')).some(visible)
              || Array.from(document.querySelectorAll('.byted-cascader-popover-search-input input')).some(visible);
        """):
            return
        close_popovers(driver)
    raise RuntimeError(f"filter not found or did not open: {label}")


def click_visible_text_native(driver: webdriver.Chrome, text: str, selectors: str, exact: bool = True) -> bool:
    element = js(driver, """
        const wanted = arguments[0], selectors = arguments[1], exact = arguments[2];
        const visible = el => {
          const r = el.getBoundingClientRect();
          const s = getComputedStyle(el);
          return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0
            && r.top < innerHeight && r.left < innerWidth
            && s.visibility !== 'hidden' && s.display !== 'none';
        };
        const nodes = Array.from(document.querySelectorAll(selectors))
          .filter(visible)
          .filter(el => {
            const t = (el.innerText || '').trim();
            return exact ? t === wanted : t.includes(wanted);
          });
        return nodes[nodes.length - 1] || null;
    """, text, selectors, exact)
    if not element:
        return False
    ActionChains(driver).move_to_element(element).click().perform()
    time.sleep(0.3)
    return True


def select_control_by_label(driver: webdriver.Chrome, label: str) -> Any:
    ensure_filters_visible(driver)
    return js(driver, """
        const label = arguments[0];
        const visible = el => {
          const r = el.getBoundingClientRect();
          const s = getComputedStyle(el);
          return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0
            && r.top < innerHeight && r.left < innerWidth
            && s.visibility !== 'hidden' && s.display !== 'none';
        };
        return Array.from(document.querySelectorAll('.byted-select'))
          .find(el => visible(el) && (el.innerText || '').includes(label)) || null;
    """, label)


def visible_select_option(driver: webdriver.Chrome, text: str) -> Any:
    return js(driver, """
        const text = arguments[0];
        const visible = el => {
          const r = el.getBoundingClientRect();
          const s = getComputedStyle(el);
          return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0
            && r.top < innerHeight && r.left < innerWidth
            && s.visibility !== 'hidden' && s.display !== 'none';
        };
        return Array.from(document.querySelectorAll('.byted-select-option'))
          .find(el => visible(el) && (el.innerText || '').trim() === text) || null;
    """, text)


def open_select_by_label(driver: webdriver.Chrome, label: str, expected_option: str) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        class_name = click_control_arrow(driver, label, ".byted-select")
        if not class_name:
            break
        time.sleep(0.4)
        if visible_select_option(driver, expected_option):
            return
        close_popovers(driver)
        time.sleep(0.2)
    raise RuntimeError(f"select options did not open: {label}")


def choose_select_option(driver: webdriver.Chrome, text: str) -> None:
    option = visible_select_option(driver, text)
    if not option:
        raise RuntimeError(f"select option not found: {text}")
    ActionChains(driver).move_to_element(option).click().perform()
    time.sleep(0.3)


def filter_text(driver: webdriver.Chrome, label: str) -> str:
    return str(js(driver, """
        const label = arguments[0];
        const visible = el => {
          const r = el.getBoundingClientRect();
          const s = getComputedStyle(el);
          return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0
            && r.top < innerHeight && r.left < innerWidth
            && s.visibility !== 'hidden' && s.display !== 'none';
        };
        const control = Array.from(document.querySelectorAll('.byted-select,.byted-cascader-select'))
          .find(el => visible(el) && (el.innerText || '').includes(label));
        return control ? control.innerText || '' : '';
    """, label) or "")


def fill_visible_search(driver: webdriver.Chrome, value: str) -> None:
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        ok = js(driver, """
            const visible = el => {
              const r = el.getBoundingClientRect();
              const s = getComputedStyle(el);
              return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0
                && r.top < innerHeight && r.left < innerWidth
                && s.visibility !== 'hidden' && s.display !== 'none';
            };
            const input = Array.from(document.querySelectorAll('.byted-cascader-popover-search-input input')).find(visible);
            if (!input) return false;
            input.focus();
            input.select();
            return document.activeElement === input;
        """)
        if ok:
            driver.execute_cdp_cmd("Input.insertText", {"text": value})
            return
        time.sleep(0.2)
    raise RuntimeError("visible cascader search input not found")


def choose_city(driver: webdriver.Chrome, city: str) -> None:
    if not city:
        return
    wanted = city if city.endswith("市") else f"{city}市"
    for attempt in range(2):
        try:
            click_filter_by_label(driver, "常驻城市")
            time.sleep(0.5)
            fill_visible_search(driver, city)
            time.sleep(0.5)
            if not click_visible_text_native(driver, wanted, ".byted-cascader-item-container,.byted-cascader-item-label", exact=True):
                if not click_text(driver, wanted, exact=True, last=True):
                    click_text(driver, city, exact=False, last=True)
            time.sleep(0.6)
            close_popovers(driver)
            return
        except Exception:
            close_popovers(driver)
            if attempt:
                raise
            driver.refresh()
            wait_ready(driver, 30)
            scroll_filters_into_view(driver)


def choose_category(driver: webdriver.Chrome, category: str) -> None:
    if not category:
        return
    click_filter_by_label(driver, "优势品类")
    time.sleep(0.5)
    if not click_visible_text_native(driver, category, ".byted-cascader-item-container,.byted-cascader-item-label", exact=True):
        if not click_text(driver, category, exact=True, last=True):
            click_text(driver, category, exact=False, last=True)
    time.sleep(0.6)
    close_popovers(driver)


def choose_video_levels(driver: webdriver.Chrome, levels: list[str]) -> None:
    if not levels:
        return
    expected_options = [level.upper() for level in levels]
    open_select_by_label(driver, "视频带货力", expected_options[0])
    for level in levels:
        choose_select_option(driver, level.upper())
    selected_text = filter_text(driver, "视频带货力").upper()
    missing = [level for level in expected_options if level not in selected_text]
    if missing:
        raise RuntimeError(f"video level selection failed: missing {missing}, selected={selected_text!r}")
    close_popovers(driver)


def choose_has_contact(driver: webdriver.Chrome, value: str) -> None:
    if not value or value in {"不限", "无"}:
        return
    open_select_by_label(driver, "有微信/电话", "是")
    choose_select_option(driver, "是")
    close_popovers(driver)


def apply_filters(driver: webdriver.Chrome, config: BrowserRunConfig) -> None:
    scroll_filters_into_view(driver)
    try:
        click_button(driver, "重置")
        time.sleep(1.2)
    except Exception:
        pass
    scroll_filters_into_view(driver)
    choose_city(driver, config.city)
    choose_video_levels(driver, config.video_levels)
    choose_category(driver, config.category)
    choose_has_contact(driver, config.has_contact)
    click_button(driver, "查询")
    time.sleep(2.5)


def city_matches(actual: str, expected: str) -> bool:
    if not expected:
        return True
    expected_base = expected.removesuffix("市")
    return expected_base in actual


def verify_filters(driver: webdriver.Chrome, config: BrowserRunConfig) -> None:
    deadline = time.monotonic() + 12
    last_error = ""
    while True:
        rows = read_rows(driver)
        if not rows:
            if time.monotonic() >= deadline:
                return
            time.sleep(0.8)
            continue
        sample = rows[: min(5, len(rows))]
        problems: list[str] = []
        if config.city:
            bad = [row for row in sample if not city_matches(str(row.get("city") or ""), config.city)]
            if bad:
                problems.append(f"city expected {config.city}, got {[row.get('city') for row in bad]}")
        if config.video_levels:
            allowed = {normalize_level(level) for level in config.video_levels}
            bad = [row for row in sample if normalize_level(str(row.get("video_power") or "")) not in allowed]
            if bad:
                problems.append(f"video levels expected {sorted(allowed)}, got {[row.get('video_power') for row in bad]}")
        if not problems:
            return
        first_rows = [
            {
                "nickname": row.get("nickname"),
                "douyin_id": row.get("douyin_id"),
                "city": row.get("city"),
                "category": row.get("category"),
                "video_power": row.get("video_power"),
            }
            for row in sample
        ]
        last_error = f"filter verification failed: {'; '.join(problems)}; first_rows={first_rows}"
        if time.monotonic() >= deadline:
            raise RuntimeError(last_error)
        time.sleep(0.8)


def read_rows(driver: webdriver.Chrome) -> list[dict[str, Any]]:
    rows = js(driver, """
        return Array.from(document.querySelectorAll('tr')).slice(1).map((tr, i) => ({
          row: i + 1,
          cells: Array.from(tr.children).map(td => (td.innerText || '').trim())
        }));
    """) or []
    talents: list[dict[str, Any]] = []
    for item in rows:
        parsed = parse_row_cells(item.get("cells", []), item.get("row", 0))
        if parsed:
            talents.append(parsed)
    return talents


def rows_signature(rows: list[dict[str, Any]]) -> str:
    return "|".join(dedupe_key(row) for row in rows)


def click_next_page(driver: webdriver.Chrome, previous_signature: str) -> bool:
    clicked = bool(js(driver, """
        const pager = document.querySelector('.byted-pager');
        if (!pager) return false;
        const items = Array.from(pager.querySelectorAll('.byted-pager-item'));
        const current = items.find(item => item.className.includes('byted-pager-item-checked'));
        const currentPage = current ? Number((current.innerText || '').trim()) : NaN;
        const nextPage = Number.isFinite(currentPage) ? String(currentPage + 1) : '';
        const nextNumber = items.find(item => (item.innerText || '').trim() === nextPage);
        if (nextNumber && !nextNumber.className.includes('disabled')) { nextNumber.click(); return true; }
        const nextArrow = items.find(item => item.querySelector('.byted-icon-right') && !item.className.includes('disabled'));
        if (nextArrow) { nextArrow.click(); return true; }
        return false;
    """))
    if not clicked:
        return False
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        time.sleep(0.5)
        if rows_signature(read_rows(driver)) != previous_signature:
            return True
    return False


def result_count(driver: webdriver.Chrome) -> str:
    return str(js(driver, """
        const text = document.body.innerText || '';
        const m = text.match(/共\s*(?:\d+|999\+)\s*位达人/);
        return m ? m[0] : '';
    """) or "")


def contact_dialog_open(driver: webdriver.Chrome) -> bool:
    return "达人联系方式" in body_text(driver) and "虚拟手机号" in body_text(driver)


def parse_contact_text(text: str) -> dict[str, str]:
    lines = clean_lines(text)

    def after(label: str) -> str:
        for index, line in enumerate(lines):
            if line == label:
                return lines[index + 1] if index + 1 < len(lines) else ""
            if line.startswith(label + "：") or line.startswith(label + ":"):
                return line.split("：", 1)[-1].split(":", 1)[-1].strip()
        return ""

    phone = re.search(r"1\d{10}", after("虚拟手机号"))
    quota = re.search(r"今日剩余查看次数\s*(\d+)\s*/\s*(\d+)", text)
    return {"phone": phone.group(0) if phone else "", "wechat": after("微信号"), "quota_after": f"{quota.group(1)}/{quota.group(2)}" if quota else ""}


def visible_contact_text(driver: webdriver.Chrome) -> str:
    text = str(js(driver, """
        const selectors = ['.byted-modal','[role=dialog]','.byted-drawer','.byted-popover-show'];
        const visible = el => {
          const r = el.getBoundingClientRect();
          const s = getComputedStyle(el);
          return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
        };
        for (const sel of selectors) {
          const nodes = Array.from(document.querySelectorAll(sel)).filter(visible)
            .filter(el => /达人联系方式|虚拟手机号|今日剩余查看次数/.test(el.innerText || ''));
          if (nodes.length) return nodes[nodes.length - 1].innerText || '';
        }
        const body = document.body.innerText || '';
        return /达人联系方式|虚拟手机号|今日剩余查看次数/.test(body) ? body : '';
    """) or "")
    return text


def close_contact_dialog(driver: webdriver.Chrome) -> None:
    for label in ("我知道了", "知道了", "确定"):
        if click_text(driver, label, exact=True, last=True):
            time.sleep(0.5)
            return
    close_popovers(driver)


def open_contact(driver: webdriver.Chrome, row_index: int) -> dict[str, str]:
    ok = js(driver, """
        const row = document.querySelectorAll('tr')[arguments[0] + 1];
        if (!row) return false;
        const candidates = Array.from(row.querySelectorAll('button,[role=button],span,div'))
          .filter(el => (el.innerText || '').trim() === '查看联系方式');
        const target = candidates[candidates.length - 1];
        if (!target) return false;
        target.click();
        return true;
    """, row_index)
    if not ok:
        raise RuntimeError("contact button not found")
    WebDriverWait(driver, 15).until(lambda d: re.search(r"达人联系方式|虚拟手机号|今日剩余查看次数", body_text(d)))
    text = visible_contact_text(driver)
    if not text:
        raise RuntimeError("contact dialog opened but contact text was not readable")
    contact = parse_contact_text(text)
    if not contact.get("wechat") and not contact.get("phone"):
        raise RuntimeError("contact dialog did not contain WeChat or phone")
    close_contact_dialog(driver)
    return contact


def collect(driver: webdriver.Chrome, *, max_results: int, max_contacts: int, contact_cache: dict[str, dict[str, Any]], skip_keys: set[str], no_contact: bool, max_pages: int) -> dict[str, Any]:
    talents: list[dict[str, Any]] = []
    opened = 0
    seen_keys: set[str] = set()
    contact_errors: list[dict[str, str]] = []
    visible_rows = 0
    pages_scanned = 0
    for _page_index in range(max_pages):
        rows = read_rows(driver)
        pages_scanned += 1
        visible_rows += len(rows)
        for index, talent in enumerate(rows):
            key = dedupe_key(talent)
            if key in seen_keys:
                continue
            if len(talents) >= max_results:
                break
            seen_keys.add(key)
            cached = contact_cache.get(key)
            if cached:
                talents.append({**talent, **cached, "dedupe_key": key, "contact_consumed": False})
                continue
            if key in skip_keys:
                continue
            if no_contact:
                talents.append({**talent, "dedupe_key": key, "contact_consumed": False})
                continue
            if opened >= max_contacts:
                continue
            try:
                contact = open_contact(driver, index)
            except Exception as exc:
                contact_errors.append({"dedupe_key": key, "error": str(exc)[:200]})
                close_contact_dialog(driver)
                continue
            opened += 1
            talents.append({**talent, **contact, "dedupe_key": key, "contact_consumed": True})
        if len(talents) >= max_results:
            break
        if not rows or not click_next_page(driver, rows_signature(rows)):
            break
    return {"talents": talents, "opened_contacts": opened, "visible_rows": visible_rows, "pages_scanned": pages_scanned, "contact_errors": contact_errors, "result_count_text": result_count(driver), "contact_dialog_open": contact_dialog_open(driver)}


def doctor(args: argparse.Namespace) -> dict[str, Any]:
    driver = connect_driver(args.cdp_url, args.url)
    try:
        first_page(driver, args.url)
        if args.wait_ready:
            try:
                wait_ready(driver, args.wait_ready)
            except RuntimeError:
                pass
        state = inspect_page(driver)
        return {"ok": state["logged_in"] and state["talent_square_ready"], "cdp_url": args.cdp_url, "page_count": len(driver.window_handles), **(account_identity(driver) if state["logged_in"] else {"account": "", "account_name": "", "groupid": ""}), **state}
    finally:
        driver.quit()


def account_info(args: argparse.Namespace) -> dict[str, Any]:
    driver = connect_driver(args.cdp_url, args.url)
    try:
        first_page(driver, args.url)
        wait_ready(driver, args.wait_ready or 30)
        identity = account_identity(driver)
        return {"ok": bool(identity["account"]), **identity, "url": driver.current_url, "title": driver.title}
    finally:
        driver.quit()


def run(args: argparse.Namespace) -> dict[str, Any]:
    prepare = json.loads(args.prepare_json.read_text(encoding="utf-8"))
    config = config_from_prepare(prepare)
    contact_cache = prepare.get("contact_cache") or {}
    skip_keys = set(prepare.get("skip_keys") or [])
    max_contacts = min(int(prepare.get("allowed_contact_views") or 0), args.max_contacts)
    max_results = args.max_results or int(prepare.get("configured_contact_views") or 0) or max_contacts
    no_contact = args.no_contact
    driver = connect_driver(args.cdp_url, args.url)
    try:
        first_page(driver, args.url)
        wait_ready(driver, args.wait_ready or 30)
        apply_filters(driver, config)
        verify_filters(driver, config)
        result = collect(driver, max_results=max_results, max_contacts=max_contacts, contact_cache=contact_cache, skip_keys=skip_keys, no_contact=no_contact, max_pages=args.max_pages)
        result.update({"task_id": prepare.get("active_task_id"), "config_hash": prepare.get("config_hash"), "no_contact": no_contact, "contact_cache_count": len(contact_cache), "filter": {"city": config.city, "category": config.category, "video_levels": config.video_levels, "has_contact": config.has_contact, "talent_type": config.talent_type}})
        return result
    finally:
        driver.quit()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-json", type=Path)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--max-contacts", type=int, default=1)
    parser.add_argument("--max-results", type=int, default=0)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--no-contact", action="store_true")
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument("--account-info", action="store_true")
    parser.add_argument("--wait-ready", type=int, default=0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.doctor:
            result = doctor(args)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("ok") else 2
        if args.account_info:
            result = account_info(args)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("ok") else 2
        if not args.prepare_json or not args.output_json:
            raise RuntimeError("--prepare-json and --output-json are required unless --doctor is used.")
        result = run(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "hint": "Start a logged-in Chrome with --remote-debugging-port=9222, then rerun."}, ensure_ascii=False, indent=2))
        return 2
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "output_json": str(args.output_json), **{k: result[k] for k in ("task_id", "config_hash", "opened_contacts", "visible_rows", "result_count_text")}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
