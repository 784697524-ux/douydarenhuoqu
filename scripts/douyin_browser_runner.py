#!/usr/bin/env python3
"""Collect compact Douyin Life talent-square data with Playwright.

This script intentionally prints only small JSON. It never dumps full page text.
Use a Chrome instance that exposes CDP, for example:

  open -na "Google Chrome" --args --remote-debugging-port=9222 \
    --user-data-dir="$HOME/.douyin-talent-chrome"

Log in to Douyin Life in that Chrome profile once, then reuse it for runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright
except Exception as exc:  # pragma: no cover - dependency is validated by CLI startup.
    raise SystemExit(f"Playwright is required: {exc}") from exc


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


def current_groupid(context: Any, fallback_url: str) -> str:
    for page in reversed(context.pages):
        if "life.douyin.com/p/" not in page.url:
            continue
        if "/merchant/talent/square" in page.url:
            continue
        groupid = groupid_from_url(page.url)
        if groupid:
            return groupid
    for page in reversed(context.pages):
        if "life.douyin.com/p/" not in page.url:
            continue
        groupid = groupid_from_url(page.url)
        if groupid:
            return groupid
    return groupid_from_url(fallback_url)


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


def dedupe_key(talent: dict[str, Any]) -> str:
    douyin_id = str(talent.get("douyin_id") or "").strip()
    if douyin_id:
        return f"dy:{douyin_id.lower()}"
    raw = "|".join(str(talent.get(key) or "").strip().lower() for key in ("nickname", "city", "category"))
    return "profile:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


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


def read_rows(page: Page) -> list[dict[str, Any]]:
    rows = page.locator("tr").evaluate_all(
        """trs => trs.slice(1).map((tr, i) => ({
            row: i + 1,
            cells: Array.from(tr.children).map(td => (td.innerText || '').trim())
        }))"""
    )
    talents: list[dict[str, Any]] = []
    for item in rows:
        parsed = parse_row_cells(item.get("cells", []), item.get("row", 0))
        if parsed:
            talents.append(parsed)
    return talents


def rows_signature(rows: list[dict[str, Any]]) -> str:
    return "|".join(dedupe_key(row) for row in rows)


def click_next_page(page: Page, previous_signature: str) -> bool:
    pager = page.locator(".byted-pager").first
    if not pager.count():
        return False
    clicked = pager.evaluate(
        """pager => {
            const items = Array.from(pager.querySelectorAll('.byted-pager-item'));
            const current = items.find(item => item.className.includes('byted-pager-item-checked'));
            const currentPage = current ? Number((current.innerText || '').trim()) : NaN;
            const nextPage = Number.isFinite(currentPage) ? String(currentPage + 1) : '';
            const nextNumber = items.find(item => (item.innerText || '').trim() === nextPage);
            if (nextNumber && !nextNumber.className.includes('disabled')) {
                nextNumber.click();
                return true;
            }
            const nextArrow = items.find(item =>
                item.querySelector('.byted-icon-right') &&
                !item.className.includes('disabled')
            );
            if (nextArrow) {
                nextArrow.click();
                return true;
            }
            return false;
        }"""
    )
    if not clicked:
        return False
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        page.wait_for_timeout(500)
        if rows_signature(read_rows(page)) != previous_signature:
            return True
    return False


def result_count(page: Page) -> str:
    text = page.locator("body").evaluate(
        """body => {
            const text = body.innerText || '';
            const m = text.match(/共\\s*(?:\\d+|999\\+)\\s*位达人/);
            return m ? m[0] : '';
        }"""
    )
    return str(text)


def contact_dialog_open(page: Page) -> bool:
    return bool(page.locator("body").evaluate("body => /达人联系方式\\n虚拟手机号/.test(body.innerText || '')"))


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
    elif "达人广场" in text and "常驻城市" in text:
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


def inspect_page(page: Page) -> dict[str, Any]:
    page.wait_for_load_state("domcontentloaded", timeout=30000)
    text = page.locator("body").inner_text(timeout=5000)
    if not text.strip():
        page.reload(wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        text = page.locator("body").inner_text(timeout=5000)
    state = classify_page_state(page.url, page.title(), text)
    state["body_sample"] = " ".join(clean_lines(text))[:200]
    return state


def current_account(page: Page) -> str:
    text = page.locator("body").inner_text(timeout=5000)
    lines = clean_lines(text)
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


def account_identity(page: Page) -> dict[str, str]:
    name = current_account(page)
    groupid = groupid_from_url(page.url)
    account = name
    if groupid:
        account = f"{name}|{groupid}" if name else groupid
    return {"account": account, "account_name": name, "groupid": groupid}


def click_button(page: Page, name: str, timeout_ms: int = 5000) -> None:
    page.get_by_role("button", name=name).click(timeout=timeout_ms)


def close_popovers(page: Page) -> None:
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)


def click_filter_by_label(page: Page, label: str) -> None:
    for selector in (
        ".byted-cascader-select",
        ".byted-select",
        ".byted-select-input-wrapper",
    ):
        locator = page.locator(selector).filter(has_text=label).first
        if locator.count():
            try:
                locator.click(timeout=5000)
                return
            except PlaywrightTimeoutError:
                pass
    page.locator("span,div,label").filter(has_text=label).first.click(timeout=8000)


def choose_cascader_root(page: Page, label: str, root_text: str, child_text: str | None = None) -> None:
    click_filter_by_label(page, label)
    page.wait_for_timeout(500)
    panel = page.locator(".byted-cascader-popover-panel:visible").last
    if child_text:
        panel.get_by_text(root_text, exact=True).click(timeout=8000)
        page.wait_for_timeout(300)
        panel.get_by_text(child_text, exact=True).click(timeout=8000)
    else:
        item = panel.locator(".byted-list-item-container").filter(has_text=root_text).first
        try:
            item.locator(".byted-checkbox").click(timeout=3000)
        except PlaywrightTimeoutError:
            panel.get_by_text(root_text, exact=True).click(timeout=5000)
    page.wait_for_timeout(500)
    close_popovers(page)


def choose_city(page: Page, city: str) -> None:
    wanted = city if city.endswith("市") else f"{city}市"
    click_filter_by_label(page, "常驻城市")
    page.wait_for_timeout(500)
    search = page.locator(".byted-cascader-popover-search-input input:visible")
    try:
        if search.count():
            search.last.fill(city, timeout=3000)
            page.wait_for_timeout(500)
    except PlaywrightTimeoutError:
        pass
    try:
        page.get_by_text(wanted, exact=True).last.click(timeout=5000)
    except PlaywrightTimeoutError:
        page.get_by_text(city, exact=True).last.click(timeout=5000)
    page.wait_for_timeout(600)
    close_popovers(page)


def choose_category(page: Page, category: str) -> None:
    if not category:
        return
    choose_cascader_root(page, "优势品类", category)


def choose_video_levels(page: Page, levels: list[str]) -> None:
    if not levels:
        return
    click_filter_by_label(page, "视频带货力")
    page.wait_for_timeout(500)
    popover = page.locator(".byted-popover-show").filter(has_text="LV").last
    for level in levels:
        popover.get_by_text(level.upper(), exact=True).click(timeout=8000)
        page.wait_for_timeout(200)
    close_popovers(page)


def choose_has_contact(page: Page, value: str) -> None:
    if not value or value in {"不限", "无"}:
        return
    click_filter_by_label(page, "有微信/电话")
    page.wait_for_timeout(500)
    page.locator(".byted-popover-show").get_by_text("是", exact=True).click(timeout=8000)
    page.wait_for_timeout(400)
    close_popovers(page)


def apply_filters(page: Page, config: BrowserRunConfig) -> None:
    try:
        click_button(page, "重置", timeout_ms=3000)
        page.wait_for_timeout(1200)
    except PlaywrightTimeoutError:
        pass
    choose_city(page, config.city)
    choose_category(page, config.category)
    choose_video_levels(page, config.video_levels)
    choose_has_contact(page, config.has_contact)
    click_button(page, "查询")
    page.wait_for_timeout(2500)


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
    return {
        "phone": phone.group(0) if phone else "",
        "wechat": after("微信号"),
        "quota_after": f"{quota.group(1)}/{quota.group(2)}" if quota else "",
    }


def visible_contact_text(page: Page) -> str:
    for selector in (
        ".byted-modal:visible",
        "[role=dialog]:visible",
        ".byted-drawer:visible",
        ".byted-popover-show:visible",
    ):
        locator = page.locator(selector).filter(has_text=re.compile("达人联系方式|虚拟手机号|今日剩余查看次数")).last
        if locator.count():
            try:
                return locator.inner_text(timeout=3000)
            except PlaywrightTimeoutError:
                pass
    text = page.locator("body").inner_text(timeout=3000)
    if "达人联系方式" in text or "虚拟手机号" in text or "今日剩余查看次数" in text:
        return text
    return ""


def close_contact_dialog(page: Page) -> None:
    for label in ("我知道了", "知道了", "确定"):
        button = page.get_by_text(label, exact=True)
        if button.count():
            try:
                button.last.click(timeout=3000)
                page.wait_for_timeout(500)
                return
            except PlaywrightTimeoutError:
                pass
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)


def open_contact(page: Page, row_index: int) -> dict[str, str]:
    row = page.locator("tr").nth(row_index + 1)
    button = row.get_by_role("button", name="查看联系方式").first
    if not button.count():
        button = row.get_by_text("查看联系方式", exact=True).first
    button.click(timeout=10000)
    page.wait_for_function(
        "() => /达人联系方式|虚拟手机号|今日剩余查看次数/.test(document.body.innerText || '')",
        timeout=15000,
    )
    text = visible_contact_text(page)
    if not text:
        raise RuntimeError("contact dialog opened but contact text was not readable")
    contact = parse_contact_text(text)
    if not contact.get("wechat") and not contact.get("phone"):
        raise RuntimeError("contact dialog did not contain WeChat or phone")
    close_contact_dialog(page)
    return contact


def first_page(context: Any, url: str) -> Page:
    target_groupid = current_groupid(context, url)
    target_url = url_with_groupid(url, target_groupid)
    for page in context.pages:
        if "/merchant/talent/square" in page.url:
            if target_groupid and groupid_from_url(page.url) != target_groupid:
                continue
            page.bring_to_front()
            page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            return page
    page = context.new_page()
    page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
    return page


def wait_ready(page: Page, timeout_seconds: int) -> dict[str, Any]:
    page.wait_for_load_state("domcontentloaded", timeout=30000)
    deadline = time.monotonic() + max(timeout_seconds, 0)
    last_state: dict[str, Any] = {}
    last_text = ""
    while True:
        last_text = page.locator("body").inner_text(timeout=5000)
        last_state = classify_page_state(page.url, page.title(), last_text)
        if last_state["talent_square_ready"]:
            return last_state
        if time.monotonic() >= deadline:
            break
        page.wait_for_timeout(1000)
    if last_state.get("status") == "login_required":
        raise RuntimeError(
            "Dedicated Chrome profile is not logged in to Douyin Life. "
            "Log in once in the CDP Chrome window, then rerun the task."
        )
    snippet = " ".join(clean_lines(last_text))[:200]
    raise RuntimeError(
        f"Talent square is not ready. status={last_state.get('status')!r} "
        f"title={page.title()!r} url={page.url!r} body={snippet!r}"
    )


def doctor(args: argparse.Namespace) -> dict[str, Any]:
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(args.cdp_url)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = first_page(context, args.url)
        if args.wait_ready:
            try:
                wait_ready(page, args.wait_ready)
            except RuntimeError:
                pass
        state = inspect_page(page)
        return {
            "ok": state["logged_in"] and state["talent_square_ready"],
            "cdp_url": args.cdp_url,
            "page_count": len(context.pages),
            **(account_identity(page) if state["logged_in"] else {"account": "", "account_name": "", "groupid": ""}),
            **state,
        }


def account_info(args: argparse.Namespace) -> dict[str, Any]:
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(args.cdp_url)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = first_page(context, args.url)
        wait_ready(page, args.wait_ready or 30)
        identity = account_identity(page)
        return {
            "ok": bool(identity["account"]),
            **identity,
            "url": page.url,
            "title": page.title(),
        }


def collect(
    page: Page,
    *,
    max_results: int,
    max_contacts: int,
    contact_cache: dict[str, dict[str, Any]],
    skip_keys: set[str],
    no_contact: bool,
    max_pages: int,
) -> dict[str, Any]:
    talents: list[dict[str, Any]] = []
    opened = 0
    seen_keys: set[str] = set()
    contact_errors: list[dict[str, str]] = []
    visible_rows = 0
    pages_scanned = 0
    for _page_index in range(max_pages):
        rows = read_rows(page)
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
                contact = open_contact(page, index)
            except Exception as exc:
                contact_errors.append({"dedupe_key": key, "error": str(exc)[:200]})
                close_contact_dialog(page)
                continue
            opened += 1
            talents.append({**talent, **contact, "dedupe_key": key, "contact_consumed": True})
        if len(talents) >= max_results:
            break
        if not rows or not click_next_page(page, rows_signature(rows)):
            break
    return {
        "talents": talents,
        "opened_contacts": opened,
        "visible_rows": visible_rows,
        "pages_scanned": pages_scanned,
        "contact_errors": contact_errors,
        "result_count_text": result_count(page),
        "contact_dialog_open": contact_dialog_open(page),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    prepare = json.loads(args.prepare_json.read_text(encoding="utf-8"))
    config = config_from_prepare(prepare)
    contact_cache = prepare.get("contact_cache") or {}
    skip_keys = set(prepare.get("skip_keys") or [])
    max_contacts = min(int(prepare.get("allowed_contact_views") or 0), args.max_contacts)
    max_results = args.max_results or int(prepare.get("configured_contact_views") or 0) or max_contacts
    no_contact = args.no_contact
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(args.cdp_url)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = first_page(context, args.url)
        wait_ready(page, args.wait_ready or 30)
        apply_filters(page, config)
        result = collect(
            page,
            max_results=max_results,
            max_contacts=max_contacts,
            contact_cache=contact_cache,
            skip_keys=skip_keys,
            no_contact=no_contact,
            max_pages=args.max_pages,
        )
        result.update(
            {
                "task_id": prepare.get("active_task_id"),
                "config_hash": prepare.get("config_hash"),
                "no_contact": no_contact,
                "contact_cache_count": len(contact_cache),
                "filter": {
                    "city": config.city,
                    "category": config.category,
                    "video_levels": config.video_levels,
                    "has_contact": config.has_contact,
                    "talent_type": config.talent_type,
                },
            }
        )
        return result


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
    parser.add_argument("--doctor", action="store_true", help="Only check CDP/login/talent-square readiness.")
    parser.add_argument("--account-info", action="store_true", help="Print the current Douyin Life account from Chrome.")
    parser.add_argument("--wait-ready", type=int, default=0, help="Seconds to wait for login and talent-square readiness.")
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
        error = {
            "ok": False,
            "error": str(exc),
            "hint": "Start a logged-in Chrome with --remote-debugging-port=9222, then rerun.",
        }
        print(json.dumps(error, ensure_ascii=False, indent=2))
        return 2
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "output_json": str(args.output_json), **{k: result[k] for k in ("task_id", "config_hash", "opened_contacts", "visible_rows", "result_count_text")}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
