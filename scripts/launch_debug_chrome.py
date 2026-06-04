#!/usr/bin/env python3
"""Launch a dedicated Chrome profile for Douyin talent automation."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


DEFAULT_PROFILE = Path.home() / ".douyin-talent-chrome"
DEFAULT_URL = (
    "https://life.douyin.com/p/liteapp/alliance_merchant/merchant/talent/square"
    "?enter_from=pc_menu_daren_square"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--url", default=DEFAULT_URL)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.profile_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "open",
        "-na",
        "Google Chrome",
        "--args",
        f"--remote-debugging-port={args.port}",
        f"--user-data-dir={args.profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        args.url,
    ]
    subprocess.Popen(cmd)
    print(f"Opened Chrome CDP on http://127.0.0.1:{args.port}")
    print(f"Profile: {args.profile_dir}")
    print("Log in to Douyin Life in that window once, then rerun the task script.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
