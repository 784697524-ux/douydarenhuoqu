#!/usr/bin/env python3
"""Small DingTalk-notable compatible adapter backed by lark-cli Base commands."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any


def parse_json_output(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {}
    if text.startswith("=== Dry Run ==="):
        text = text.split("\n", 1)[1].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"lark-cli returned non-JSON output: {text[:500]}") from exc


def run_lark(args: list[str], as_identity: str = "user") -> dict[str, Any]:
    cmd = ["lark-cli", "base", *args]
    if as_identity:
        cmd.extend(["--as", as_identity])
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(cmd)
            + f"\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return parse_json_output(proc.stdout)


def items_from(response: dict[str, Any], *names: str) -> list[dict[str, Any]]:
    data = response.get("data") if isinstance(response.get("data"), dict) else response
    for name in names:
        value = data.get(name) if isinstance(data, dict) else None
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def table_list(args: argparse.Namespace) -> dict[str, Any]:
    response = run_lark(["+table-list", "--base-token", args.base_id, "--limit", "100"], args.as_identity)
    value = []
    for item in items_from(response, "items", "tables"):
        value.append({"id": item.get("table_id") or item.get("id"), "name": item.get("name") or item.get("table_name")})
    return {"value": [item for item in value if item["id"] and item["name"]]}


def field_list(args: argparse.Namespace) -> dict[str, Any]:
    response = run_lark([
        "+field-list",
        "--base-token",
        args.base_id,
        "--table-id",
        args.sheet_id,
        "--limit",
        "100",
    ], args.as_identity)
    value = []
    for item in items_from(response, "items", "fields"):
        value.append({"id": item.get("field_id") or item.get("id"), "name": item.get("field_name") or item.get("name")})
    return {"value": [item for item in value if item["name"]]}


def records_list(args: argparse.Namespace) -> dict[str, Any]:
    limit = int(args.max_results or 100)
    offset = int(args.next_token or 0)
    response = run_lark([
        "+record-list",
        "--base-token",
        args.base_id,
        "--table-id",
        args.sheet_id,
        "--limit",
        str(limit),
        "--offset",
        str(offset),
        "--format",
        "json",
    ], args.as_identity)
    records = []
    for item in items_from(response, "items", "records"):
        records.append({"id": item.get("record_id") or item.get("id"), "fields": item.get("fields") or {}})
    has_more = len(records) >= limit
    return {"records": records, "hasMore": has_more, "nextToken": str(offset + len(records)) if has_more else ""}


def records_add(args: argparse.Namespace) -> dict[str, Any]:
    records = json.loads(args.records_json)
    value = []
    for record in records:
        fields = record.get("fields", {}) if isinstance(record, dict) else {}
        response = run_lark([
            "+record-upsert",
            "--base-token",
            args.base_id,
            "--table-id",
            args.sheet_id,
            "--json",
            json.dumps(fields, ensure_ascii=False),
        ], args.as_identity)
        data = response.get("data") if isinstance(response.get("data"), dict) else response
        value.append({"id": data.get("record_id") or data.get("id") or ""})
    return {"value": value}


def records_update(args: argparse.Namespace) -> dict[str, Any]:
    records = json.loads(args.records_json)
    value = []
    for record in records:
        if not isinstance(record, dict) or not record.get("id"):
            continue
        response = run_lark([
            "+record-upsert",
            "--base-token",
            args.base_id,
            "--table-id",
            args.sheet_id,
            "--record-id",
            str(record["id"]),
            "--json",
            json.dumps(record.get("fields", {}), ensure_ascii=False),
        ], args.as_identity)
        data = response.get("data") if isinstance(response.get("data"), dict) else response
        value.append({"id": data.get("record_id") or record["id"]})
    return {"value": value}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="scope", required=True)
    notable = sub.add_parser("notable")
    notable_sub = notable.add_subparsers(dest="command", required=True)

    sheets = notable_sub.add_parser("sheets")
    sheets.add_argument("--base-id", required=True)
    sheets.add_argument("--as", dest="as_identity", default="user")
    sheets.set_defaults(func=table_list)

    fields = notable_sub.add_parser("fields")
    fields.add_argument("--base-id", required=True)
    fields.add_argument("--sheet-id", required=True)
    fields.add_argument("--as", dest="as_identity", default="user")
    fields.set_defaults(func=field_list)

    for name, func in (("records-list", records_list), ("records-add", records_add), ("records-update", records_update)):
        command = notable_sub.add_parser(name)
        command.add_argument("--base-id", required=True)
        command.add_argument("--sheet-id", required=True)
        command.add_argument("--as", dest="as_identity", default="user")
        command.add_argument("--max-results")
        command.add_argument("--next-token")
        command.add_argument("--records-json")
        command.add_argument("--dry-run", action="store_true")
        command.set_defaults(func=func)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        print(json.dumps(args.func(args), ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
