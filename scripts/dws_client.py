#!/usr/bin/env python3
"""Thin client for the public dws CLI (DingTalk Workspace CLI) to access DingTalk AI Tables.

This module is the ONLY place that talks to the `dws` binary. Install it with:

    npm install -g dingtalk-workspace-cli

All record payloads use dws conventions:
- reads return raw records like {"recordId": "...", "cells": {"<fieldId>": value}}
- writes take records like {"cells": {"<fieldId>": value}} or
  {"recordId": "...", "cells": {"<fieldId>": value}}

FieldCodec converts between fieldId-keyed cells and field-name-keyed dicts so
the rest of this project can keep working with human-readable Chinese field
names.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

RETRYABLE_MARKERS = (
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
    "ETIMEDOUT",
    "ECONNRESET",
    "connection reset",
)

MAX_RECORDS_PER_WRITE = 100
MAX_RECORDS_PER_READ = 100


class DwsError(RuntimeError):
    """Raised when a dws command fails or returns an error payload."""


def _parse_json_output(text: str) -> dict[str, Any]:
    """dws may print retry/log lines before the JSON; parse from the first '{'."""
    start = text.find("{")
    if start < 0:
        raise DwsError(f"dws produced no JSON output: {text[:300]}")
    try:
        return json.loads(text[start:])
    except json.JSONDecodeError as exc:
        raise DwsError(f"dws produced invalid JSON: {text[:300]}") from exc


def is_retryable_failure(text: str) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in RETRYABLE_MARKERS)


class DwsClient:
    """Subprocess wrapper around the public dws CLI with retry and JSON parsing."""

    def __init__(self, binary: str = "dws", timeout: int = 120, retries: int = 3) -> None:
        self.binary = binary
        self.timeout = timeout
        self.retries = retries

    # ---------- low level ----------

    def run(self, args: list[str], timeout: int | None = None) -> dict[str, Any]:
        cmd = [self.binary, *args, "--format", "json"]
        last_error = ""
        for attempt in range(1, self.retries + 1):
            try:
                proc = subprocess.run(
                    cmd, text=True, capture_output=True, check=False,
                    timeout=timeout or self.timeout,
                )
            except subprocess.TimeoutExpired:
                last_error = f"dws timed out after {timeout or self.timeout}s: {' '.join(cmd[:6])}"
                if attempt == self.retries or not is_retryable_failure(last_error):
                    break
                time.sleep(attempt * 2)
                continue
            except FileNotFoundError as exc:
                raise DwsError(
                    "dws CLI not found. Install it first: npm install -g dingtalk-workspace-cli"
                ) from exc
            combined = (proc.stdout or "") + (proc.stderr or "")
            if proc.returncode == 0:
                return _parse_json_output(combined)
            last_error = f"dws failed (rc={proc.returncode}): {combined[:500]}"
            if attempt == self.retries or not is_retryable_failure(last_error):
                break
            time.sleep(attempt * 2)
        raise DwsError(last_error)

    @staticmethod
    def _unwrap(response: dict[str, Any]) -> dict[str, Any]:
        return response.get("data") if isinstance(response.get("data"), dict) else response

    # ---------- base / table ----------

    def create_base(self, name: str) -> str:
        response = self.run(["aitable", "base", "create", "--name", name])
        data = self._unwrap(response)
        base_id = data.get("baseId") or response.get("baseId")
        if not base_id:
            raise DwsError(f"base create returned no baseId: {json.dumps(response, ensure_ascii=False)[:300]}")
        return str(base_id)

    def list_tables(self, base_id: str) -> dict[str, str]:
        response = self.run(["aitable", "+list-tables", "--base", base_id])
        data = self._unwrap(response)
        tables = data.get("tables") or response.get("tables") or []
        result: dict[str, str] = {}
        for table in tables:
            name = table.get("tableName") or table.get("name")
            table_id = table.get("tableId") or table.get("id")
            if name and table_id:
                result[str(name)] = str(table_id)
        return result

    def create_table(self, base_id: str, name: str, dws_fields: list[dict[str, Any]]) -> str:
        """Create one table with fields. dws_fields: [{"fieldName","type","config"?}]"""
        response = self.run(
            [
                "aitable", "table", "create",
                "--base-id", base_id,
                "--name", name,
                "--fields", json.dumps(dws_fields, ensure_ascii=False),
            ]
        )
        data = self._unwrap(response)
        table_id = data.get("tableId") or response.get("tableId")
        if not table_id:
            raise DwsError(f"table create returned no tableId: {json.dumps(response, ensure_ascii=False)[:300]}")
        return str(table_id)

    # ---------- fields ----------

    def list_fields(self, base_id: str, table_id: str) -> list[dict[str, Any]]:
        """Return raw field list: [{"fieldId","fieldName","type","config"?}]"""
        response = self.run(
            ["aitable", "field", "list", "--base-id", base_id, "--table-id", table_id]
        )
        data = self._unwrap(response)
        fields = data.get("fields") or response.get("fields") or []
        if not fields:
            raise DwsError(
                f"field list returned no fields for table {table_id}: "
                f"{json.dumps(response, ensure_ascii=False)[:300]}"
            )
        return fields

    def create_field(
        self, base_id: str, table_id: str, name: str, field_type: str, config: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        args = [
            "aitable", "field", "create",
            "--base-id", base_id, "--table-id", table_id,
            "--name", name, "--type", field_type,
        ]
        if config:
            args.extend(["--config", json.dumps(config, ensure_ascii=False)])
        return self.run(args)

    # ---------- records ----------

    def query_records(
        self, base_id: str, table_id: str, limit: int = MAX_RECORDS_PER_READ
    ) -> list[dict[str, Any]]:
        """Single-page query. Returns raw records (cells keyed by fieldId)."""
        response = self.run(
            [
                "aitable", "record", "query",
                "--base-id", base_id, "--table-id", table_id,
                "--limit", str(min(limit, MAX_RECORDS_PER_READ)),
            ]
        )
        data = self._unwrap(response)
        records = data.get("records") or response.get("records") or []
        return list(records)

    def query_all_records(
        self, base_id: str, table_id: str, max_records: int = 500
    ) -> list[dict[str, Any]]:
        """Auto-paginated full scan, bounded by max_records (rounded up to pages of 100)."""
        if max_records <= MAX_RECORDS_PER_READ:
            return self.query_records(base_id, table_id, max_records)
        page_limit = (max_records + MAX_RECORDS_PER_READ - 1) // MAX_RECORDS_PER_READ
        response = self.run(
            [
                "aitable", "record", "query",
                "--base-id", base_id, "--table-id", table_id,
                "--all", "--page-limit", str(page_limit),
            ]
        )
        data = self._unwrap(response)
        records = data.get("records") or response.get("records") or []
        return list(records)

    def create_records(
        self, base_id: str, table_id: str, records: list[dict[str, Any]]
    ) -> int:
        """records: [{"cells": {"<fieldId>": value}}]. Returns created count."""
        created = 0
        for chunk in _chunked(records, MAX_RECORDS_PER_WRITE):
            payload = json.dumps(chunk, ensure_ascii=False)
            response = self.run(
                [
                    "aitable", "record", "create",
                    "--base-id", base_id, "--table-id", table_id,
                    "--records", payload,
                ],
                timeout=self.timeout,
            )
            data = self._unwrap(response)
            ids = data.get("recordIds") or data.get("records") or []
            created += len(ids) if isinstance(ids, list) else len(chunk)
        return created

    def update_records(
        self, base_id: str, table_id: str, records: list[dict[str, Any]]
    ) -> int:
        """records: [{"recordId": "...", "cells": {...}}]. Returns updated count."""
        updated = 0
        for chunk in _chunked(records, MAX_RECORDS_PER_WRITE):
            payload = json.dumps(chunk, ensure_ascii=False)
            response = self.run(
                [
                    "aitable", "record", "update",
                    "--base-id", base_id, "--table-id", table_id,
                    "--records", payload,
                ],
                timeout=self.timeout,
            )
            data = self._unwrap(response)
            ids = data.get("recordIds") or data.get("records") or []
            updated += len(ids) if isinstance(ids, list) else len(chunk)
        return updated


class FieldCodec:
    """fieldId <-> fieldName mapping for one table."""

    def __init__(self, client: DwsClient, base_id: str, table_id: str) -> None:
        self.client = client
        self.base_id = base_id
        self.table_id = table_id
        self._id_by_name: dict[str, str] = {}
        self._name_by_id: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        self._id_by_name.clear()
        self._name_by_id.clear()
        for field in self.client.list_fields(self.base_id, self.table_id):
            name = str(field.get("fieldName") or field.get("name") or "")
            field_id = str(field.get("fieldId") or field.get("id") or "")
            if name and field_id:
                self._id_by_name[name] = field_id
                self._name_by_id[field_id] = name

    def names(self) -> set[str]:
        return set(self._id_by_name)

    def encode(self, fields_by_name: dict[str, Any]) -> dict[str, Any]:
        """Convert {fieldName: value} to {fieldId: value}; unknown names are skipped."""
        cells: dict[str, Any] = {}
        for name, value in fields_by_name.items():
            field_id = self._id_by_name.get(str(name))
            if field_id is not None and value not in ("", None):
                cells[field_id] = value
        return cells

    def encode_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Convert {"fields": {...}} (+ optional "id") to dws record payload."""
        payload: dict[str, Any] = {"cells": self.encode(record.get("fields", {}))}
        record_id = record.get("id") or record.get("recordId")
        if record_id:
            payload["recordId"] = str(record_id)
        return payload

    def decode(self, raw_record: dict[str, Any]) -> dict[str, Any]:
        """Convert dws raw record to {"id": ..., "fields": {fieldName: value}}."""
        fields: dict[str, Any] = {}
        for field_id, value in (raw_record.get("cells") or {}).items():
            name = self._name_by_id.get(str(field_id), str(field_id))
            fields[name] = value
        record_id = raw_record.get("recordId") or raw_record.get("id")
        return {"id": record_id, "fields": fields}


def _chunked(items: list[Any], size: int) -> list[list[Any]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def schema_to_dws_fields(schema_fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert schema_spec format [{name, type, property?}] to dws [{fieldName, type, config?}].

    Number formatter properties are display-only and intentionally dropped so
    that every field is created with the plainest accepted type.
    """
    dws_fields: list[dict[str, Any]] = []
    for field in schema_fields:
        entry: dict[str, Any] = {
            "fieldName": str(field["name"]),
            "type": str(field["type"]),
        }
        if field.get("config"):
            entry["config"] = field["config"]
        dws_fields.append(entry)
    return dws_fields
