#!/usr/bin/env python3
"""Run a configured Douyin Life talent contact task with compact browser IO."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from runtime_config import DEFAULT_CONFIG_PATH, DEFAULT_DOUYIN_URL, load_config, require_keys  # noqa: E402

SYNC = SCRIPT_DIR / "sync_talent.py"
BROWSER = SCRIPT_DIR / "douyin_browser_runner.py"
LAUNCH_CHROME = SCRIPT_DIR / "launch_debug_chrome.py"
FEISHU_ADAPTER = SCRIPT_DIR / "feishu_notable_adapter.py"


def run_json(cmd: list[str]) -> dict[str, Any]:
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        try:
            child_error = json.loads(proc.stdout)
        except json.JSONDecodeError:
            child_error = None
        if child_error:
            raise RuntimeError(json.dumps(child_error, ensure_ascii=False))
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(cmd)
            + f"\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Command returned non-JSON:\n{proc.stdout}") from exc


def run_text(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(cmd)
            + f"\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc.stdout


def cdp_version_url(cdp_url: str) -> str:
    return cdp_url.rstrip("/") + "/json/version"


def cdp_json_url(cdp_url: str, path: str) -> str:
    return cdp_url.rstrip("/") + path


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


def table_config(args: argparse.Namespace) -> dict[str, Any]:
    backend = args.settings.get("backend")
    if backend == "dingtalk":
        config = dict(args.settings["dingtalk"])
        require_keys(config, ["base_id", "config_sheet", "result_sheet"], "dingtalk")
        config["helper"] = str(Path(str(config.get("helper") or "")).expanduser())
        return config
    if backend == "feishu":
        source = args.settings["feishu"]
        require_keys(source, ["base_token", "config_table", "result_table"], "feishu")
        return {
            "helper": str(FEISHU_ADAPTER),
            "base_id": source["base_token"],
            "config_sheet": source["config_table"],
            "result_sheet": source["result_table"],
            "master_sheet": source.get("master_table", ""),
            "contact_log_sheet": source.get("contact_log_table", ""),
            "quota_sheet": source.get("quota_table", ""),
            "cursor_sheet": source.get("cursor_table", ""),
        }
    raise RuntimeError("backend must be dingtalk or feishu")


def backend_common_args(args: argparse.Namespace) -> list[str]:
    config = table_config(args)
    return ["--helper", str(config["helper"]), "--base-id", str(config["base_id"])]


def ensure_cdp_page(cdp_url: str, talent_square_url: str) -> None:
    with urllib.request.urlopen(cdp_json_url(cdp_url, "/json/list"), timeout=2) as response:
        targets = json.loads(response.read().decode("utf-8"))
    pages = [target for target in targets if target.get("type") == "page"]
    groupid = ""
    for page in reversed(pages):
        url = str(page.get("url", ""))
        if "life.douyin.com/p/" in url:
            if "/merchant/talent/square" in url:
                continue
            groupid = groupid_from_url(url)
            if groupid:
                break
    if not groupid:
        for page in reversed(pages):
            url = str(page.get("url", ""))
            if "life.douyin.com/p/" in url:
                groupid = groupid_from_url(url)
                if groupid:
                    break
    target_url = url_with_groupid(talent_square_url, groupid)
    if any(
        "/merchant/talent/square" in str(page.get("url", ""))
        and (not groupid or groupid_from_url(str(page.get("url", ""))) == groupid)
        for page in pages
    ):
        return
    encoded_url = urllib.parse.quote(target_url, safe="")
    request = urllib.request.Request(cdp_json_url(cdp_url, f"/json/new?{encoded_url}"), method="PUT")
    with urllib.request.urlopen(request, timeout=5):
        return


def assert_cdp_ready(args: argparse.Namespace) -> None:
    cdp_url = args.cdp_url
    try:
        with urllib.request.urlopen(cdp_version_url(cdp_url), timeout=2) as response:
            if response.status != 200:
                raise RuntimeError(f"CDP endpoint returned HTTP {response.status}")
        ensure_cdp_page(cdp_url, args.douyin_url)
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeError(
            json.dumps(
                {
                    "error": f"Chrome CDP is not reachable: {exc}",
                    "hint": f"Run: {sys.executable} {LAUNCH_CHROME}",
                    "cdp_url": cdp_url,
                },
                ensure_ascii=False,
            )
        ) from exc


def doctor(args: argparse.Namespace) -> dict[str, Any]:
    assert_cdp_ready(args)
    cmd = [sys.executable, str(BROWSER), "--doctor", "--cdp-url", args.cdp_url, "--url", args.douyin_url]
    if args.wait_ready:
        cmd.extend(["--wait-ready", str(args.wait_ready)])
    return run_json(cmd)


def browser_account(args: argparse.Namespace) -> str:
    if args.account != "auto":
        return args.account
    cmd = [
        sys.executable,
        str(BROWSER),
        "--account-info",
        "--cdp-url",
        args.cdp_url,
        "--url",
        args.douyin_url,
    ]
    if args.wait_ready:
        cmd.extend(["--wait-ready", str(args.wait_ready)])
    data = run_json(cmd)
    account = str(data.get("account") or "").strip()
    if not account:
        raise RuntimeError("Could not detect current Douyin Life account from Chrome.")
    return account


def prepare(args: argparse.Namespace, out_dir: Path) -> dict[str, Any]:
    config = table_config(args)
    cmd = [
        sys.executable,
        str(SYNC),
        "prepare",
        *backend_common_args(args),
        "--task-id",
        args.task_id,
        "--config-sheet",
        str(config["config_sheet"]),
        "--result-sheet",
        str(config["result_sheet"]),
        "--existing-scan-limit",
        str(args.existing_scan_limit),
        "--daily-quota",
        str(args.daily_quota),
        "--reserve-quota",
        str(args.reserve_quota),
        "--max-contact-views",
        str(args.max_contact_views),
        "--account",
        args.account,
    ]
    for key, flag in (("master_sheet", "--master-sheet"), ("contact_log_sheet", "--contact-log-sheet"), ("quota_sheet", "--quota-sheet")):
        if config.get(key):
            cmd.extend([flag, str(config[key])])
    data = run_json(cmd)
    (out_dir / "prepare.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def run_browser(args: argparse.Namespace, out_dir: Path, prepare_data: dict[str, Any]) -> dict[str, Any]:
    prepare_path = out_dir / "prepare.json"
    browser_path = out_dir / "browser.json"
    cmd = [
        sys.executable,
        str(BROWSER),
        "--prepare-json",
        str(prepare_path),
        "--output-json",
        str(browser_path),
        "--cdp-url",
        args.cdp_url,
        "--url",
        args.douyin_url,
        "--max-contacts",
        str(prepare_data.get("allowed_contact_views") or 0),
        "--max-results",
        str(prepare_data.get("configured_contact_views") or prepare_data.get("allowed_contact_views") or 0),
        "--max-pages",
        str(args.max_pages),
    ]
    if args.wait_ready:
        cmd.extend(["--wait-ready", str(args.wait_ready)])
    if args.no_contact:
        cmd.append("--no-contact")
    run_json(cmd)
    data = json.loads(browser_path.read_text(encoding="utf-8"))
    data["output_json"] = str(browser_path)
    return data


def commit(args: argparse.Namespace, out_dir: Path, prepare_data: dict[str, Any], browser_data: dict[str, Any]) -> dict[str, Any]:
    if args.no_commit or args.no_contact:
        return {"skipped": True, "reason": "no_commit_or_no_contact"}
    config = table_config(args)
    input_path = out_dir / "browser.json"
    cmd = [
        sys.executable,
        str(SYNC),
        "commit",
        *backend_common_args(args),
        "--task-id",
        args.task_id,
        "--config-sheet",
        str(config["config_sheet"]),
        "--result-sheet",
        str(config["result_sheet"]),
        "--input-json",
        str(input_path),
        "--existing-scan-limit",
        str(args.existing_scan_limit),
        "--daily-quota",
        str(args.daily_quota),
        "--reserve-quota",
        str(args.reserve_quota),
        "--max-contact-views",
        str(args.max_contact_views),
        "--account",
        args.account,
        "--config-hash",
        str(prepare_data["config_hash"]),
    ]
    for key, flag in (("master_sheet", "--master-sheet"), ("contact_log_sheet", "--contact-log-sheet"), ("quota_sheet", "--quota-sheet")):
        if config.get(key):
            cmd.extend([flag, str(config[key])])
    data = run_json(cmd)
    (out_dir / "commit.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def write_cursor(args: argparse.Namespace, prepare_data: dict[str, Any], browser_data: dict[str, Any], status: str) -> str:
    config = table_config(args)
    if not config.get("cursor_sheet"):
        return ""
    fields = prepare_data.get("config", {})
    cursor = [
        {
            "fields": {
                "config_hash": prepare_data.get("config_hash"),
                "任务ID": args.task_id,
                "账号": args.account,
                "筛选摘要": (
                    f"城市={fields.get('常驻城市')}; 品类={fields.get('优势品类')}; "
                    f"视频带货力={fields.get('视频带货力')}; 有微信/电话={fields.get('有微信/电话')}; "
                    f"结果={browser_data.get('result_count_text')}"
                ),
                "最近扫描页码": browser_data.get("pages_scanned") or 1,
                "最近成功页码": browser_data.get("pages_scanned") or 1,
                "已采集数量": len(browser_data.get("talents") or []),
                "连续重复页数": 0,
                "状态": status,
                "最近运行时间": dt.datetime.now().replace(microsecond=0).isoformat(),
                "备注": f"browser_json={browser_data.get('output_json', '')}",
            }
        }
    ]
    response = run_json(
        [
            sys.executable,
            str(config["helper"]),
            "notable",
            "records-add",
            "--base-id",
            str(config["base_id"]),
            "--sheet-id",
            str(config["cursor_sheet"]),
            "--records-json",
            json.dumps(cursor, ensure_ascii=False),
        ]
    )
    return response.get("value", [{}])[0].get("id", "")


def update_config_result(args: argparse.Namespace, prepare_data: dict[str, Any], browser_data: dict[str, Any], commit_data: dict[str, Any], cursor_id: str) -> None:
    config = table_config(args)
    record_id = prepare_data["active_config_record_id"]
    commit_text = (
        "未写入结果表（no_contact/no_commit）"
        if commit_data.get("skipped")
        else f"写入结果表{commit_data.get('add_count', 0)}条，消耗联系方式{commit_data.get('planned_contact_view_consumption', 0)}次"
    )
    text = (
        f"{dt.datetime.now().replace(microsecond=0).isoformat()} 任务{args.task_id}脚本执行完成。"
        f"页面结果={browser_data.get('result_count_text')}，可见行={browser_data.get('visible_rows')}，"
        f"扫描页数={browser_data.get('pages_scanned', 1)}，"
        f"采集候选={len(browser_data.get('talents') or [])}，打开联系方式={browser_data.get('opened_contacts')}。"
        f"联系方式错误={len(browser_data.get('contact_errors') or [])}。"
        f"{commit_text}。游标记录={cursor_id}。"
    )
    payload = [{"id": record_id, "fields": {"执行结果": text}}]
    run_text(
        [
            sys.executable,
            str(config["helper"]),
            "notable",
            "records-update",
            "--base-id",
            str(config["base_id"]),
            "--sheet-id",
            str(config["config_sheet"]),
            "--records-json",
            json.dumps(payload, ensure_ascii=False),
        ]
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = args.out_dir or Path("/private/tmp") / f"douyin_task_{args.task_id}_{dt.datetime.now().strftime('%Y%m%d%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    assert_cdp_ready(args)
    args.account = browser_account(args)
    prepare_data = prepare(args, out_dir)
    browser_data = run_browser(args, out_dir, prepare_data)
    commit_data = commit(args, out_dir, prepare_data, browser_data)
    status = "无联系方式测试通过" if args.no_contact else "脚本执行完成"
    if args.no_status_write:
        cursor_id = ""
        status_write = {"skipped": True, "reason": "no_status_write"}
    else:
        cursor_id = write_cursor(args, prepare_data, browser_data, status)
        update_config_result(args, prepare_data, browser_data, commit_data, cursor_id)
        status_write = {"skipped": False, "cursor_id": cursor_id}
    return {
        "ok": True,
        "backend": args.settings.get("backend"),
        "task_id": args.task_id,
        "out_dir": str(out_dir),
        "config_hash": prepare_data.get("config_hash"),
        "account": args.account,
        "allowed_contact_views": prepare_data.get("allowed_contact_views"),
        "result_count_text": browser_data.get("result_count_text"),
        "visible_rows": browser_data.get("visible_rows"),
        "pages_scanned": browser_data.get("pages_scanned"),
        "talent_count": len(browser_data.get("talents") or []),
        "opened_contacts": browser_data.get("opened_contacts"),
        "contact_error_count": len(browser_data.get("contact_errors") or []),
        "commit": commit_data,
        "cursor_id": cursor_id,
        "status_write": status_write,
    }


def normalize_args(args: argparse.Namespace) -> argparse.Namespace:
    settings = load_config(args.config)
    args.settings = settings
    args.cdp_url = args.cdp_url or str(settings.get("chrome_cdp_url") or "http://127.0.0.1:9222")
    args.douyin_url = args.douyin_url or str(settings.get("douyin_url") or DEFAULT_DOUYIN_URL)
    quota = settings.get("quota") or {}
    args.daily_quota = args.daily_quota if args.daily_quota is not None else int(quota.get("daily_quota") or 30)
    args.reserve_quota = args.reserve_quota if args.reserve_quota is not None else int(quota.get("reserve_quota") or 0)
    args.max_contact_views = args.max_contact_views if args.max_contact_views is not None else int(quota.get("max_contact_views") or 1)
    args.account = args.account or str(settings.get("account") or "auto")
    if args.smoke:
        args.no_contact = True
        args.no_commit = True
        args.no_status_write = True
    return args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--cdp-url")
    parser.add_argument("--douyin-url")
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--account", help="Use 'auto' to read the current Douyin Life account from Chrome.")
    parser.add_argument("--daily-quota", type=int)
    parser.add_argument("--reserve-quota", type=int)
    parser.add_argument("--max-contact-views", type=int)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--existing-scan-limit", type=int, default=500)
    parser.add_argument("--no-contact", action="store_true", help="Apply filters and read rows, but do not open contact popups.")
    parser.add_argument("--no-commit", action="store_true", help="Do not write talent results even if contacts were collected.")
    parser.add_argument("--no-status-write", action="store_true", help="Do not write cursor or config execution status.")
    parser.add_argument("--smoke", action="store_true", help="Shortcut for --no-contact --no-commit --no-status-write.")
    parser.add_argument("--doctor", action="store_true", help="Only check Chrome CDP/login/talent-square readiness.")
    parser.add_argument("--wait-ready", type=int, default=0, help="Seconds to wait for login and talent-square readiness.")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = normalize_args(build_parser().parse_args(argv))
        if args.doctor:
            result = doctor(args)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result.get("ok") else 2
        if not args.task_id:
            raise RuntimeError("--task-id is required unless --doctor is used.")
        result = run(args)
    except Exception as exc:
        try:
            parsed = json.loads(str(exc))
        except json.JSONDecodeError:
            parsed = {"error": str(exc)}
        print(json.dumps({"ok": False, **parsed}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
