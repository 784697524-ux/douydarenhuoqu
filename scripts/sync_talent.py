#!/usr/bin/env python3
"""Sync Douyin Life talent contact data into a DingTalk AI Table."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from dws_client import DwsClient, FieldCodec


DEFAULT_BASE_ID = ""
DEFAULT_CONFIG_SHEET = ""
DEFAULT_RESULT_SHEET = ""
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


class DingTalkStore:
    """Name-keyed table access over the public dws CLI.

    All business logic keeps working with {"id": ..., "fields": {中文字段名: 值}}
    records; this class translates to/from dws fieldId-keyed cells.
    """

    def __init__(self, client: DwsClient, base_id: str) -> None:
        self.client = client
        self.base_id = base_id
        self._codecs: dict[str, FieldCodec] = {}

    def codec(self, sheet_id: str | None) -> FieldCodec | None:
        if not sheet_id:
            return None
        if sheet_id not in self._codecs:
            self._codecs[sheet_id] = FieldCodec(self.client, self.base_id, sheet_id)
        return self._codecs[sheet_id]

    def query_records(self, sheet_id: str | None, scan_limit: int) -> list[dict[str, Any]]:
        if not sheet_id:
            return []
        codec = self.codec(sheet_id)
        raw = self.client.query_all_records(self.base_id, sheet_id, max_records=scan_limit)
        return [codec.decode(record) for record in raw]

    def field_names(self, sheet_id: str | None) -> set[str]:
        codec = self.codec(sheet_id)
        return codec.names() if codec else set()

    def list_sheets(self) -> dict[str, str]:
        return self.client.list_tables(self.base_id)

    def write_records(
        self, *, sheet_id: str, records: list[dict[str, Any]], mode: str = "add"
    ) -> dict[str, Any]:
        if not records:
            return {"count": 0}
        codec = self.codec(sheet_id)
        payloads = [codec.encode_record(record) for record in records]
        if mode == "update":
            count = self.client.update_records(self.base_id, sheet_id, payloads)
        else:
            count = self.client.create_records(self.base_id, sheet_id, payloads)
        return {"count": count}


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
    store = make_store(args)
    config = load_active_config(store, args.config_sheet, args.task_id)
    result_fields = store.field_names(args.result_sheet)
    existing = load_existing_results(store, args.result_sheet, args.existing_scan_limit)
    master = load_master_contacts(store, args.master_sheet, args.existing_scan_limit)
    contact_logs = load_contact_logs(store, args.contact_log_sheet, args.existing_scan_limit)
    master_field_names = store.field_names(args.master_sheet) if args.master_sheet else set()
    contact_log_field_names = (
        store.field_names(args.contact_log_sheet) if args.contact_log_sheet else set()
    )
    quota_field_names = store.field_names(args.quota_sheet) if args.quota_sheet else set()
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
    store = make_store(args)
    talents = load_talents(args.input_json)
    result_fields = store.field_names(args.result_sheet)
    existing = load_existing_results(store, args.result_sheet, args.existing_scan_limit)
    master = load_master_contacts(store, args.master_sheet, args.existing_scan_limit)
    contact_logs = load_contact_logs(store, args.contact_log_sheet, args.existing_scan_limit)
    master_field_names = store.field_names(args.master_sheet) if args.master_sheet else set()
    contact_log_field_names = (
        store.field_names(args.contact_log_sheet) if args.contact_log_sheet else set()
    )
    quota_field_names = store.field_names(args.quota_sheet) if args.quota_sheet else set()
    execute_date = args.execute_date or dt.date.today().isoformat()
    run_config = load_active_config(store, args.config_sheet, args.task_id)
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
        "results": store.write_records(sheet_id=args.result_sheet, records=helper_records),
    }
    if args.master_sheet:
        responses["master_adds"] = store.write_records(
            sheet_id=args.master_sheet, records=master_adds
        )
        responses["master_updates"] = store.write_records(
            sheet_id=args.master_sheet, records=master_updates, mode="update"
        )
    if args.contact_log_sheet:
        responses["contact_logs"] = store.write_records(
            sheet_id=args.contact_log_sheet, records=contact_log_adds
        )
    if args.quota_sheet:
        responses["quota_audits"] = store.write_records(
            sheet_id=args.quota_sheet, records=quota_records
        )
    print(json.dumps({"dry_run": False, **plan, "dingtalk_response": responses}, ensure_ascii=False, indent=2))
    return 0


def command_verify(args: argparse.Namespace) -> int:
    store = make_store(args)
    existing = load_existing_results(store, args.result_sheet, args.existing_scan_limit)
    record = existing.get(args.dedupe_key)
    output = {
        "dedupe_key": args.dedupe_key,
        "found": bool(record),
        "record": record,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if record else 1


def command_provision_schema(args: argparse.Namespace) -> int:
    """Ensure all six tables (and their fields) exist in the configured base."""
    from init_tables import ensure_tables  # local import to avoid a cycle at module load

    client = DwsClient(binary=args.dws_binary)
    if not args.base_id:
        raise SyncError("--base-id is required (or run scripts/init_tables.py --create-base)")
    result = ensure_tables(client, args.base_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def make_store(args: argparse.Namespace) -> DingTalkStore:
    if not args.base_id:
        raise SyncError(
            "--base-id is required. Run scripts/init_tables.py --create-base --write-config "
            "first (or let run_talent_task.py auto-provision on first use)."
        )
    return DingTalkStore(DwsClient(binary=args.dws_binary), args.base_id)


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
    provision.add_argument("--dws-binary", default="dws")
    provision.add_argument("--base-id", default=DEFAULT_BASE_ID)
    provision.add_argument("--dry-run", action="store_true")
    provision.set_defaults(func=command_provision_schema)
    return parser


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dws-binary", default="dws")
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
