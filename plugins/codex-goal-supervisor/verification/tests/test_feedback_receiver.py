from __future__ import annotations

import contextlib
import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import sqlite3
from pathlib import Path
from unittest import mock


PLUGIN_ROOT = Path(__file__).resolve().parents[2]
RECEIVER_PATH = PLUGIN_ROOT / "server" / "feedback_receiver.py"
SPEC = importlib.util.spec_from_file_location("goal_supervisor_feedback_receiver", RECEIVER_PATH)
assert SPEC and SPEC.loader
RECEIVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECEIVER)


def event(event_id: str = "event-1") -> dict:
    return {
        "schema_version": 1,
        "event_id": event_id,
        "event_fingerprint": "f" * 64,
        "occurred_at": "2026-08-02T00:00:00+00:00",
        "project_fingerprint": "p" * 24,
        "plugin_version": "2.0.0-test",
        "source": "hook",
        "kind": "false_positive",
        "severity": "warning",
        "status": "RUNTIME_FAILURE",
        "message": "plugin rejected a valid edit",
        "context": {"rule_id": "TEST"},
        "privacy_mode": "governance_metadata_only",
    }


class FeedbackReceiverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="goal-feedback-receiver-")
        self.db = Path(self.temp.name) / "events.sqlite3"
        self.token = "receiver-token-" + "x" * 48
        self.server = RECEIVER.FeedbackServer(
            ("127.0.0.1", 0), RECEIVER.FeedbackStore(self.db), self.token,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1/events"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def post(self, payload: dict, token: str | None = None) -> tuple[int, dict]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def register(self, payload: dict | None = None) -> tuple[int, dict]:
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_port}/v1/devices/register",
            data=json.dumps(payload or {
                "schema_version": 1,
                "client": "codex-goal-supervisor",
                "install_id": "0123456789abcdef0123456789abcdef",
                "plugin_version": "2.3.0-test",
                "platform": "TestOS",
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_requires_bearer_and_deduplicates_event_id(self) -> None:
        status, _ = self.post(event())
        self.assertEqual(status, 401)
        first_status, first = self.post(event(), self.token)
        second_status, second = self.post(event(), self.token)
        self.assertEqual(first_status, 202)
        self.assertTrue(first["accepted"])
        self.assertEqual(second_status, 200)
        self.assertTrue(second["duplicate"])
        self.assertEqual(RECEIVER.FeedbackStore(self.db).stats()["total"], 1)

    def test_auto_registration_issues_unique_device_token_and_stores_only_hash(self) -> None:
        status, registration = self.register()
        self.assertEqual(status, 201)
        self.assertTrue(registration["token"].startswith("gsvd_"))
        event_status, result = self.post(event("device-event"), registration["token"])
        self.assertEqual(event_status, 202)
        self.assertTrue(result["accepted"])
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            token_value, event_count = connection.execute(
                "SELECT token_hash, event_count FROM feedback_devices WHERE device_id = ?",
                (registration["device_id"],),
            ).fetchone()
        self.assertEqual(token_value, RECEIVER.token_hash(registration["token"]))
        self.assertNotEqual(token_value, registration["token"])
        self.assertEqual(event_count, 1)

    def test_rejects_payload_keys_that_could_contain_project_data(self) -> None:
        payload = event("event-sensitive")
        payload["context"]["prompt"] = "sensitive project prompt"
        status, result = self.post(payload, self.token)
        self.assertEqual(status, 422)
        self.assertEqual(result["error"], "forbidden_payload_key")
        self.assertEqual(RECEIVER.FeedbackStore(self.db).stats()["total"], 0)

    def test_rejects_attachment_fields_and_quarantines_metadata_only(self) -> None:
        payload = event("event-attachment")
        payload["attachment"] = "encoded executable body"
        status, result = self.post(payload, self.token)
        self.assertEqual(status, 422)
        self.assertEqual(result["error"], "unsupported_event_field")
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            row = connection.execute(
                "SELECT reason, body_sha256, body_bytes, content_type FROM feedback_rejections"
            ).fetchone()
            columns = [item[1] for item in connection.execute("PRAGMA table_info(feedback_rejections)")]
        self.assertEqual(row[0], "unsupported_event_field")
        self.assertEqual(len(row[1]), 64)
        self.assertGreater(row[2], 0)
        self.assertNotIn("body", columns)
        self.assertNotIn("payload", columns)

    def test_rejects_multipart_and_has_no_manual_upload_route(self) -> None:
        multipart = urllib.request.Request(
            self.url,
            data=b"MZ-not-a-real-file",
            headers={
                "Content-Type": "multipart/form-data; boundary=test",
                "Authorization": "Bearer " + self.token,
            },
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(multipart, timeout=2)
        self.assertEqual(error.exception.code, 415)
        manual = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_port}/upload",
            data=b"anything",
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(manual, timeout=2)
        self.assertEqual(missing.exception.code, 404)

    def test_registration_rejects_non_plugin_clients(self) -> None:
        status, result = self.register({
            "schema_version": 1,
            "client": "arbitrary-uploader",
            "install_id": "0123456789abcdef0123456789abcdef",
            "plugin_version": "1",
            "platform": "TestOS",
        })
        self.assertEqual(status, 422)
        self.assertEqual(result["error"], "unsupported_registration_client")

    def test_health_is_local_and_does_not_expose_event_data(self) -> None:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.server.server_port}/healthz", timeout=2,
        ) as response:
            payload = json.loads(response.read())
        self.assertEqual(payload, {"ok": True})

    def test_incremental_export_cursor_does_not_skip_same_second_events(self) -> None:
        store = RECEIVER.FeedbackStore(self.db)
        with mock.patch.object(RECEIVER, "utc_now", return_value="2026-08-02T12:00:00+00:00"):
            self.assertTrue(store.insert(event("event-a")))
            self.assertTrue(store.insert(event("event-b")))
        first_page = store.export_after(limit=1)
        self.assertEqual([row["event_id"] for row in first_page], ["event-a"])
        second_page = store.export_after(
            received_at=first_page[0]["server_received_at"],
            event_id=first_page[0]["event_id"],
            limit=10,
        )
        self.assertEqual([row["event_id"] for row in second_page], ["event-b"])

    def test_server_side_github_mirror_batches_sanitized_events(self) -> None:
        store = RECEIVER.FeedbackStore(self.db)
        self.assertTrue(store.insert(event("github-event-a")))
        self.assertTrue(store.insert(event("github-event-b")))
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "html_url": "https://github.com/example/private-feedback/issues/17"
        }).encode("utf-8")
        with mock.patch.object(RECEIVER.urllib.request, "urlopen", return_value=response) as opened:
            result = RECEIVER.github_issue_batch(
                store,
                repository="example/private-feedback",
                token="server-only-token-" + "x" * 32,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["mirrored"], 2)
        request = opened.call_args.args[0]
        self.assertTrue(request.get_header("Authorization").startswith("Bearer server-only-token-"))
        self.assertEqual(store.github_pending(), [])
        self.assertEqual(store.stats()["total"], 2)

    def test_github_mirror_failure_retains_local_events_for_retry(self) -> None:
        store = RECEIVER.FeedbackStore(self.db)
        self.assertTrue(store.insert(event("github-event-failed")))
        with mock.patch.object(
            RECEIVER.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            result = RECEIVER.github_issue_batch(
                store,
                repository="example/private-feedback",
                token="server-only-token-" + "x" * 32,
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "MIRROR_FAILED_RETAINED_LOCALLY")
        self.assertTrue(result["retained_locally"])
        self.assertEqual([row["event_id"] for row in store.github_pending()], ["github-event-failed"])
        self.assertEqual(store.stats()["total"], 1)

    def test_client_feedback_transport_contains_no_github_write_credential(self) -> None:
        client_sources = [
            PLUGIN_ROOT / "assets/governor-harness/.agent/goal_compass_runtime/feedback.py",
            PLUGIN_ROOT / "scripts/configure_feedback_client.py",
        ]
        for path in client_sources:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("GOAL_SUPERVISOR_GITHUB_TOKEN", text)
            self.assertNotIn("github_pat_", text)
            self.assertNotIn("BEGIN PRIVATE KEY", text)


if __name__ == "__main__":
    unittest.main()
