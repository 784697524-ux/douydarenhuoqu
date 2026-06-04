#!/usr/bin/env python3
"""Provision DingTalk AI Table or Feishu Base tables for the talent contact skill."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from runtime_config import DEFAULT_CONFIG, DEFAULT_CONFIG_PATH, deep_merge, save_config  # noqa: E402
from schema_spec import TABLE_KEYS, TABLE_SCHEMAS  # noqa: E402


def run_json(cmd: list[str]) -> dict[str, Any]:
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(cmd)
            + f"\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    if not proc.stdout.strip():
        return {}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"text": proc.stdout}


def dingtalk_helper(args: argparse.Namespace) -> Path:
    return Path(args.helper or DEFAULT_CONFIG["dingtalk"]["helper"]).expanduser()


def dingtalk_list_sheets(helper: Path, base_id: str) -> dict[str, str]:
    response = run_json([sys.executable, str(helper), "notable", "sheets", "--base-id", base_id])
    return {
        str(sheet.get("name")): str(sheet.get("id"))
        for sheet in response.get("value", [])
        if sheet.get("name") and sheet.get("id")
    }


def dingtalk_field_names(helper: Path, base_id: str, sheet_id: str) -> set[str]:
    response = run_json([
        sys.executable,
        str(helper),
        "notable",
        "fields",
        "--base-id",
        base_id,
        "--sheet-id",
        sheet_id,
    ])
    return {str(field.get("name")) for field in response.get("value", []) if field.get("name")}


def dingtalk_create_sheet(helper: Path, base_id: str, name: str, fields: list[dict[str, Any]], dry_run: bool) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(helper),
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
    return run_json(cmd)


def dingtalk_create_field(helper: Path, base_id: str, sheet_id: str, field: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(helper),
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
    if field.get("property"):
        cmd.extend(["--property-json", json.dumps(field["property"], ensure_ascii=False)])
    if dry_run:
        cmd.append("--dry-run")
    return run_json(cmd)


def provision_dingtalk(args: argparse.Namespace) -> dict[str, Any]:
    if not args.base_id:
        raise ValueError("--base-id is required for DingTalk provisioning")
    helper = dingtalk_helper(args)
    sheets = {} if args.dry_run else dingtalk_list_sheets(helper, args.base_id)
    sheet_ids: dict[str, str] = {}
    actions: list[dict[str, Any]] = []

    for table_name, fields in TABLE_SCHEMAS.items():
        sheet_id = sheets.get(table_name)
        if not sheet_id:
            actions.append({"action": "create_sheet", "table": table_name, "field_count": len(fields)})
            response = dingtalk_create_sheet(helper, args.base_id, table_name, fields, args.dry_run)
            if not args.dry_run:
                sheets = dingtalk_list_sheets(helper, args.base_id)
                sheet_id = sheets.get(table_name) or str(response.get("id") or response.get("sheetId") or "")
        if not sheet_id:
            continue
        sheet_ids[TABLE_KEYS[table_name]] = sheet_id
        if args.dry_run:
            continue
        existing_fields = dingtalk_field_names(helper, args.base_id, sheet_id)
        for field in fields:
            if field["name"] in existing_fields:
                continue
            actions.append({"action": "create_field", "table": table_name, "field": field["name"]})
            dingtalk_create_field(helper, args.base_id, sheet_id, field, False)

    return {"backend": "dingtalk", "base_id": args.base_id, "sheet_ids": sheet_ids, "actions": actions}


def feishu_cmd(args: argparse.Namespace, extra: list[str]) -> list[str]:
    cmd = ["lark-cli", "base", *extra]
    if args.as_identity:
        cmd.extend(["--as", args.as_identity])
    return cmd


def feishu_list_tables(args: argparse.Namespace, base_token: str) -> dict[str, str]:
    response = run_json(feishu_cmd(args, ["+table-list", "--base-token", base_token, "--limit", "100"]))
    data = response.get("data") or response
    items = data.get("items") or data.get("tables") or response.get("items") or []
    tables = {}
    for item in items:
        name = item.get("name") or item.get("table_name")
        table_id = item.get("table_id") or item.get("id")
        if name and table_id:
            tables[str(name)] = str(table_id)
    return tables


def feishu_field_names(args: argparse.Namespace, base_token: str, table_id: str) -> set[str]:
    response = run_json(feishu_cmd(args, [
        "+field-list",
        "--base-token",
        base_token,
        "--table-id",
        table_id,
        "--limit",
        "100",
    ]))
    data = response.get("data") or response
    items = data.get("items") or data.get("fields") or response.get("items") or []
    return {str(item.get("field_name") or item.get("name")) for item in items if item.get("field_name") or item.get("name")}


def feishu_create_base(args: argparse.Namespace) -> str:
    if not args.folder_token:
        raise ValueError("--folder-token is required when --base-token is omitted")
    response = run_json(feishu_cmd(args, [
        "+base-create",
        "--folder-token",
        args.folder_token,
        "--name",
        args.base_name,
        "--time-zone",
        "Asia/Shanghai",
    ] + (["--dry-run"] if args.dry_run else [])))
    data = response.get("data") or response
    return str(data.get("app_token") or data.get("base_token") or response.get("app_token") or "")


def provision_feishu(args: argparse.Namespace) -> dict[str, Any]:
    base_token = args.base_token or ("" if args.dry_run else feishu_create_base(args))
    if not base_token and not args.dry_run:
        raise RuntimeError("Could not resolve Feishu base token from lark-cli response")
    tables = {} if args.dry_run or not base_token else feishu_list_tables(args, base_token)
    table_ids: dict[str, str] = {}
    actions: list[dict[str, Any]] = []

    for table_name, fields in TABLE_SCHEMAS.items():
        table_id = tables.get(table_name)
        if not table_id:
            actions.append({"action": "create_table", "table": table_name, "field_count": len(fields)})
            cmd = feishu_cmd(args, [
                "+table-create",
                "--base-token",
                base_token or "<created_base_token>",
                "--name",
                table_name,
                "--fields",
                json.dumps(fields, ensure_ascii=False),
            ])
            if args.dry_run:
                cmd.append("--dry-run")
            response = run_json(cmd)
            if not args.dry_run:
                data = response.get("data") or response
                table_id = str(data.get("table_id") or data.get("id") or "")
        if not table_id:
            continue
        table_ids[TABLE_KEYS[table_name].replace("_sheet", "_table")] = table_id
        if args.dry_run:
            continue
        existing_fields = feishu_field_names(args, base_token, table_id)
        for field in fields:
            if field["name"] in existing_fields:
                continue
            actions.append({"action": "create_field", "table": table_name, "field": field["name"]})
            run_json(feishu_cmd(args, [
                "+field-create",
                "--base-token",
                base_token,
                "--table-id",
                table_id,
                "--json",
                json.dumps(field, ensure_ascii=False),
            ]))

    return {"backend": "feishu", "base_token": base_token, "table_ids": table_ids, "actions": actions}


def write_runtime_config(args: argparse.Namespace, provision: dict[str, Any]) -> Path | None:
    if not args.write_config:
        return None
    config = DEFAULT_CONFIG.copy()
    if args.config_template and args.config_template.exists():
        config = deep_merge(config, json.loads(args.config_template.read_text(encoding="utf-8")))
    config["backend"] = provision["backend"]
    if provision["backend"] == "dingtalk":
        config["dingtalk"].update({"base_id": provision["base_id"], **provision.get("sheet_ids", {})})
    else:
        config["feishu"].update({"base_token": provision.get("base_token", ""), **provision.get("table_ids", {})})
    return save_config(config, args.config)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["dingtalk", "feishu"], required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--write-config", action="store_true")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--config-template", type=Path)
    parser.add_argument("--helper", help="DingTalk helper path")
    parser.add_argument("--base-id", help="DingTalk AI Table base id")
    parser.add_argument("--base-token", help="Feishu Base app/base token")
    parser.add_argument("--folder-token", help="Feishu folder token for creating a new Base")
    parser.add_argument("--base-name", default="抖音来客达人广场获取联系方式")
    parser.add_argument("--as", dest="as_identity", default="user", help="Feishu lark-cli identity: user or bot")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        provision = provision_dingtalk(args) if args.backend == "dingtalk" else provision_feishu(args)
        config_path = write_runtime_config(args, provision)
        print(json.dumps({"ok": True, "config_path": str(config_path or ""), **provision}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
