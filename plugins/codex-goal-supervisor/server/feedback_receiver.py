#!/usr/bin/env python3
"""Minimal authenticated receiver for Goal Supervisor diagnostic metadata."""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


MAX_BODY_BYTES = 64 * 1024
MAX_REGISTRATION_BYTES = 4 * 1024
MAX_EXPORT_ROWS = 10_000
DEVICE_TOKEN_PREFIX = "gsvd_"
DEVICE_CLIENT_ID = "codex-goal-supervisor"
EVENT_ALLOWED_KEYS = {
    "schema_version", "event_id", "event_fingerprint", "occurred_at",
    "project_fingerprint", "plugin_version", "runtime", "source", "kind",
    "severity", "rule_id", "command", "ticket_id", "status", "message",
    "context", "privacy_mode", "maintainer_action",
}
REGISTRATION_ALLOWED_KEYS = {
    "schema_version", "client", "install_id", "plugin_version", "platform",
}
FORBIDDEN_KEYS = {
    "archive", "attachment", "attachments", "binary", "blob", "content",
    "environment", "file", "file_content", "password", "payload", "prompt",
    "refresh_token", "secret", "source_text", "token", "upload",
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in FORBIDDEN_KEYS or contains_forbidden_key(item):
                return True
    elif isinstance(value, list):
        return any(contains_forbidden_key(item) for item in value)
    return False


def validate_bounded_json(value: Any, *, depth: int = 0) -> bool:
    if depth > 4:
        return False
    if isinstance(value, dict):
        if len(value) > 40:
            return False
        return all(
            len(str(key)) <= 120 and validate_bounded_json(item, depth=depth + 1)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return len(value) <= 40 and all(validate_bounded_json(item, depth=depth + 1) for item in value)
    if isinstance(value, str):
        return len(value) <= 2000
    return isinstance(value, (bool, int, float)) or value is None


def validate_event(value: Any) -> str | None:
    if not isinstance(value, dict):
        return "event_must_be_object"
    if set(value) - EVENT_ALLOWED_KEYS:
        return "unsupported_event_field"
    if value.get("schema_version") != 1:
        return "unsupported_schema_version"
    required = ("event_id", "event_fingerprint", "occurred_at", "project_fingerprint", "kind", "privacy_mode")
    if any(not str(value.get(key) or "").strip() for key in required):
        return "missing_required_field"
    if value.get("privacy_mode") != "governance_metadata_only":
        return "unsupported_privacy_mode"
    if len(str(value.get("event_id"))) > 128 or len(str(value.get("message") or "")) > 2000:
        return "field_too_large"
    if not isinstance(value.get("context", {}), dict) or not isinstance(value.get("runtime", {}), dict):
        return "invalid_metadata_shape"
    if set(value.get("runtime", {})) - {"os", "python"}:
        return "unsupported_runtime_field"
    if contains_forbidden_key(value):
        return "forbidden_payload_key"
    if not validate_bounded_json(value):
        return "payload_shape_too_large"
    return None


def validate_registration(value: Any) -> str | None:
    if not isinstance(value, dict):
        return "registration_must_be_object"
    if set(value) - REGISTRATION_ALLOWED_KEYS:
        return "unsupported_registration_field"
    if value.get("schema_version") != 1 or value.get("client") != DEVICE_CLIENT_ID:
        return "unsupported_registration_client"
    install_id = str(value.get("install_id") or "")
    if not re.fullmatch(r"[A-Za-z0-9-]{16,64}", install_id):
        return "invalid_install_id"
    if any(len(str(value.get(key) or "")) > 160 for key in ("plugin_version", "platform")):
        return "field_too_large"
    return None


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class FeedbackStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    @contextlib.contextmanager
    def session(self):
        connection = self.connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.session() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS feedback_events (
                    event_id TEXT PRIMARY KEY,
                    event_fingerprint TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    project_fingerprint TEXT NOT NULL,
                    plugin_version TEXT,
                    kind TEXT NOT NULL,
                    severity TEXT,
                    status TEXT,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_feedback_received_at
                    ON feedback_events(received_at);
                CREATE INDEX IF NOT EXISTS idx_feedback_kind
                    ON feedback_events(kind);
                CREATE TABLE IF NOT EXISTS feedback_devices (
                    device_id TEXT PRIMARY KEY,
                    token_hash TEXT UNIQUE NOT NULL,
                    install_id_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT,
                    event_count INTEGER NOT NULL DEFAULT 0,
                    revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS feedback_rejections (
                    rejection_id TEXT PRIMARY KEY,
                    received_at TEXT NOT NULL,
                    source_fingerprint TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    body_sha256 TEXT NOT NULL,
                    body_bytes INTEGER NOT NULL,
                    content_type TEXT NOT NULL
                );
                """
            )

    def register_device(self, install_id: str) -> tuple[str, str]:
        device_id = "dev_" + secrets.token_hex(16)
        token = DEVICE_TOKEN_PREFIX + secrets.token_urlsafe(32)
        with self.session() as connection:
            connection.execute(
                """
                INSERT INTO feedback_devices (
                    device_id, token_hash, install_id_hash, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (device_id, token_hash(token), token_hash(install_id), utc_now()),
            )
        return device_id, token

    def authenticate_device(self, token: str) -> str | None:
        digest = token_hash(token)
        with self.session() as connection:
            row = connection.execute(
                "SELECT device_id FROM feedback_devices WHERE token_hash = ? AND revoked = 0",
                (digest,),
            ).fetchone()
        return str(row[0]) if row else None

    def reject(self, *, source_fingerprint: str, reason: str, body: bytes, declared_bytes: int, content_type: str) -> None:
        digest = hashlib.sha256(body).hexdigest()
        with self.session() as connection:
            connection.execute(
                """
                INSERT INTO feedback_rejections (
                    rejection_id, received_at, source_fingerprint, reason,
                    body_sha256, body_bytes, content_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    secrets.token_hex(16), utc_now(), source_fingerprint, reason,
                    digest, max(len(body), declared_bytes), content_type[:160],
                ),
            )

    def insert(self, event: dict[str, Any], *, device_id: str | None = None) -> bool:
        payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with self.session() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO feedback_events (
                    event_id, event_fingerprint, received_at, occurred_at,
                    project_fingerprint, plugin_version, kind, severity, status, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(event["event_id"]), str(event["event_fingerprint"]), utc_now(),
                    str(event["occurred_at"]), str(event["project_fingerprint"]),
                    str(event.get("plugin_version") or ""), str(event["kind"]),
                    str(event.get("severity") or ""), str(event.get("status") or ""), payload,
                ),
            )
            if cursor.rowcount == 1 and device_id:
                connection.execute(
                    """
                    UPDATE feedback_devices
                    SET last_seen_at = ?, event_count = event_count + 1
                    WHERE device_id = ?
                    """,
                    (utc_now(), device_id),
                )
            return cursor.rowcount == 1

    def stats(self) -> dict[str, Any]:
        with self.session() as connection:
            total = int(connection.execute("SELECT COUNT(*) FROM feedback_events").fetchone()[0])
            rows = connection.execute(
                "SELECT kind, COUNT(*) FROM feedback_events GROUP BY kind ORDER BY COUNT(*) DESC, kind"
            ).fetchall()
            latest = connection.execute("SELECT MAX(received_at) FROM feedback_events").fetchone()[0]
            devices = int(connection.execute("SELECT COUNT(*) FROM feedback_devices").fetchone()[0])
            rejections = int(connection.execute("SELECT COUNT(*) FROM feedback_rejections").fetchone()[0])
        return {
            "total": total,
            "by_kind": {str(kind): int(count) for kind, count in rows},
            "latest": latest,
            "devices": devices,
            "rejections": rejections,
        }

    def export(self, limit: int) -> list[str]:
        with self.session() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM feedback_events ORDER BY received_at DESC LIMIT ?",
                (max(1, min(limit, MAX_EXPORT_ROWS)),),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def export_after(
        self,
        *,
        received_at: str = "",
        event_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, str]]:
        bounded_limit = max(1, min(limit, MAX_EXPORT_ROWS))
        with self.session() as connection:
            rows = connection.execute(
                """
                SELECT received_at, event_id, payload_json
                FROM feedback_events
                WHERE received_at > ? OR (received_at = ? AND event_id > ?)
                ORDER BY received_at ASC, event_id ASC
                LIMIT ?
                """,
                (received_at, received_at, event_id, bounded_limit),
            ).fetchall()
        return [
            {
                "server_received_at": str(row[0]),
                "event_id": str(row[1]),
                "payload_json": str(row[2]),
            }
            for row in rows
        ]


class FeedbackServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], store: FeedbackStore, token: str):
        self.store = store
        self.token = token
        super().__init__(address, FeedbackHandler)


class FeedbackHandler(BaseHTTPRequestHandler):
    server: FeedbackServer

    def reply(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def authorized_device(self) -> str | None:
        header = self.headers.get("Authorization", "")
        candidate = header[7:] if header.startswith("Bearer ") else ""
        if not candidate:
            return None
        if hmac.compare_digest(candidate, self.server.token):
            return "master"
        return self.server.store.authenticate_device(candidate)

    def source_fingerprint(self) -> str:
        address = str(self.client_address[0] if self.client_address else "unknown")
        return hmac.new(self.server.token.encode("utf-8"), address.encode("utf-8"), hashlib.sha256).hexdigest()[:24]

    def reject(self, status: int, reason: str, body: bytes = b"", declared_bytes: int = 0) -> None:
        self.server.store.reject(
            source_fingerprint=self.source_fingerprint(),
            reason=reason,
            body=body,
            declared_bytes=declared_bytes,
            content_type=str(self.headers.get("Content-Type") or ""),
        )
        self.reply(status, {"ok": False, "error": reason})

    def read_json_body(self, max_bytes: int) -> tuple[Any | None, bytes, str | None]:
        content_type = str(self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            return None, b"", "unsupported_content_type"
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > max_bytes:
            return None, b"", "invalid_body_size"
        body = self.rfile.read(length)
        try:
            return json.loads(body.decode("utf-8")), body, None
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, body, "invalid_json"

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback
        if self.path == "/healthz":
            self.reply(200, {"ok": True})
        else:
            self.reply(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback
        if self.path == "/v1/devices/register":
            registration, body, error = self.read_json_body(MAX_REGISTRATION_BYTES)
            if error:
                declared = int(self.headers.get("Content-Length", "0") or 0) if str(self.headers.get("Content-Length", "0")).isdigit() else 0
                self.reject(415 if error == "unsupported_content_type" else 413 if error == "invalid_body_size" else 400, error, body, declared)
                return
            error = validate_registration(registration)
            if error:
                self.reject(422, error, body, len(body))
                return
            device_id, token = self.server.store.register_device(str(registration["install_id"]))
            self.reply(201, {
                "ok": True,
                "device_id": device_id,
                "token": token,
                "token_type": "Bearer",
                "endpoint": "/v1/events",
            })
            return
        if self.path != "/v1/events":
            self.reply(404, {"ok": False, "error": "not_found"})
            return
        device_id = self.authorized_device()
        if not device_id:
            self.reply(401, {"ok": False, "error": "unauthorized"})
            return
        event, body, error = self.read_json_body(MAX_BODY_BYTES)
        if error:
            declared = int(self.headers.get("Content-Length", "0") or 0) if str(self.headers.get("Content-Length", "0")).isdigit() else 0
            self.reject(415 if error == "unsupported_content_type" else 413 if error == "invalid_body_size" else 400, error, body, declared)
            return
        error = validate_event(event)
        if error:
            self.reject(422, error, body, len(body))
            return
        inserted = self.server.store.insert(event, device_id=None if device_id == "master" else device_id)
        self.reply(202 if inserted else 200, {"ok": True, "accepted": inserted, "duplicate": not inserted})

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def command_serve(args: argparse.Namespace) -> int:
    token = os.environ.get(args.token_env, "").strip()
    if len(token) < 32:
        print(f"{args.token_env} must contain at least 32 characters", file=sys.stderr)
        return 2
    server = FeedbackServer((args.bind, args.port), FeedbackStore(args.db), token)
    print(json.dumps({"status": "LISTENING", "bind": args.bind, "port": server.server_port, "db": str(args.db)}))
    server.serve_forever(poll_interval=0.25)
    return 0


def command_stats(args: argparse.Namespace) -> int:
    print(json.dumps(FeedbackStore(args.db).stats(), ensure_ascii=False))
    return 0


def command_export(args: argparse.Namespace) -> int:
    if args.with_receipt or args.after_received_at or args.after_event_id:
        rows = FeedbackStore(args.db).export_after(
            received_at=args.after_received_at,
            event_id=args.after_event_id,
            limit=args.limit,
        )
        for row in rows:
            print(json.dumps({
                "server_received_at": row["server_received_at"],
                "event_id": row["event_id"],
                "event": json.loads(row["payload_json"]),
            }, ensure_ascii=False, separators=(",", ":")))
        return 0
    for row in FeedbackStore(args.db).export(args.limit):
        print(row)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--bind", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8766)
    serve.add_argument("--db", type=Path, required=True)
    serve.add_argument("--token-env", default="GOAL_SUPERVISOR_FEEDBACK_TOKEN")
    serve.set_defaults(func=command_serve)
    stats = sub.add_parser("stats")
    stats.add_argument("--db", type=Path, required=True)
    stats.set_defaults(func=command_stats)
    export = sub.add_parser("export")
    export.add_argument("--db", type=Path, required=True)
    export.add_argument("--limit", type=int, default=100)
    export.add_argument("--with-receipt", action="store_true")
    export.add_argument("--after-received-at", default="")
    export.add_argument("--after-event-id", default="")
    export.set_defaults(func=command_export)
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
