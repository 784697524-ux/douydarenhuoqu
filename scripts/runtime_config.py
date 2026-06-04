#!/usr/bin/env python3
"""Load local runtime config for the Douyin Life talent contact skill."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

CONFIG_HOME = Path.home() / ".douyin-life-talent-contact"
DEFAULT_CONFIG_PATH = CONFIG_HOME / "config.json"
DEFAULT_DOUYIN_URL = (
    "https://life.douyin.com/p/liteapp/alliance_merchant/merchant/talent/square"
    "?enter_from=pc_menu_daren_square"
)
DEFAULT_DINGTALK_HELPER = (
    Path.home()
    / ".codex"
    / "skills"
    / "dingtalk-knowledge-manager"
    / "scripts"
    / "dingtalk_tool.py"
)

DEFAULT_CONFIG: dict[str, Any] = {
    "backend": "dingtalk",
    "chrome_cdp_url": "http://127.0.0.1:9222",
    "douyin_url": DEFAULT_DOUYIN_URL,
    "quota": {"daily_quota": 30, "reserve_quota": 0, "max_contact_views": 1},
    "account": "auto",
    "dingtalk": {
        "helper": str(DEFAULT_DINGTALK_HELPER),
        "base_id": "",
        "config_sheet": "",
        "result_sheet": "",
        "master_sheet": "",
        "contact_log_sheet": "",
        "quota_sheet": "",
        "cursor_sheet": "",
    },
    "feishu": {
        "base_token": "",
        "config_table": "",
        "result_table": "",
        "master_table": "",
        "contact_log_table": "",
        "quota_table": "",
        "cursor_table": "",
        "as": "user",
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    config_path = Path(path or DEFAULT_CONFIG_PATH).expanduser()
    if not config_path.exists():
        raise FileNotFoundError(
            f"config not found: {config_path}. Run scripts/init_tables.py --write-config first."
        )
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config root must be a JSON object")
    return deep_merge(DEFAULT_CONFIG, data)


def save_config(config: dict[str, Any], path: Path | str | None = None) -> Path:
    config_path = Path(path or DEFAULT_CONFIG_PATH).expanduser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return config_path


def backend_config(config: dict[str, Any]) -> dict[str, Any]:
    backend = str(config.get("backend") or "dingtalk")
    if backend not in {"dingtalk", "feishu"}:
        raise ValueError("backend must be 'dingtalk' or 'feishu'")
    return config[backend]


def require_keys(data: dict[str, Any], keys: list[str], label: str) -> None:
    missing = [key for key in keys if not str(data.get(key) or "").strip()]
    if missing:
        raise ValueError(f"missing {label} config keys: {', '.join(missing)}")
