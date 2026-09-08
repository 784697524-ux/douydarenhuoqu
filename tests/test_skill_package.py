#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dws_client import FieldCodec, schema_to_dws_fields  # noqa: E402
from runtime_config import DEFAULT_CONFIG, load_config, save_config  # noqa: E402
from schema_spec import TABLE_KEYS, TABLE_SCHEMAS  # noqa: E402


class FakeClient:
    """Minimal DwsClient stand-in for codec tests (no network)."""

    def list_fields(self, base_id: str, table_id: str) -> list[dict]:
        assert base_id == "base_demo"
        assert table_id == "tbl_demo"
        return [
            {"fieldId": "fld01", "fieldName": "任务ID"},
            {"fieldId": "fld02", "fieldName": "启用"},
            {"fieldId": "fld03", "fieldName": "查询次数"},
        ]


class SkillPackageTest(unittest.TestCase):
    def test_schema_has_six_expected_tables(self) -> None:
        self.assertEqual(
            set(TABLE_SCHEMAS),
            {"配置表", "结果表", "达人主档表", "联系方式查看日志", "每日30次额度审计", "任务执行游标表"},
        )
        self.assertEqual(set(TABLE_KEYS), set(TABLE_SCHEMAS))
        self.assertIn("查询次数", [field["name"] for field in TABLE_SCHEMAS["配置表"]])
        self.assertIn("微信号", [field["name"] for field in TABLE_SCHEMAS["结果表"]])

    def test_config_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            config = json.loads(json.dumps(DEFAULT_CONFIG, ensure_ascii=False))
            config["backend"] = "dingtalk"
            config["dingtalk"]["base_id"] = "base_demo"
            config["dingtalk"]["config_sheet"] = "cfg_demo"
            config["dingtalk"]["result_sheet"] = "res_demo"
            save_config(config, path)
            loaded = load_config(path)
            self.assertEqual(loaded["backend"], "dingtalk")
            self.assertEqual(loaded["dingtalk"]["base_id"], "base_demo")
            self.assertEqual(loaded["quota"]["daily_quota"], 30)
            self.assertEqual(loaded["dws_binary"], "dws")
            self.assertNotIn("feishu", loaded)
            self.assertNotIn("helper", loaded["dingtalk"])

    def test_field_codec_round_trip(self) -> None:
        codec = FieldCodec(FakeClient(), "base_demo", "tbl_demo")  # type: ignore[arg-type]
        cells = codec.encode({"任务ID": "001", "启用": "是", "不存在字段": "x", "查询次数": ""})
        self.assertEqual(cells, {"fld01": "001", "fld02": "是"})
        decoded = codec.decode({"recordId": "rec1", "cells": cells})
        self.assertEqual(decoded["id"], "rec1")
        self.assertEqual(decoded["fields"]["任务ID"], "001")
        encoded_record = codec.encode_record({"id": "rec1", "fields": {"任务ID": "001"}})
        self.assertEqual(encoded_record, {"recordId": "rec1", "cells": {"fld01": "001"}})

    def test_schema_to_dws_fields(self) -> None:
        dws_fields = schema_to_dws_fields(TABLE_SCHEMAS["达人主档表"])
        self.assertEqual(dws_fields[0], {"fieldName": "dedupe_key", "type": "text"})
        names = [field["fieldName"] for field in dws_fields]
        self.assertIn("微信号", names)
        for field in dws_fields:
            self.assertIn("fieldName", field)
            self.assertIn("type", field)
            self.assertIn(field["type"], {"text", "number"})

    def test_no_known_sensitive_strings(self) -> None:
        raw_markers = os.environ.get("SENSITIVE_MARKERS", "")
        forbidden = [item for item in raw_markers.split("|") if item]
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix in {".pyc"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for marker in forbidden:
                self.assertNotIn(marker, text, msg=f"{marker} leaked in {path}")


if __name__ == "__main__":
    unittest.main()
