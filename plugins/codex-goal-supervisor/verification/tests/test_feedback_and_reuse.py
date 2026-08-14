from __future__ import annotations

import contextlib
import http.server
import io
import json
import os
import threading
from pathlib import Path
from unittest import mock

try:
    from .helpers import GOAL_COMPASS, GoalCompassRepoCase, pushd
except ImportError:
    from helpers import GOAL_COMPASS, GoalCompassRepoCase, pushd

from goal_compass_runtime import feedback as feedback_runtime


def github_fixture(*, release: str = "v1.0.0", pushed_at: str = "2026-01-01T00:00:00Z") -> dict:
    return {
        "total_count": 1,
        "incomplete_results": False,
        "items": [
            {
                "full_name": "example/open-video-generator",
                "html_url": "https://github.com/example/open-video-generator",
                "description": "Automatic video generation pipeline from prompt to artifact.",
                "stargazers_count": 1200,
                "language": "Python",
                "license": {"spdx_id": "MIT"},
                "archived": False,
                "topics": ["video-generation", "prompt", "artifact"],
                "pushed_at": pushed_at,
                "updated_at": pushed_at,
                "latest_release": release,
            }
        ],
    }


@contextlib.contextmanager
def running_http_server(handler: type[http.server.BaseHTTPRequestHandler]):
    """Bounded local server fixture; BaseServer.shutdown can wait forever."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server.timeout = 0.1
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            server.handle_request()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        stop.set()
        thread.join(timeout=2)
        server.server_close()
        if thread.is_alive():
            raise AssertionError("local feedback test server did not stop within 2 seconds")


class FeedbackAndReuseTests(GoalCompassRepoCase):
    def write_reuse_fixture(self, data: dict) -> Path:
        path = self.root / "reuse-search.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def test_init_writes_feedback_and_reuse_configuration(self) -> None:
        feedback = self.read_json(".agent/feedback_config.json")
        reuse = self.read_json(".agent/reuse_probe_config.json")
        self.assertTrue(feedback["capture_enabled"])
        self.assertEqual(feedback["schema_version"], 2)
        self.assertEqual(feedback["deployment_context"], "unknown")
        self.assertFalse(feedback["upload_enabled"])
        self.assertEqual(feedback["delivery"], "local_outbox_only")
        self.assertEqual(feedback["privacy_mode"], "governance_metadata_only")
        self.assertTrue(self.json_run("status", "--verbose")["feedback"]["privacy_choice_required"])
        self.assertTrue(reuse["required_before_mutation"])
        self.assertEqual(reuse["refresh_interval_hours"], 24)

    def test_feedback_config_help_does_not_ask_users_for_endpoint_or_token(self) -> None:
        result = self.cli("feedback-config", "--help")
        self.assertNotIn("--endpoint", result.stdout)
        self.assertNotIn("--token-env", result.stdout)
        self.assertNotIn("--timeout", result.stdout)

    def test_privacy_choice_is_requested_only_until_project_context_is_recorded(self) -> None:
        before = self.json_run("status", "--verbose")["feedback"]
        self.assertTrue(before["privacy_choice_required"])
        self.cli("feedback-config", "--context", "enterprise", "--deny-upload")
        after = self.json_run("status", "--verbose")["feedback"]
        self.assertFalse(after["privacy_choice_required"])
        self.assertEqual(after["deployment_context"], "enterprise")
        self.assertFalse(after["upload_authorized"])

    def test_endpoint_environment_cannot_bypass_upload_consent(self) -> None:
        with mock.patch.dict(os.environ, {"GOAL_COMPASS_FEEDBACK_URL": "https://feedback.invalid/events"}):
            with mock.patch.object(feedback_runtime, "_post") as post, mock.patch.object(feedback_runtime, "_open_request") as open_request:
                result = self.json_run(
                    "feedback",
                    "--kind", "false_positive",
                    "--message", "plugin blocked a valid edit",
                    "--expected-behavior", "allow it",
                )
                status = self.json_run("status", "--verbose")["feedback"]
        post.assert_not_called()
        open_request.assert_not_called()
        self.assertEqual(result["delivery"]["status"], "LOCAL_ONLY")
        self.assertEqual(result["delivery"]["pending"], 1)
        self.assertFalse(status["upload_authorized"])
        self.assertTrue(status["remote_configured"])
        self.assertEqual(status["delivery_mode"], "local_outbox_only")

    def test_v1_endpoint_config_migrates_to_local_only(self) -> None:
        self.write_json(".agent/feedback_config.json", {
            "schema_version": 1,
            "capture_enabled": True,
            "endpoint": "https://feedback.invalid/events",
            "project_id": "legacy-project",
            "delivery": "realtime_with_durable_outbox",
        })
        status = self.json_run("status", "--verbose")["feedback"]
        config = self.read_json(".agent/feedback_config.json")
        self.assertEqual(config["schema_version"], 2)
        self.assertFalse(config["upload_enabled"])
        self.assertIsNone(config["upload_consent_at"])
        self.assertEqual(config["delivery"], "local_outbox_only")
        self.assertFalse(status["upload_authorized"])

    def test_policy_block_is_durably_queued_when_server_is_unconfigured(self) -> None:
        self.start_video()
        output = io.StringIO()
        with pushd(self.root), contextlib.redirect_stdout(output):
            GOAL_COMPASS.hook_out("PreToolUse", deny="Goal Compass forbids editing: .agent/current_ticket.json")
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["hookSpecificOutput"]["permissionDecision"], "deny")
        events = list((self.root / ".agent/runtime/feedback-outbox").glob("*.json"))
        self.assertEqual(len(events), 1)
        event = json.loads(events[0].read_text(encoding="utf-8"))
        self.assertEqual(event["kind"], "policy_block")
        self.assertEqual(event["maintainer_action"], "OPEN_REPRODUCTION_AND_REPAIR_TICKET")

    def test_unhandled_plugin_runtime_error_is_captured(self) -> None:
        with mock.patch.object(GOAL_COMPASS, "cmd_status", side_effect=RuntimeError("synthetic runtime failure")):
            result = self.cli("status", check=False)
        self.assertEqual(result.returncode, 3)
        self.assertIn("PLUGIN_RUNTIME_ERROR", result.stderr)
        events = list((self.root / ".agent/runtime/feedback-outbox").glob("*.json"))
        self.assertEqual(len(events), 1)
        event = json.loads(events[0].read_text(encoding="utf-8"))
        self.assertEqual(event["kind"], "plugin_runtime_error")
        self.assertEqual(event["status"], "RUNTIME_FAILURE")

    def test_feedback_is_sent_immediately_and_secrets_are_redacted(self) -> None:
        received: list[dict] = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
                length = int(self.headers.get("Content-Length", "0"))
                received.append(json.loads(self.rfile.read(length).decode("utf-8")))
                self.send_response(202)
                self.end_headers()

            def log_message(self, *_args) -> None:
                return

        with running_http_server(Handler) as server:
            endpoint = f"http://127.0.0.1:{server.server_port}/goal-compass-feedback"
            with mock.patch.dict(os.environ, {"GOAL_COMPASS_FEEDBACK_TOKEN": "t" * 64}):
                self.cli(
                    "feedback-config",
                    "--endpoint", endpoint,
                    "--context", "personal",
                    "--enable",
                    "--allow-upload",
                    "--confirm-upload",
                )
                result = self.json_run(
                    "feedback",
                    "--kind", "false_positive",
                    "--message", f"token=secret-value path={Path.home()}/private plugin blocked a valid edit",
                    "--expected-behavior", "allow the exact writable path",
                )
            self.assertTrue(result["captured"])
            self.assertTrue(result["uploaded"])
            self.assertEqual(result["delivery"]["pending"], 0, (result, received))
        self.assertEqual(len(received), 1)
        encoded = json.dumps(received[0], ensure_ascii=False)
        self.assertIn("[REDACTED]", encoded)
        self.assertIn("<HOME>", encoded)
        self.assertNotIn("secret-value", encoded)
        self.assertNotIn(str(Path.home()), encoded)
        self.assertNotIn("prompt", received[0])

    def test_user_level_endpoint_and_token_file_still_require_project_consent(self) -> None:
        received: list[dict] = []
        authorization: list[str] = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
                authorization.append(self.headers.get("Authorization", ""))
                length = int(self.headers.get("Content-Length", "0"))
                received.append(json.loads(self.rfile.read(length).decode("utf-8")))
                self.send_response(202)
                self.end_headers()

            def log_message(self, *_args) -> None:
                return

        shared = self.root / "shared-feedback.json"
        token_file = self.root / "feedback.token"
        token_file.write_text("t" * 64, encoding="utf-8")
        token_file.chmod(0o600)
        with running_http_server(Handler) as server:
            shared.write_text(json.dumps({
                "endpoint": f"http://127.0.0.1:{server.server_port}/v1/events",
                "token_file": str(token_file),
            }), encoding="utf-8")
            with mock.patch.dict(os.environ, {"GOAL_COMPASS_FEEDBACK_GLOBAL_CONFIG": str(shared)}):
                local_only = self.json_run(
                    "feedback", "--kind", "false_positive", "--message", "local until consent",
                )
                self.assertEqual(local_only["delivery"]["status"], "LOCAL_ONLY")
                self.assertEqual(received, [])
                self.cli(
                    "feedback-config", "--context", "personal",
                    "--allow-upload", "--confirm-upload",
                )
                delivered = self.json_run(
                    "feedback", "--kind", "false_positive", "--message", "authorized event",
                )
                self.assertEqual(delivered["delivery"]["pending"], 0)
        self.assertEqual(len(received), 2)
        self.assertTrue(all(value == "Bearer " + "t" * 64 for value in authorization))

    def test_upload_consent_can_be_revoked_without_losing_outbox(self) -> None:
        configured = self.json_run(
            "feedback-config",
            "--context", "enterprise",
            "--allow-upload",
            "--confirm-upload",
            check=False,
        )
        self.assertFalse(configured["ok"])
        self.assertFalse(configured["upload_ready"])
        self.assertEqual(configured["required_action"], "retry_automatic_device_registration")
        captured_result = self.cli(
            "feedback",
            "--kind", "workflow_friction",
            "--message", "local pending event",
            check=False,
        )
        self.assertNotEqual(captured_result.returncode, 0)
        captured = json.loads(captured_result.stdout)
        self.assertEqual(captured["delivery"]["status"], "AUTHORIZED_UNCONFIGURED")
        self.assertTrue(captured["queued_locally"])
        self.assertFalse(captured["uploaded"])
        self.cli("feedback-config", "--deny-upload")
        flushed = self.json_run("feedback", "--flush")
        self.assertTrue(flushed["ok"])
        self.assertEqual(flushed["delivery"]["status"], "LOCAL_ONLY")
        self.assertEqual(flushed["delivery"]["pending"], 1)
        self.assertEqual(len(list((self.root / ".agent/runtime/feedback-outbox").glob("*.json"))), 1)

    def test_explicit_consent_auto_registers_device_without_manual_token(self) -> None:
        requests: list[tuple[str, str]] = []
        issued_token = "gsvd_" + "x" * 48

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                requests.append((self.path, self.headers.get("Authorization", "")))
                if self.path == "/v1/devices/register":
                    if body.get("client") != "codex-goal-supervisor":
                        self.send_response(422)
                        self.end_headers()
                        return
                    response = json.dumps({
                        "ok": True,
                        "device_id": "dev_test",
                        "token": issued_token,
                        "token_type": "Bearer",
                        "endpoint": "/v1/events",
                    }).encode("utf-8")
                    self.send_response(201)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(response)))
                    self.end_headers()
                    self.wfile.write(response)
                    return
                if self.path == "/v1/events" and self.headers.get("Authorization") == "Bearer " + issued_token:
                    self.send_response(202)
                    self.end_headers()
                    return
                self.send_response(401)
                self.end_headers()

            def log_message(self, *_args) -> None:
                return

        with running_http_server(Handler) as server:
            endpoint = f"http://127.0.0.1:{server.server_port}/v1/events"
            configured = self.json_run(
                "feedback-config", "--endpoint", endpoint, "--context", "personal",
                "--allow-upload", "--confirm-upload",
            )
            result = self.json_run(
                "feedback", "--kind", "false_positive", "--message", "automatic device delivery",
            )
        self.assertTrue(configured["ok"])
        self.assertTrue(configured["upload_ready"])
        self.assertTrue(result["uploaded"])
        self.assertEqual([path for path, _ in requests], ["/v1/devices/register", "/v1/events"])
        self.assertEqual(requests[0][1], "")
        self.assertEqual(requests[1][1], "Bearer " + issued_token)
        global_config = self.root / "no-global-feedback-config.json"
        token_file = self.root / "goal-supervisor-feedback.token"
        self.assertTrue(global_config.is_file())
        self.assertTrue(token_file.is_file())
        self.assertNotIn(issued_token, global_config.read_text(encoding="utf-8"))
        self.assertEqual(token_file.read_text(encoding="utf-8").strip(), issued_token)
        if os.name != "nt":
            self.assertEqual(global_config.stat().st_mode & 0o777, 0o600)
            self.assertEqual(token_file.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(issued_token, json.dumps(configured))

    def test_automatic_registration_failure_is_queued_without_asking_for_token(self) -> None:
        shared = self.root / "shared-feedback.json"
        shared.write_text(json.dumps({
            "endpoint": "http://127.0.0.1:1/v1/events",
            "token_file": str(self.root / "missing-feedback.token"),
        }), encoding="utf-8")
        with mock.patch.dict(os.environ, {"GOAL_COMPASS_FEEDBACK_GLOBAL_CONFIG": str(shared)}):
            configured = self.json_run(
                "feedback-config", "--context", "personal",
                "--allow-upload", "--confirm-upload",
                check=False,
            )
            self.assertFalse(configured["ok"])
            self.assertTrue(configured["remote_configured"])
            self.assertFalse(configured["credentials_configured"])
            self.assertFalse(configured["upload_ready"])
            self.assertEqual(configured["required_action"], "retry_automatic_device_registration")
            self.assertEqual(configured["delivery"]["status"], "AUTHORIZED_DEVICE_REGISTRATION_FAILED")
            result = self.cli(
                "feedback", "--kind", "other", "--message", "synthetic cross-device probe",
                check=False,
            )
            status = self.json_run("status", "--verbose")["feedback"]
        payload = json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["uploaded"])
        self.assertTrue(payload["queued_locally"])
        self.assertEqual(payload["delivery"]["status"], "COOLDOWN")
        self.assertTrue(str(payload["delivery"]["last_error"]).startswith("registration_"))
        self.assertEqual(status["delivery_status"], "AUTHORIZED_DEVICE_REGISTRATION_FAILED")
        self.assertNotIn("token", str(configured.get("required_action", "")).lower())

    def test_direct_reuse_candidate_blocks_custom_build_until_disposition(self) -> None:
        fixture = self.write_reuse_fixture(github_fixture())
        with mock.patch.dict(os.environ, {"GOAL_COMPASS_REUSE_PROBE_FIXTURE": str(fixture)}):
            self.goal_video()
            blocked = self.cli("start", ".agent/tickets/examples/VIDEO-MOCK-001.json", check=False)
            self.assertEqual(blocked.returncode, 2)
            blocked_payload = json.loads(blocked.stdout)
            self.assertTrue(any("direct reuse candidate" in value for value in blocked_payload["errors"]))
            self.assertEqual(blocked_payload["reuse"]["direct_reuse_candidate_count"], 1)

            decided = self.cli(
                "reuse-check",
                "--ticket", ".agent/tickets/examples/VIDEO-MOCK-001.json",
                "--decision", "REJECT_WITH_EVIDENCE",
                "--rationale", "The candidate license is usable, but its artifact contract is incompatible with the frozen local test.",
            )
            self.assertEqual(decided.returncode, 0)
            started = self.cli("start", ".agent/tickets/examples/VIDEO-MOCK-001.json")
            self.assertEqual(started.returncode, 0)

    def test_generic_quality_words_do_not_create_blocking_reuse_candidate(self) -> None:
        fixture = self.write_reuse_fixture({
            "total_count": 1,
            "incomplete_results": False,
            "items": [{
                "full_name": "example/unrelated-maintenance-tool",
                "html_url": "https://github.com/example/unrelated-maintenance-tool",
                "description": "Deliver reliable product maintenance workflow tooling.",
                "stargazers_count": 900,
                "language": "Python",
                "license": {"spdx_id": "MIT"},
                "archived": False,
                "topics": ["maintenance", "workflow"],
                "pushed_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "latest_release": "v1.0.0",
            }],
        })
        with mock.patch.dict(os.environ, {"GOAL_COMPASS_REUSE_PROBE_FIXTURE": str(fixture)}):
            result = self.cli(
                "reuse-check",
                "--task", "Deliver a reliable product maintenance workflow.",
                check=False,
            )

        payload = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(payload["reuse"]["direct_reuse_candidate_count"], 0)
        self.assertEqual(payload["candidates"][0]["reuse_fit"], "REFERENCE_CANDIDATE")

    def test_twenty_four_hour_refresh_detects_updates_to_previously_seen_candidate(self) -> None:
        fixture = self.write_reuse_fixture(github_fixture(release="v1.0.0", pushed_at="2026-01-01T00:00:00Z"))
        task = "Build an automatic video generation pipeline from prompt to artifact."
        with mock.patch.dict(os.environ, {"GOAL_COMPASS_REUSE_PROBE_FIXTURE": str(fixture)}):
            first = self.cli(
                "reuse-check", "--task", task,
                "--decision", "REJECT_WITH_EVIDENCE",
                "--rationale", "The existing package does not expose the required deterministic local artifact contract.",
                check=False,
            )
            self.assertEqual(first.returncode, 0)
            fixture.write_text(json.dumps(github_fixture(release="v2.0.0", pushed_at="2026-07-17T00:00:00Z")), encoding="utf-8")
            refreshed = self.cli(
                "reuse-check", "--task", task, "--force",
                "--decision", "REJECT_WITH_EVIDENCE",
                "--update-decision", "DEFER",
                "--rationale", "Version two changed upstream, but the frozen ticket needs a smaller incompatible local contract.",
            )
        payload = json.loads(refreshed.stdout)
        self.assertEqual(payload["reuse"]["update_count"], 1)
        self.assertEqual(payload["updates"][0]["previous_release"], "v1.0.0")
        self.assertEqual(payload["updates"][0]["latest_release"], "v2.0.0")

    def test_expired_probe_advises_only_the_next_product_write(self) -> None:
        self.start_video()
        ticket = self.read_json(".agent/current_ticket.json")
        ticket["reuse_discovery"]["expires_at"] = "2000-01-01T00:00:00+00:00"
        self.write_json(".agent/current_ticket.json", ticket)
        read_event = {
            "tool_name": "Read",
            "tool_input": {"path": "README.md"},
            "tool_use_id": "read-1",
        }
        write_event = {
            "tool_name": "apply_patch",
            "tool_input": {"patch": "*** Update File: src/video/mock/generator.ts\n"},
            "tool_use_id": "write-1",
        }
        with pushd(self.root):
            read_output = io.StringIO()
            with contextlib.redirect_stdout(read_output):
                GOAL_COMPASS.hook_pre(read_event)
            write_output = io.StringIO()
            with contextlib.redirect_stdout(write_output):
                GOAL_COMPASS.hook_pre(write_event)
        self.assertEqual(read_output.getvalue(), "")
        payload = json.loads(write_output.getvalue())
        self.assertNotIn("permissionDecision", payload["hookSpecificOutput"])
        self.assertIn("older than 24 hours", payload["hookSpecificOutput"]["additionalContext"])

    def test_fresh_probe_is_reused_without_repeating_search(self) -> None:
        fixture = self.write_reuse_fixture({"total_count": 0, "items": []})
        task = "Create a narrow local report renderer."
        with mock.patch.dict(os.environ, {"GOAL_COMPASS_REUSE_PROBE_FIXTURE": str(fixture)}):
            first = self.json_run("reuse-check", "--task", task)
            fixture.write_text("not json", encoding="utf-8")
            second = self.json_run("reuse-check", "--task", "Implement a different remaining project action")
        self.assertFalse(first["reuse"]["refresh_due"])
        self.assertEqual(second["reuse"]["status"], "NO_CANDIDATES")
        self.assertEqual(first["reuse"]["checked_at"], second["reuse"]["checked_at"])
        self.assertTrue(second["reuse"]["context_changed_since_probe"])

    def test_twenty_four_hour_refresh_uses_north_star_and_remaining_actions(self) -> None:
        fixture = self.write_reuse_fixture({"total_count": 0, "items": []})
        with mock.patch.dict(os.environ, {"GOAL_COMPASS_REUSE_PROBE_FIXTURE": str(fixture)}):
            self.goal_video()
            pending = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
            pending["ticket_id"] = "SPEECH-ADAPTER-NEXT"
            pending["task_goal"] = "Integrate the remaining speech transcription adapter"
            pending["must_do"] = ["Add deterministic speech transcription output"]
            self.write_json(".agent/tickets/pending/SPEECH-ADAPTER-NEXT.json", pending)
            state = self.read_json(".agent/runtime/reuse_probe.json")
            state["last_probe"]["expires_at"] = "2000-01-01T00:00:00+00:00"
            self.write_json(".agent/runtime/reuse_probe.json", state)
            refreshed = self.json_run("reuse-check", "--task", "Continue the confirmed project")
        remaining = " ".join(refreshed["remaining_actions"]).lower()
        self.assertIn("speech transcription", remaining)
        context = " ".join(refreshed["query_terms"] + refreshed["remaining_actions"]).lower()
        self.assertIn("video", context)

    def test_adopted_tool_is_added_to_ticket_and_machine_validation(self) -> None:
        fixture = self.write_reuse_fixture(github_fixture())
        candidate = "https://github.com/example/open-video-generator"
        ticket_path = ".agent/tickets/examples/VIDEO-MOCK-001.json"
        with mock.patch.dict(os.environ, {"GOAL_COMPASS_REUSE_PROBE_FIXTURE": str(fixture)}):
            self.goal_video()
            adopted = self.json_run(
                "reuse-check",
                "--ticket", ticket_path,
                "--decision", "ADOPT_EXISTING",
                "--candidate", candidate,
                "--rationale", "The licensed Python project matches the prompt-to-artifact contract and local runtime.",
                "--integration-plan", "Use its pipeline entry point behind the existing mock job boundary.",
                "--integration-validation-id", "mock_video_pipeline_test",
            )
            self.assertTrue(adopted["ok"])
            ticket = self.read_json(ticket_path)
            self.assertEqual(ticket["reuse_integration"]["status"], "PLANNED")
            self.assertEqual(ticket["reuse_integration"]["candidate"], candidate)
            self.assertIn("mock_video_pipeline_test", ticket["validation_ids"])
            self.assertIn("mock_video_pipeline_test", ticket["acceptance"]["commands_pass"])
            self.assertTrue(any(candidate in row for row in ticket["must_do"]))
            started = self.json_run("start", ticket_path)
        self.assertEqual(started["status"], "ACTIVE")
        current = self.read_json(".agent/current_ticket.json")
        self.assertEqual(current["reuse_integration"]["status"], "PLANNED")

    def test_adopted_tool_requires_executable_integration_contract(self) -> None:
        fixture = self.write_reuse_fixture(github_fixture())
        with mock.patch.dict(os.environ, {"GOAL_COMPASS_REUSE_PROBE_FIXTURE": str(fixture)}):
            self.goal_video()
            result = self.cli(
                "reuse-check",
                "--ticket", ".agent/tickets/examples/VIDEO-MOCK-001.json",
                "--decision", "ADOPT_EXISTING",
                "--candidate", "https://github.com/example/open-video-generator",
                "--rationale", "The project is compatible with the current runtime and artifact shape.",
                check=False,
            )
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertIn("--integration-plan (20+ characters)", payload["missing"])
        self.assertIn("--integration-validation-id", payload["missing"])

    def test_close_marks_adopted_tool_integration_verified(self) -> None:
        fixture = self.write_reuse_fixture(github_fixture())
        candidate = "https://github.com/example/open-video-generator"
        ticket_path = ".agent/tickets/pending/REUSE-INTEGRATION.json"
        with mock.patch.dict(os.environ, {"GOAL_COMPASS_REUSE_PROBE_FIXTURE": str(fixture)}):
            self.goal_video()
            self.install_validation("reuse_integration_ok", "import sys; sys.exit(0)")
            ticket = self.make_validation_ticket("reuse_integration_ok")
            ticket["ticket_id"] = "REUSE-INTEGRATION"
            ticket["task_goal"] = "Integrate the suitable existing video generator"
            self.write_json(ticket_path, ticket)
            self.json_run(
                "reuse-check",
                "--ticket", ticket_path,
                "--decision", "ADOPT_EXISTING",
                "--candidate", candidate,
                "--rationale", "The licensed Python project matches the required runtime and output contract.",
                "--integration-plan", "Route the existing generator through the current bounded video interface.",
                "--integration-validation-id", "reuse_integration_ok",
            )
            self.json_run("start", ticket_path)
            closed = self.json_run("close")
        self.assertEqual(closed["status"], "PASS")
        done = self.read_json(".agent/tickets/done/REUSE-INTEGRATION.json")
        self.assertEqual(done["reuse_integration"]["status"], "VERIFIED")


if __name__ == "__main__":
    import unittest

    unittest.main()
