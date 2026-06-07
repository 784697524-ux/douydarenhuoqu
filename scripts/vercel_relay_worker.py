#!/usr/bin/env python3
"""Poll the Vercel relay and execute Douyin talent tasks on this local machine."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

RUNNER = Path(__file__).resolve().parent / "run_talent_task.py"


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "是"}


def request_json(method: str, url: str, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def apply_proxy(proxy: str) -> None:
    if not proxy:
        return
    os.environ.setdefault("HTTP_PROXY", proxy)
    os.environ.setdefault("HTTPS_PROXY", proxy)


def macos_https_proxy() -> str:
    try:
        output = subprocess.check_output(["scutil", "--proxy"], text=True, timeout=3)
    except Exception:
        return ""
    values: dict[str, str] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    if values.get("HTTPSEnable") != "1":
        return ""
    host = values.get("HTTPSProxy", "")
    port = values.get("HTTPSPort", "")
    return f"http://{host}:{port}" if host and port else ""


def task_command(payload: dict[str, Any]) -> list[str]:
    task_id = str(payload.get("task_id") or payload.get("任务编号") or payload.get("任务ID") or "").strip()
    if not task_id:
        raise ValueError("missing task_id")
    cmd = [sys.executable, str(RUNNER), "--task-id", task_id]
    cmd.extend(["--wait-ready", str(payload.get("wait_ready") or os.environ.get("DOUYIN_WAIT_READY", "60"))])
    cmd.extend(["--reserve-quota", str(payload.get("reserve_quota", os.environ.get("DOUYIN_RESERVE_QUOTA", "0")))])
    if parse_bool(payload.get("smoke")):
        cmd.extend(["--no-contact", "--no-commit", "--no-status-write"])
    return cmd


def run_task(payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    proc = subprocess.run(task_command(payload), text=True, capture_output=True, timeout=timeout, check=False)
    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    try:
        result = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError:
        result = {"raw_stdout": stdout}
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "result": result,
        "stderr": stderr[-4000:],
    }


def handle_once(relay_url: str, token: str, timeout: int) -> dict[str, Any]:
    next_url = relay_url.rstrip("/") + "/api/next"
    complete_url = relay_url.rstrip("/") + "/api/complete"
    response = request_json("GET", next_url, token)
    job = response.get("job")
    if not job:
        return {"ok": True, "status": "idle"}

    job_id = job["id"]
    payload = job.get("payload") or {}
    try:
        result = run_task(payload, timeout)
        complete_payload = {"job_id": job_id, "ok": result["ok"], "result": result}
        if not result["ok"]:
            complete_payload["error"] = result.get("stderr") or "douyin-task failed"
    except Exception as exc:
        complete_payload = {"job_id": job_id, "ok": False, "error": str(exc), "result": {}}
    complete_response = request_json("POST", complete_url, token, complete_payload)
    return {"ok": complete_response.get("ok", False), "job_id": job_id, "complete": complete_response}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--relay-url", default=os.environ.get("DOUYIN_RELAY_URL", ""))
    parser.add_argument("--worker-token", default=os.environ.get("DOUYIN_RELAY_WORKER_TOKEN", ""))
    parser.add_argument("--interval", type=float, default=float(os.environ.get("DOUYIN_RELAY_POLL_INTERVAL", "10")))
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("DOUYIN_RELAY_TASK_TIMEOUT", "900")))
    parser.add_argument("--proxy", default=os.environ.get("DOUYIN_RELAY_PROXY", ""))
    parser.add_argument("--no-system-proxy", action="store_true")
    parser.add_argument("--once", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.relay_url:
        print("error: missing --relay-url or DOUYIN_RELAY_URL", file=sys.stderr)
        return 2
    if not args.worker_token:
        print("error: missing --worker-token or DOUYIN_RELAY_WORKER_TOKEN", file=sys.stderr)
        return 2
    if args.proxy:
        apply_proxy(args.proxy)
    elif not args.no_system_proxy:
        apply_proxy(macos_https_proxy())

    while True:
        try:
            result = handle_once(args.relay_url, args.worker_token, args.timeout)
            print(json.dumps(result, ensure_ascii=False), flush=True)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            print(json.dumps({"ok": False, "error": f"HTTP {exc.code}: {body}"}, ensure_ascii=False), flush=True)
        except Exception as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), flush=True)
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
