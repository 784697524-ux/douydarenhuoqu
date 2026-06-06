#!/usr/bin/env python3
"""Sync Douyin Life talent contact data into a DingTalk AI Table."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


DEFAULT_BASE_ID = ""
DEFAULT_CONFIG_SHEET = ""
DEFAULT_RESULT_SHEET = ""
DEFAULT_HELPER = (
    Path.home()
    / ".codex"
    / "skills"
    / "dingtalk-knowledge-manager"
    / "scripts"
    / "dingtalk_tool.py"
)

DEFAULT_DAILY_QUOTA = 30
DEFAULT_RESERVE_QUOTA = 0
DEFAULT_MAX_CONTACT_VIEWS = 1

CONFIG_FIELDS = [
    "任务ID",
    "任务编号",
    "启用",
    "常驻城市",
    "优势品类",
    "直播类型",
    "达人粉丝数",
    "视频带货力",
    "直播带货力",
    "达人内容力",
    "短视频报价最低",
    "短视频报价最高",
    "直播报价最低",
    "直播报价最高",
    "是否合作过",
    "同行合作过",
    "签约机构",
    "有微信/电话",
    "达人类型",
    "每页数量",
    "查询次数",
]

RESULT_FIELD_MAP = {
    "nickname": "达人昵称",
    "execute_date": "最近执行时间",
    "douyin_id": "抖音号",
    "uid": "达人UID",
    "city": "达人城市",
    "category": "达人品类",
    "followers": "粉丝数",
    "video_power": "视频带货力结果",
    "live_power": "直播带货力结果",
    "content_power": "内容力结果",
    "credit_score": "信用分",
    "verification_rate_30d": "30日核销率",
    "avg_sales_per_video": "稿均销售额",
    "avg_seed_sales": "平均种草销售额",
    "avg_views_per_video": "稿均播放量",
    "avg_gmv_per_k_impression": "稿均千次曝光GMV",
    "avg_completion_rate": "稿均完播率",
    "poi_click_rate": "POI锚点点击率",
    "avg_live_sales": "场均销售额",
    "avg_live_watchers": "场均观看人数",
    "avg_live_watch_time": "场均观看时长",
    "avg_live_comments": "场均评论数",
    "wechat": "微信号",
    "contact_source": "联系方式来源",
    "contact_consumed": "是否消耗额度",
}

NUMERIC_FIELDS = {"信用分", "场均评论数"}

MASTER_FIELD_MAP = {
    "dedupe_key": "dedupe_key",
    "nickname": "达人昵称",
    "douyin_id": "抖音号",
    "uid": "达人UID",
    "city": "达人城市",
    "category": "达人品类",
    "wechat": "微信号",
    "phone": "虚拟手机号",
    "first_seen_at": "首次获取时间",
    "last_seen_at": "最近更新时间",
    "source_config_hash": "来源配置hash",
}

CONTACT_LOG_FIELD_MAP = {
    "date": "日期",
    "account": "账号",
    "run_id": "run_id",
    "config_hash": "config_hash",
    "dedupe_key": "dedupe_key",
    "nickname": "达人昵称",
    "douyin_id": "抖音号",
    "action": "动作",
    "status": "状态",
    "consumed_quota": "消耗额度",
    "quota_before": "查看前剩余额度",
    "quota_after": "查看后剩余额度",
    "reason": "原因",
    "wechat": "微信号",
    "recorded_at": "记录时间",
}

QUOTA_FIELD_MAP = {
    "date": "日期",
    "account": "账号",
    "run_id": "run_id",
    "daily_quota": "每日额度",
    "reserve_quota": "保留额度",
    "consumed_count": "已消耗次数",
    "remaining_count": "剩余次数",
    "can_continue": "可继续查看",
    "updated_at": "最近更新时间",
}

OPTIONAL_TABLE_SCHEMAS = {
    "达人主档表": [
        {"name": "dedupe_key", "type": "text"},
        {"name": "达人昵称", "type": "text"},
        {"name": "抖音号", "type": "text"},
        {"name": "达人UID", "type": "text"},
        {"name": "达人城市", "type": "text"},
        {"name": "达人品类", "type": "text"},
        {"name": "微信号", "type": "text"},
        {"name": "虚拟手机号", "type": "text"},
        {"name": "首次获取时间", "type": "text"},
        {"name": "最近更新时间", "type": "text"},
        {"name": "来源配置hash", "type": "text"},
    ],
    "联系方式查看日志": [
        {"name": "日期", "type": "text"},
        {"name": "账号", "type": "text"},
        {"name": "run_id", "type": "text"},
        {"name": "config_hash", "type": "text"},
        {"name": "dedupe_key", "type": "text"},
        {"name": "达人昵称", "type": "text"},
        {"name": "抖音号", "type": "text"},
        {"name": "动作", "type": "text"},
        {"name": "状态", "type": "text"},
        {"name": "消耗额度", "type": "text"},
        {"name": "查看前剩余额度", "type": "number", "property": {"formatter": "INT"}},
        {"name": "查看后剩余额度", "type": "number", "property": {"formatter": "INT"}},
        {"name": "原因", "type": "text"},
        {"name": "微信号", "type": "text"},
        {"name": "记录时间", "type": "text"},
    ],
    "每日30次额度审计": [
        {"name": "日期", "type": "text"},
        {"name": "账号", "type": "text"},
        {"name": "run_id", "type": "text"},
        {"name": "每日额度", "type": "number", "property": {"formatter": "INT"}},
        {"name": "保留额度", "type": "number", "property": {"formatter": "INT"}},
        {"name": "已消耗次数", "type": "number", "property": {"formatter": "INT"}},
        {"name": "剩余次数", "type": "number", "property": {"formatter": "INT"}},
        {"name": "可继续查看", "type": "text"},
        {"name": "最近更新时间", "type": "text"},
    ],
    "任务执行游标表": [
        {"name": "config_hash", "type": "text"},
        {"name": "任务ID", "type": "text"},
        {"name": "账号", "type": "text"},
        {"name": "筛选摘要", "type": "text"},
        {"name": "最近扫描页码", "type": "number", "property": {"formatter": "INT"}},
        {"name": "最近成功页码", "type": "number", "property": {"formatter": "INT"}},
        {"name": "已采集数量", "type": "number", "property": {"formatter": "INT"}},
        {"name": "连续重复页数", "type": "number", "property": {"formatter": "INT"}},
        {"name": "状态", "type": "text"},
        {"name": "最近运行时间", "type": "text"},
        {"name": "备注", "type": "text"},
    ],
}


class SyncError(RuntimeError):
    pass


def is_retryable_helper_failure(text: str) -> bool:
    markers = (
        "HTTP 429",
        "HTTP 500",
        "HTTP 502",
        "HTTP 503",
        "HTTP 504",
        "ServiceUnavailable",
        "temporary failure",
        "Too Many Requests",
        "socket.timeout",
        "timed out",
        "read operation timed out",
        "The read operation timed out",
    )
    return any(marker in text for marker in markers)


def run_helper(helper: Path, args: list[str]) -> dict[str, Any]:
    cmd = [sys.executable, str(helper), *args]
    last_error = ""
    for attempt in range(1, 4):
        proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
        if proc.returncode == 0:
            try:
                return json.loads(proc.stdout)
            except json.JSONDecodeError as exc:
                raise SyncError(f"Helper returned non-JSON output: {proc.stdout}") from exc
        last_error = (
            f"DingTalk helper failed: {' '.join(cmd)}\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
        if attempt == 3 or not is_retryable_helper_failure(last_error):
            break
        time.sleep(attempt * 2)
    raise SyncError(last_error)


def now_iso() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def select_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or value.get("text") or value.get("id") or "")
    if value is None:
        return ""
    return str(value)


def parse_positive_int(value: Any) -> int | None:
    text = select_name(value).strip()
    if not text:
        return None
    try:
        parsed = int(float(text))
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def normalize_config(fields: dict[str, Any]) -> dict[str, str]:
    return {name: select_name(fields.get(name)).strip() for name in CONFIG_FIELDS}


def config_task_id(fields: dict[str, Any]) -> str:
    return select_name(fields.get("任务ID") or fields.get("任务编号")).strip()


def is_enabled(record: dict[str, Any]) -> bool:
    return select_name(record.get("fields", {}).get("启用")) == "是"


def load_active_config(
    helper: Path, base_id: str, sheet_id: str, task_id: str | None = None
) -> dict[str, Any]:
    response = run_helper(
        helper,
        [
            "notable",
            "records-list",
            "--base-id",
            base_id,
            "--sheet-id",
            sheet_id,
            "--max-results",
            "50",
        ],
    )
    records = response.get("records", [])
    enabled_records = [record for record in records if is_enabled(record)]
    if task_id:
        active = next(
            (
                record
                for record in enabled_records
                if config_task_id(record.get("fields", {})) == task_id
            ),
            None,
        )
        if not active:
            raise SyncError(
                f"No active config row found where 启用=是 and 任务ID/任务编号={task_id}"
            )
    else:
        active = next(iter(enabled_records), None)
    if not active:
        raise SyncError("No active config row found where 启用=是")
    fields = normalize_config(active.get("fields", {}))
    return {"record_id": active.get("id"), "fields": fields}


def stable_hash(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def make_run_id(config_hash: str, when: str | None = None) -> str:
    seed = f"{when or now_iso()}:{config_hash}"
    return "run_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def dedupe_key_from_fields(fields: dict[str, Any]) -> str:
    uid = str(fields.get("达人UID") or "").strip()
    if uid:
        return f"uid:{uid}"
    douyin_id = str(fields.get("抖音号") or "").strip()
    if douyin_id:
        return f"dy:{douyin_id.lower()}"
    raw = "|".join(
        str(fields.get(name) or "").strip().lower()
        for name in ("达人昵称", "达人城市", "达人品类")
    )
    return "profile:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def dedupe_key_from_talent(talent: dict[str, Any]) -> str:
    uid = str(talent.get("uid") or talent.get("达人UID") or "").strip()
    if uid:
        return f"uid:{uid}"
    douyin_id = str(talent.get("douyin_id") or talent.get("抖音号") or "").strip()
    if douyin_id:
        return f"dy:{douyin_id.lower()}"
    raw = "|".join(
        str(
            talent.get(key)
            or talent.get(local_key)
            or ""
        ).strip().lower()
        for key, local_key in (
            ("nickname", "达人昵称"),
            ("city", "达人城市"),
            ("category", "达人品类"),
        )
    )
    return "profile:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def load_existing_results(
    helper: Path, base_id: str, sheet_id: str, max_results: int
) -> dict[str, dict[str, Any]]:
    existing: dict[str, dict[str, Any]] = {}
    for record in load_records(helper, base_id, sheet_id, max_results):
        fields = record.get("fields", {})
        key = dedupe_key_from_fields(fields)
        existing[key] = {"record_id": record.get("id"), "fields": fields}
    return existing


def load_records(
    helper: Path, base_id: str, sheet_id: str, scan_limit: int
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    next_token = ""
    while len(records) < scan_limit:
        page_size = min(100, scan_limit - len(records))
        cmd = [
            "notable",
            "records-list",
            "--base-id",
            base_id,
            "--sheet-id",
            sheet_id,
            "--max-results",
            str(page_size),
        ]
        if next_token:
            cmd.extend(["--next-token", next_token])
        response = run_helper(helper, cmd)
        records.extend(response.get("records", []))
        next_token = response.get("nextToken") or ""
        if not response.get("hasMore") or not next_token:
            break
    return records


def get_sheet_fields(helper: Path, base_id: str, sheet_id: str) -> set[str]:
    response = run_helper(
        helper,
        [
            "notable",
            "fields",
            "--base-id",
            base_id,
            "--sheet-id",
            sheet_id,
        ],
    )
    return {field.get("name") for field in response.get("value", []) if field.get("name")}


def list_sheets(helper: Path, base_id: str) -> dict[str, str]:
    response = run_helper(helper, ["notable", "sheets", "--base-id", base_id])
    return {
        str(sheet.get("name")): str(sheet.get("id"))
        for sheet in response.get("value", [])
        if sheet.get("name") and sheet.get("id")
    }


def create_sheet(
    helper: Path,
    *,
    base_id: str,
    name: str,
    fields: list[dict[str, Any]],
    dry_run: bool,
) -> dict[str, Any]:
    cmd = [
        "notable",
        "sheet-create",
        "--base-id",
        base_id,
        "--name",
        name,
        "--fields-json",
        json.dumps(fields, ensure_ascii=False),
    ]
    if dry_run:
        cmd.append("--dry-run")
    return run_helper(helper, cmd)


def create_field(
    helper: Path,
    *,
    base_id: str,
    sheet_id: str,
    field: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    cmd = [
        "notable",
        "field-create",
        "--base-id",
        base_id,
        "--sheet-id",
        sheet_id,
        "--name",
        str(field["name"]),
        "--type",
        str(field["type"]),
    ]
    if "property" in field:
        cmd.extend(["--property-json", json.dumps(field["property"], ensure_ascii=False)])
    if dry_run:
        cmd.append("--dry-run")
    return run_helper(helper, cmd)


def get_result_fields(helper: Path, base_id: str, sheet_id: str) -> set[str]:
    return get_sheet_fields(helper, base_id, sheet_id)


def coerce_number(value: Any) -> int | float | None:
    if value in ("", None):
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return None


def talent_to_result_fields(
    talent: dict[str, Any],
    result_field_names: set[str],
    execute_date: str,
) -> dict[str, Any]:
    merged = dict(talent)
    merged.setdefault("execute_date", execute_date)
    fields: dict[str, Any] = {}
    for source_key, target_name in RESULT_FIELD_MAP.items():
        if target_name not in result_field_names:
            continue
        value = merged.get(source_key)
        if value is None:
            value = merged.get(target_name)
        if value in ("", None):
            continue
        if source_key == "contact_consumed":
            value = "是" if truthy(value) else "否"
        if target_name in NUMERIC_FIELDS:
            numeric = coerce_number(value)
            if numeric is None:
                continue
            value = numeric
        fields[target_name] = value
    return fields


def map_fields(
    values: dict[str, Any], field_map: dict[str, str], available_fields: set[str]
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for source_key, target_name in field_map.items():
        if target_name not in available_fields:
            continue
        value = values.get(source_key)
        if value in ("", None):
            continue
        fields[target_name] = value
    return fields


def get_field_any(fields: dict[str, Any], names: tuple[str, ...]) -> str:
    for name in names:
        value = select_name(fields.get(name)).strip()
        if value:
            return value
    return ""


def contact_cache_entry(fields: dict[str, Any], source: str) -> dict[str, str]:
    wechat = get_field_any(fields, ("微信号", "wechat"))
    if not wechat:
        return {}
    entry = {
        "wechat": wechat,
        "contact_source": source,
    }
    phone = get_field_any(fields, ("虚拟手机号", "phone"))
    if phone:
        entry["phone"] = phone
    return entry


def build_contact_cache(
    existing: dict[str, dict[str, Any]],
    master: dict[str, dict[str, Any]],
    contact_logs: list[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    cache: dict[str, dict[str, str]] = {}
    for key, record in existing.items():
        entry = contact_cache_entry(record.get("fields", {}), "result_cache")
        if entry:
            cache[key] = entry
    for record in contact_logs:
        fields = record.get("fields", {})
        key = get_field_any(fields, ("dedupe_key", "去重键")) or dedupe_key_from_fields(fields)
        entry = contact_cache_entry(fields, "contact_log_cache")
        if entry:
            cache[key] = entry
    for key, record in master.items():
        entry = contact_cache_entry(record.get("fields", {}), "master_cache")
        if entry:
            cache[key] = entry
    return cache


def load_master_contacts(
    helper: Path, base_id: str, sheet_id: str | None, scan_limit: int
) -> dict[str, dict[str, Any]]:
    if not sheet_id:
        return {}
    contacts: dict[str, dict[str, Any]] = {}
    for record in load_records(helper, base_id, sheet_id, scan_limit):
        fields = record.get("fields", {})
        key = get_field_any(fields, ("dedupe_key", "去重键")) or dedupe_key_from_fields(fields)
        contacts[key] = {"record_id": record.get("id"), "fields": fields}
    return contacts


def truthy(value: Any) -> bool:
    text = select_name(value).strip().lower()
    return text in {"1", "true", "yes", "y", "是", "已消耗", "__yes__"}


def load_contact_logs(
    helper: Path, base_id: str, sheet_id: str | None, scan_limit: int
) -> list[dict[str, Any]]:
    if not sheet_id:
        return []
    return load_records(helper, base_id, sheet_id, scan_limit)


def quota_summary(
    contact_logs: list[dict[str, Any]],
    *,
    date: str,
    account: str,
    daily_quota: int,
    reserve_quota: int,
) -> dict[str, Any]:
    consumed = 0
    viewed_keys = set()
    for record in contact_logs:
        fields = record.get("fields", {})
        if select_name(fields.get("日期")) != date:
            continue
        if select_name(fields.get("账号")) != account:
            continue
        key = get_field_any(fields, ("dedupe_key", "去重键"))
        if key:
            viewed_keys.add(key)
        if truthy(fields.get("消耗额度")):
            consumed += 1
    remaining = max(0, daily_quota - consumed)
    usable = max(0, remaining - reserve_quota)
    return {
        "date": date,
        "account": account,
        "daily_quota": daily_quota,
        "reserve_quota": reserve_quota,
        "consumed_count": consumed,
        "remaining_count": remaining,
        "usable_count": usable,
        "viewed_keys": sorted(viewed_keys),
        "can_continue": "是" if usable > 0 else "否",
    }


def configured_max_contact_views(config_fields: dict[str, Any], fallback: int) -> int:
    # Keep the CLI fallback so older config tables without 查询次数 still run safely.
    return parse_positive_int(config_fields.get("查询次数")) or fallback


def cached_wechat(master_record: dict[str, Any] | None) -> str:
    if not master_record:
        return ""
    return get_field_any(master_record.get("fields", {}), ("微信号", "wechat"))


def write_records(
    helper: Path,
    *,
    base_id: str,
    sheet_id: str,
    records: list[dict[str, Any]],
    dry_run: bool,
    mode: str = "add",
) -> dict[str, Any]:
    if not records:
        return {"value": []}
    command = "records-update" if mode == "update" else "records-add"
    cmd = [
        "notable",
        command,
        "--base-id",
        base_id,
        "--sheet-id",
        sheet_id,
        "--records-json",
        json.dumps(records, ensure_ascii=False),
    ]
    if dry_run:
        cmd.append("--dry-run")
    return run_helper(helper, cmd)


def talent_contact_consumed(talent: dict[str, Any], has_cached_contact: bool) -> bool:
    if "contact_consumed" in talent:
        return truthy(talent.get("contact_consumed"))
    if has_cached_contact:
        return False
    # If a new WeChat value appears without cache, assume a popup view was consumed.
    return bool(select_name(talent.get("wechat") or talent.get("微信号")).strip())


def make_master_record(
    talent: dict[str, Any],
    dedupe_key: str,
    config_hash: str,
    existing_record: dict[str, Any] | None,
    available_fields: set[str],
) -> dict[str, Any]:
    timestamp = now_iso()
    values = {
        **talent,
        "dedupe_key": dedupe_key,
        "first_seen_at": timestamp,
        "last_seen_at": timestamp,
        "source_config_hash": config_hash,
    }
    if existing_record:
        values["first_seen_at"] = get_field_any(
            existing_record.get("fields", {}), ("首次获取时间", "first_seen_at")
        ) or timestamp
    fields = map_fields(values, MASTER_FIELD_MAP, available_fields)
    record = {"fields": fields}
    if existing_record:
        record["id"] = existing_record["record_id"]
    return record


def make_contact_log_record(
    talent: dict[str, Any],
    dedupe_key: str,
    *,
    date: str,
    account: str,
    run_id: str,
    config_hash: str,
    consumed: bool,
    quota_before: int,
    quota_after: int,
    reason: str,
    available_fields: set[str],
) -> dict[str, Any]:
    values = {
        **talent,
        "date": date,
        "account": account,
        "run_id": run_id,
        "config_hash": config_hash,
        "dedupe_key": dedupe_key,
        "action": "查看联系方式" if consumed else "复用联系方式",
        "status": "success",
        "consumed_quota": "是" if consumed else "否",
        "quota_before": quota_before,
        "quota_after": quota_after,
        "reason": reason,
        "recorded_at": now_iso(),
    }
    return {"fields": map_fields(values, CONTACT_LOG_FIELD_MAP, available_fields)}


def make_quota_record(
    *,
    date: str,
    account: str,
    run_id: str,
    daily_quota: int,
    reserve_quota: int,
    consumed_count: int,
    available_fields: set[str],
) -> dict[str, Any]:
    remaining = max(0, daily_quota - consumed_count)
    values = {
        "date": date,
        "account": account,
        "run_id": run_id,
        "daily_quota": daily_quota,
        "reserve_quota": reserve_quota,
        "consumed_count": consumed_count,
        "remaining_count": remaining,
        "can_continue": "是" if remaining > reserve_quota else "否",
        "updated_at": now_iso(),
    }
    return {"fields": map_fields(values, QUOTA_FIELD_MAP, available_fields)}


def load_talents(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("talents") or data.get("records") or [data]
    if not isinstance(data, list):
        raise SyncError("Input JSON must be a talent object, a talent list, or {'talents': [...]}")
    return [item for item in data if isinstance(item, dict)]


def command_prepare(args: argparse.Namespace) -> int:
    config = load_active_config(args.helper, args.base_id, args.config_sheet, args.task_id)
    result_fields = get_result_fields(args.helper, args.base_id, args.result_sheet)
    existing = load_existing_results(
        args.helper, args.base_id, args.result_sheet, args.existing_scan_limit
    )
    master = load_master_contacts(
        args.helper, args.base_id, args.master_sheet, args.existing_scan_limit
    )
    contact_logs = load_contact_logs(
        args.helper, args.base_id, args.contact_log_sheet, args.existing_scan_limit
    )
    master_field_names = (
        get_sheet_fields(args.helper, args.base_id, args.master_sheet)
        if args.master_sheet
        else set()
    )
    contact_log_field_names = (
        get_sheet_fields(args.helper, args.base_id, args.contact_log_sheet)
        if args.contact_log_sheet
        else set()
    )
    quota_field_names = (
        get_sheet_fields(args.helper, args.base_id, args.quota_sheet)
        if args.quota_sheet
        else set()
    )
    config_hash = stable_hash(config["fields"])
    quota = quota_summary(
        contact_logs,
        date=args.date,
        account=args.account,
        daily_quota=args.daily_quota,
        reserve_quota=args.reserve_quota,
    )
    result_wechat_keys = {
        key
        for key, record in existing.items()
        if select_name(record.get("fields", {}).get("微信号")).strip()
    }
    master_wechat_keys = {
        key for key, record in master.items() if cached_wechat(record)
    }
    skip_contact_keys = result_wechat_keys | master_wechat_keys | set(quota["viewed_keys"])
    contact_cache = build_contact_cache({}, master, contact_logs)
    for key in result_wechat_keys:
        contact_cache.pop(key, None)
    max_contact_views = configured_max_contact_views(config["fields"], args.max_contact_views)
    allowed_contact_views = min(max_contact_views, quota["usable_count"])
    output = {
        "base_id": args.base_id,
        "config_sheet": args.config_sheet,
        "result_sheet": args.result_sheet,
        "master_sheet": args.master_sheet,
        "contact_log_sheet": args.contact_log_sheet,
        "quota_sheet": args.quota_sheet,
        "active_config_record_id": config["record_id"],
        "active_task_id": config_task_id(config["fields"]),
        "config": config["fields"],
        "config_hash": config_hash,
        "configured_contact_views": max_contact_views,
        "result_field_count": len(result_fields),
        "existing_result_count": len(existing),
        "master_contact_count": len(master),
        "quota": quota,
        "allowed_contact_views": allowed_contact_views,
        "skip_keys": sorted(skip_contact_keys),
        "contact_cache": contact_cache,
        "contact_cache_count": len(contact_cache),
        "missing_optional_sheets": [
            name
            for name, value in {
                "master_sheet": args.master_sheet,
                "contact_log_sheet": args.contact_log_sheet,
                "quota_sheet": args.quota_sheet,
            }.items()
            if not value
        ],
        "next_action": "Use Chrome to apply config and only open contacts for candidates not in skip_keys while allowed_contact_views > 0.",
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def command_commit(args: argparse.Namespace) -> int:
    talents = load_talents(args.input_json)
    result_fields = get_result_fields(args.helper, args.base_id, args.result_sheet)
    existing = load_existing_results(
        args.helper, args.base_id, args.result_sheet, args.existing_scan_limit
    )
    master = load_master_contacts(
        args.helper, args.base_id, args.master_sheet, args.existing_scan_limit
    )
    contact_logs = load_contact_logs(
        args.helper, args.base_id, args.contact_log_sheet, args.existing_scan_limit
    )
    master_field_names = (
        get_sheet_fields(args.helper, args.base_id, args.master_sheet)
        if args.master_sheet
        else set()
    )
    contact_log_field_names = (
        get_sheet_fields(args.helper, args.base_id, args.contact_log_sheet)
        if args.contact_log_sheet
        else set()
    )
    quota_field_names = (
        get_sheet_fields(args.helper, args.base_id, args.quota_sheet)
        if args.quota_sheet
        else set()
    )
    execute_date = args.execute_date or dt.date.today().isoformat()
    run_config = load_active_config(args.helper, args.base_id, args.config_sheet, args.task_id)
    config_hash = args.config_hash or stable_hash(run_config["fields"])
    run_id = args.run_id or make_run_id(config_hash)
    quota = quota_summary(
        contact_logs,
        date=args.date,
        account=args.account,
        daily_quota=args.daily_quota,
        reserve_quota=args.reserve_quota,
    )
    max_contact_views = configured_max_contact_views(run_config["fields"], args.max_contact_views)
    allowed_contact_views = min(max_contact_views, quota["usable_count"])
    consumed_planned = 0
    records_to_add = []
    master_adds = []
    master_updates = []
    contact_log_adds = []
    skipped = []

    for talent in talents:
        key = dedupe_key_from_talent(talent)
        old = existing.get(key)
        cached = master.get(key)
        cached_contact = cached_wechat(cached)
        old_wechat = select_name((old or {}).get("fields", {}).get("微信号")).strip()
        new_wechat = select_name(talent.get("wechat") or talent.get("微信号")).strip()
        if old and (old_wechat or not args.allow_duplicate_without_contact):
            skipped.append({"dedupe_key": key, "reason": "already_exists", "record_id": old["record_id"]})
            continue
        if not new_wechat and cached_contact:
            talent["wechat"] = cached_contact
            new_wechat = cached_contact
            talent.setdefault("contact_source", "master_cache")
        if not new_wechat and args.require_wechat:
            skipped.append({"dedupe_key": key, "reason": "missing_wechat"})
            continue
        consumed = talent_contact_consumed(talent, bool(cached_contact))
        if consumed and consumed_planned >= allowed_contact_views:
            skipped.append({"dedupe_key": key, "reason": "quota_limit"})
            continue
        if consumed:
            consumed_planned += 1
        fields = talent_to_result_fields(talent, result_fields, execute_date)
        if not fields.get("达人昵称"):
            skipped.append({"dedupe_key": key, "reason": "missing_nickname"})
            continue
        records_to_add.append({"fields": fields, "_dedupe_key": key})
        if args.master_sheet:
            master_record = make_master_record(
                talent, key, config_hash, cached, master_field_names
            )
            if "id" in master_record:
                master_updates.append(master_record)
            else:
                master_adds.append(master_record)
        if args.contact_log_sheet:
            contact_log_adds.append(
                make_contact_log_record(
                    talent,
                    key,
                    date=args.date,
                    account=args.account,
                    run_id=run_id,
                    config_hash=config_hash,
                    consumed=consumed,
                    quota_before=quota["remaining_count"] - (consumed_planned - 1 if consumed else consumed_planned),
                    quota_after=quota["remaining_count"] - consumed_planned,
                    reason="new_contact" if consumed else "cached_or_supplied_contact",
                    available_fields=contact_log_field_names,
                )
            )

    helper_records = [{"fields": item["fields"]} for item in records_to_add]
    quota_records = []
    if args.quota_sheet:
        quota_records.append(
            make_quota_record(
                date=args.date,
                account=args.account,
                run_id=run_id,
                daily_quota=args.daily_quota,
                reserve_quota=args.reserve_quota,
                consumed_count=quota["consumed_count"] + consumed_planned,
                available_fields=quota_field_names,
            )
        )
    plan = {
        "run_id": run_id,
        "config_hash": config_hash,
        "input_count": len(talents),
        "active_config_record_id": run_config["record_id"],
        "active_task_id": config_task_id(run_config["fields"]),
        "configured_contact_views": max_contact_views,
        "add_count": len(helper_records),
        "master_add_count": len(master_adds),
        "master_update_count": len(master_updates),
        "contact_log_add_count": len(contact_log_adds),
        "quota_audit_add_count": len(quota_records),
        "planned_contact_view_consumption": consumed_planned,
        "quota_before": quota,
        "skip_count": len(skipped),
        "skipped": skipped,
        "records": helper_records,
        "master_adds": master_adds,
        "master_updates": master_updates,
        "contact_logs": contact_log_adds,
        "quota_audits": quota_records,
    }
    if args.dry_run:
        print(json.dumps({"dry_run": True, **plan}, ensure_ascii=False, indent=2))
        return 0

    responses = {
        "results": write_records(
            args.helper,
            base_id=args.base_id,
            sheet_id=args.result_sheet,
            records=helper_records,
            dry_run=False,
        ),
    }
    if args.master_sheet:
        responses["master_adds"] = write_records(
            args.helper,
            base_id=args.base_id,
            sheet_id=args.master_sheet,
            records=master_adds,
            dry_run=False,
        )
        responses["master_updates"] = write_records(
            args.helper,
            base_id=args.base_id,
            sheet_id=args.master_sheet,
            records=master_updates,
            dry_run=False,
            mode="update",
        )
    if args.contact_log_sheet:
        responses["contact_logs"] = write_records(
            args.helper,
            base_id=args.base_id,
            sheet_id=args.contact_log_sheet,
            records=contact_log_adds,
            dry_run=False,
        )
    if args.quota_sheet:
        responses["quota_audits"] = write_records(
            args.helper,
            base_id=args.base_id,
            sheet_id=args.quota_sheet,
            records=quota_records,
            dry_run=False,
        )
    print(json.dumps({"dry_run": False, **plan, "dingtalk_response": responses}, ensure_ascii=False, indent=2))
    return 0


def command_verify(args: argparse.Namespace) -> int:
    existing = load_existing_results(
        args.helper, args.base_id, args.result_sheet, args.existing_scan_limit
    )
    record = existing.get(args.dedupe_key)
    output = {
        "dedupe_key": args.dedupe_key,
        "found": bool(record),
        "record": record,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if record else 1


def command_provision_schema(args: argparse.Namespace) -> int:
    sheets = list_sheets(args.helper, args.base_id)
    actions: list[dict[str, Any]] = []
    responses: list[dict[str, Any]] = []

    for table_name, schema_fields in OPTIONAL_TABLE_SCHEMAS.items():
        sheet_id = sheets.get(table_name)
        if not sheet_id:
            actions.append(
                {
                    "action": "create_sheet",
                    "sheet_name": table_name,
                    "field_count": len(schema_fields),
                }
            )
            responses.append(
                {
                    "sheet_name": table_name,
                    "response": create_sheet(
                        args.helper,
                        base_id=args.base_id,
                        name=table_name,
                        fields=schema_fields,
                        dry_run=args.dry_run,
                    ),
                }
            )
            if not args.dry_run:
                sheets = list_sheets(args.helper, args.base_id)
                sheet_id = sheets.get(table_name)

        if not sheet_id or args.dry_run:
            continue

        existing_fields = get_sheet_fields(args.helper, args.base_id, sheet_id)
        for field in schema_fields:
            if field["name"] in existing_fields:
                continue
            actions.append(
                {
                    "action": "create_field",
                    "sheet_name": table_name,
                    "sheet_id": sheet_id,
                    "field": field,
                }
            )
            responses.append(
                {
                    "sheet_name": table_name,
                    "field_name": field["name"],
                    "response": create_field(
                        args.helper,
                        base_id=args.base_id,
                        sheet_id=sheet_id,
                        field=field,
                        dry_run=False,
                    ),
                }
            )

    final_sheets = list_sheets(args.helper, args.base_id) if not args.dry_run else sheets
    optional_sheet_ids = {
        name: final_sheets.get(name)
        for name in OPTIONAL_TABLE_SCHEMAS
        if final_sheets.get(name)
    }
    field_counts = {}
    if not args.dry_run:
        for name, sheet_id in optional_sheet_ids.items():
            field_counts[name] = len(get_sheet_fields(args.helper, args.base_id, sheet_id))

    output = {
        "dry_run": args.dry_run,
        "base_id": args.base_id,
        "actions": actions,
        "sheet_ids": optional_sheet_ids,
        "field_counts": field_counts,
        "responses": responses,
        "commit_args": (
            ""
            if len(optional_sheet_ids) != len(OPTIONAL_TABLE_SCHEMAS)
            else (
                f"--master-sheet {optional_sheet_ids['达人主档表']} "
                f"--contact-log-sheet {optional_sheet_ids['联系方式查看日志']} "
                f"--quota-sheet {optional_sheet_ids['每日30次额度审计']}"
            )
        ),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    add_common_args(prepare)
    prepare.add_argument("--config-sheet", default=DEFAULT_CONFIG_SHEET)
    prepare.add_argument("--result-sheet", default=DEFAULT_RESULT_SHEET)
    prepare.set_defaults(func=command_prepare)

    commit = subparsers.add_parser("commit")
    add_common_args(commit)
    commit.add_argument("--config-sheet", default=DEFAULT_CONFIG_SHEET)
    commit.add_argument("--result-sheet", default=DEFAULT_RESULT_SHEET)
    commit.add_argument("--input-json", type=Path, required=True)
    commit.add_argument("--execute-date")
    commit.add_argument("--run-id")
    commit.add_argument("--config-hash")
    commit.add_argument("--dry-run", action="store_true")
    commit.add_argument("--require-wechat", action="store_true", default=True)
    commit.add_argument("--allow-missing-wechat", dest="require_wechat", action="store_false")
    commit.add_argument("--allow-duplicate-without-contact", action="store_true")
    commit.set_defaults(func=command_commit)

    verify = subparsers.add_parser("verify")
    add_common_args(verify)
    verify.add_argument("--result-sheet", default=DEFAULT_RESULT_SHEET)
    verify.add_argument("--dedupe-key", required=True)
    verify.set_defaults(func=command_verify)

    provision = subparsers.add_parser("provision-schema")
    provision.add_argument("--helper", type=Path, default=DEFAULT_HELPER)
    provision.add_argument("--base-id", default=DEFAULT_BASE_ID)
    provision.add_argument("--dry-run", action="store_true")
    provision.set_defaults(func=command_provision_schema)
    return parser


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--helper", type=Path, default=DEFAULT_HELPER)
    parser.add_argument("--base-id", default=DEFAULT_BASE_ID)
    parser.add_argument("--task-id", help="Only use the active config row whose 任务ID matches this value")
    parser.add_argument("--existing-scan-limit", type=int, default=100)
    parser.add_argument("--master-sheet")
    parser.add_argument("--contact-log-sheet")
    parser.add_argument("--quota-sheet")
    parser.add_argument("--account", default="default")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--daily-quota", type=int, default=DEFAULT_DAILY_QUOTA)
    parser.add_argument("--reserve-quota", type=int, default=DEFAULT_RESERVE_QUOTA)
    parser.add_argument("--max-contact-views", type=int, default=DEFAULT_MAX_CONTACT_VIEWS)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except SyncError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
