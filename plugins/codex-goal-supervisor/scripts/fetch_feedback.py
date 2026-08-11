#!/usr/bin/env python3
"""Fetch new Goal Supervisor feedback records over the maintainer SSH channel."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_REMOTE_ROOT = "/home/ubuntu/workspaces/goal-supervisor-feedback"


def load_cursor(path: Path) -> dict[str, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"server_received_at": "", "event_id": ""}
    if not isinstance(value, dict):
        return {"server_received_at": "", "event_id": ""}
    return {
        "server_received_at": str(value.get("server_received_at") or ""),
        "event_id": str(value.get("event_id") or ""),
    }


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def fetch_page(
    *,
    remote: str,
    remote_root: str,
    cursor: dict[str, str],
    limit: int,
    timeout: float,
) -> list[dict[str, Any]]:
    remote_command = [
        "python3",
        f"{remote_root}/app/feedback_receiver.py",
        "export",
        "--db",
        f"{remote_root}/data/events.sqlite3",
        "--limit",
        str(limit),
        "--with-receipt",
    ]
    if cursor["server_received_at"]:
        remote_command.extend([
            "--after-received-at",
            cursor["server_received_at"],
            "--after-event-id",
            cursor["event_id"],
        ])
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", remote, shlex.join(remote_command)],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"ssh exited {result.returncode}")
    records: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if not isinstance(record, dict) or not record.get("server_received_at") or not record.get("event_id"):
            raise ValueError("server returned an invalid feedback receipt")
        records.append(record)
    return records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote", default=os.environ.get("GOAL_SUPERVISOR_FEEDBACK_REMOTE"))
    parser.add_argument("--remote-root", default=DEFAULT_REMOTE_ROOT)
    parser.add_argument("--cursor", type=Path, default=Path.home() / ".codex" / "goal-supervisor-feedback-cursor.json")
    parser.add_argument("--output-dir", type=Path, default=Path.cwd() / "feedback-inbox")
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    if not args.remote:
        parser.error("--remote or GOAL_SUPERVISOR_FEEDBACK_REMOTE is required")

    page_size = max(1, min(args.page_size, 5000))
    max_pages = max(1, min(args.max_pages, 100))
    cursor = load_cursor(args.cursor.expanduser())
    records: list[dict[str, Any]] = []
    for _ in range(max_pages):
        page = fetch_page(
            remote=args.remote,
            remote_root=args.remote_root.rstrip("/"),
            cursor=cursor,
            limit=page_size,
            timeout=max(2.0, min(args.timeout, 120.0)),
        )
        if not page:
            break
        records.extend(page)
        last = page[-1]
        cursor = {
            "server_received_at": str(last["server_received_at"]),
            "event_id": str(last["event_id"]),
        }
        if len(page) < page_size:
            break

    output_path: Path | None = None
    if records:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_path = args.output_dir.expanduser() / f"goal-supervisor-feedback-{stamp}.jsonl"
        atomic_write(
            output_path,
            "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records),
        )
        atomic_write(args.cursor.expanduser(), json.dumps(cursor, ensure_ascii=False, indent=2) + "\n")

    print(json.dumps({
        "downloaded": len(records),
        "output": str(output_path) if output_path else None,
        "cursor": cursor,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"downloaded": 0, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
