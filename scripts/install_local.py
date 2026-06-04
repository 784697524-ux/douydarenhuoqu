#!/usr/bin/env python3
"""Install the local command wrapper for this skill."""

from __future__ import annotations

import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BIN_DIR = Path.home() / ".local" / "bin"
TARGET = BIN_DIR / "douyin-talent-contact"
SOURCE = SCRIPT_DIR / "douyin-talent-contact"


def main() -> int:
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    if TARGET.exists() or TARGET.is_symlink():
        TARGET.unlink()
    TARGET.symlink_to(SOURCE)
    print(f"Installed: {TARGET}")
    if str(BIN_DIR) not in os.environ.get("PATH", ""):
        print(f"Add to PATH if needed: export PATH=\"{BIN_DIR}:$PATH\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
