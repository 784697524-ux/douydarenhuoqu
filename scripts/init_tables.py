#!/usr/bin/env python3
"""Provision the six DingTalk AI Tables for the talent contact skill.

Two modes:

1. Existing base (you already created a Base in DingTalk and copied its ID):

    python3 scripts/init_tables.py --base-id <DINGTALK_BASE_ID> --write-config

2. First use (no base id anywhere): create a brand-new Base with all six
   tables and full fields, then write the local config:

    python3 scripts/init_tables.py --create-base --write-config

The entry command `run_talent_task.py` calls ensure_tables() automatically on
first use, so manual execution is only needed when you want to control where
tables land.

Requires the public dws CLI:
    npm install -g dingtalk-workspace-cli
    dws auth login   # once, with the DingTalk account that owns the tables
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from dws_client import DwsClient, DwsError, FieldCodec, schema_to_dws_fields  # noqa: E402
from runtime_config import (  # noqa: E402
    DEFAULT_CONFIG,
    DEFAULT_CONFIG_PATH,
    deep_merge,
    load_config,
    save_config,
)
from schema_spec import TABLE_KEYS, TABLE_SCHEMAS  # noqa: E402

DEFAULT_BASE_NAME = "达人广场筛选与联系回填配置"


def ensure_tables(
    client: DwsClient,
    base_id: str,
    *,
    create_missing: bool = True,
) -> dict[str, Any]:
    """Make sure all six tables exist (create the missing ones) and return {name: tableId}."""
    tables = client.list_tables(base_id)
    actions: list[dict[str, Any]] = []
    for table_name, schema_fields in TABLE_SCHEMAS.items():
        if tables.get(table_name):
            continue
        if not create_missing:
            actions.append({"action": "missing", "table": table_name})
            continue
        client.create_table(base_id, table_name, schema_to_dws_fields(schema_fields))
        actions.append({"action": "create_table", "table": table_name, "field_count": len(schema_fields)})
        tables = client.list_tables(base_id)
        if not tables.get(table_name):
            raise DwsError(f"table {table_name} was created but not found on re-list of base {base_id}")

    missing_fields: list[str] = []
    for table_name, schema_fields in TABLE_SCHEMAS.items():
        table_id = tables[table_name]
        codec = FieldCodec(client, base_id, table_id)
        existing_names = codec.names()
        for field in schema_fields:
            if field["name"] in existing_names:
                continue
            client.create_field(base_id, table_id, field["name"], field["type"])
            missing_fields.append(f"{table_name}.{field['name']}")
            codec.reload()
    if missing_fields:
        actions.append({"action": "create_fields", "fields": missing_fields})

    return {"base_id": base_id, "tables": tables, "actions": actions}


def create_base_with_tables(client: DwsClient, base_name: str) -> dict[str, Any]:
    """First-use flow: create a new Base, then ensure all six tables inside it."""
    base_id = client.create_base(base_name)
    result = ensure_tables(client, base_id)
    result["base_name"] = base_name
    result["doc_url"] = f"https://alidocs.dingtalk.com/i/nodes/{base_id}"
    return result


def write_config_from_tables(result: dict[str, Any], config_path: Path) -> dict[str, Any]:
    """Persist base_id + all sheet ids into the local runtime config."""
    config = load_config(config_path) if config_path.exists() else json.loads(json.dumps(DEFAULT_CONFIG))
    config = deep_merge(config, {"backend": "dingtalk"})
    dingtalk = config.setdefault("dingtalk", {})
    dingtalk["base_id"] = result["base_id"]
    for table_name, config_key in TABLE_KEYS.items():
        table_id = result["tables"].get(table_name)
        if table_id:
            dingtalk[config_key] = table_id
    save_config(config, config_path)
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-id", help="Existing DingTalk AI Table base id")
    parser.add_argument("--create-base", action="store_true", help="Create a brand-new base first")
    parser.add_argument("--base-name", default=DEFAULT_BASE_NAME, help="Name for the newly created base")
    parser.add_argument("--dws-binary", default="dws", help="Path to the dws CLI binary")
    parser.add_argument("--write-config", action="store_true", help="Write table ids into the local config file")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Local config path")
    parser.add_argument("--dry-run", action="store_true", help="Only report what would happen")
    args = parser.parse_args(argv)

    client = DwsClient(binary=args.dws_binary)
    try:
        base_id = args.base_id
        if not base_id and not args.create_base:
            existing = load_config(args.config) if args.config.exists() else {}
            base_id = str(existing.get("dingtalk", {}).get("base_id") or "")
            if not base_id:
                args.create_base = True
        if args.dry_run:
            print(json.dumps({
                "dry_run": True,
                "base_id": base_id or "<new>",
                "tables": list(TABLE_SCHEMAS),
            }, ensure_ascii=False, indent=2))
            return 0
        if args.create_base:
            result = create_base_with_tables(client, args.base_name)
        else:
            result = ensure_tables(client, base_id)
        if args.write_config:
            result["config_path"] = str(args.config)
            write_config_from_tables(result, args.config)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except DwsError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
