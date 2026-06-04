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

from runtime_config import DEFAULT_CONFIG, load_config, save_config  # noqa: E402
from schema_spec import TABLE_KEYS, TABLE_SCHEMAS  # noqa: E402


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
