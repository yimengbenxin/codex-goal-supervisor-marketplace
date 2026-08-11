from __future__ import annotations

import contextlib
import http.server
import importlib.util
import io
import json
import os
import shutil
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

try:
    from .helpers import FIXTURE_TICKETS, PLUGIN_ROOT, MinimalPluginFixtureCase, run_cmd
except ImportError:
    from helpers import FIXTURE_TICKETS, PLUGIN_ROOT, MinimalPluginFixtureCase, run_cmd


def load_installer(installer_path):
    spec = importlib.util.spec_from_file_location("installer_under_test", installer_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load installer: {installer_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_installer_no_subprocess(installer_path, repo, force=True, reset_state=False):
    module = load_installer(installer_path)
    with contextlib.redirect_stdout(io.StringIO()):
        return module.install(repo, force, reset_state=reset_state)


class InstallTests(MinimalPluginFixtureCase):
    def test_feedback_device_helper_has_no_manual_token_input(self) -> None:
        script = PLUGIN_ROOT / "scripts" / "configure_feedback_client.py"
        result = run_cmd(
            [sys.executable, str(script), "--help"],
            cwd=self.plugin,
            timeout=20,
            check=True,
        )
        self.assertNotIn("--token", result.stdout)
        self.assertNotIn("--endpoint", result.stdout)
        self.assertIn("project", result.stdout)

    def test_feedback_device_helper_requires_installed_project(self) -> None:
        script = PLUGIN_ROOT / "scripts" / "configure_feedback_client.py"
        result = run_cmd(
            [sys.executable, str(script), str(self.repo)],
            cwd=self.plugin,
            timeout=20,
        )
        payload = json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(payload["error"], "goal_compass_not_installed")

    def test_public_plugin_identity_is_canonical_and_has_no_v2_product_name(self) -> None:
        plugin_root = Path(__file__).resolve().parents[2]
        manifest = json.loads((plugin_root / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "codex-goal-supervisor")
        self.assertEqual(manifest["interface"]["displayName"], "Codex Goal Supervisor")
        self.assertTrue(str(manifest["version"]).startswith("2."))
        for relative in ["README.md", "INSTALL_GOAL_COMPASS.zh.md", "skills/goal-supervisor/SKILL.md"]:
            text = (plugin_root / relative).read_text(encoding="utf-8")
            self.assertNotIn("Goal Supervisor V2", text)
            self.assertNotIn("Goal Compass V2", text)

    def test_installer_writes_runtime_provenance(self) -> None:
        installer = self.plugin / "scripts" / "install_governor.py"
        run_cmd([sys.executable, str(installer), str(self.repo), "--force"], cwd=self.plugin, timeout=20, check=True)

        provenance = json.loads((self.repo / ".agent" / "goal_compass_install.json").read_text(encoding="utf-8"))
        self.assertTrue(provenance["initialized"])
        self.assertEqual(len(provenance["runtime_sha256"]), 64)
        self.assertEqual(provenance["migration_policy"], "preserve_project_state_and_remove_only_known_legacy_examples")
        hooks = json.loads((self.repo / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        windows = hooks["hooks"]["PreToolUse"][0]["hooks"][0]["commandWindows"]
        self.assertIn("windows_hook.py", windows)
        self.assertNotIn(" -c ", windows)
        feedback = json.loads((self.repo / ".agent" / "feedback_config.json").read_text(encoding="utf-8"))
        self.assertEqual(feedback["deployment_context"], "unknown")
        self.assertFalse(feedback["upload_enabled"])
        self.assertEqual(feedback["delivery"], "local_outbox_only")

    def test_interactive_install_asks_context_and_defaults_to_no_upload(self) -> None:
        installer = load_installer(self.plugin / "scripts" / "install_governor.py")
        args = SimpleNamespace(
            feedback_context=None,
            allow_feedback_upload=False,
            deny_feedback_upload=False,
            confirm_feedback_upload=False,
        )
        stdin = mock.Mock()
        stdin.isatty.return_value = True
        with mock.patch.object(installer.sys, "stdin", stdin), mock.patch("builtins.input", side_effect=["y", ""]):
            context, allow_upload = installer.resolve_feedback_policy(args)
        self.assertEqual(context, "enterprise")
        self.assertFalse(allow_upload)

    def test_installer_requires_explicit_confirmation_before_upload(self) -> None:
        installer = self.plugin / "scripts" / "install_governor.py"
        result = run_cmd(
            [
                sys.executable,
                str(installer),
                str(self.repo),
                "--force",
                "--feedback-context", "personal",
                "--allow-feedback-upload",
            ],
            cwd=self.plugin,
            timeout=20,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--confirm-feedback-upload", result.stderr)
        self.assertFalse((self.repo / ".agent").exists())

    def test_installer_can_explicitly_authorize_project_upload(self) -> None:
        requests: list[str] = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                requests.append(self.path)
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                response = json.dumps({
                    "ok": True,
                    "device_id": "dev_installer_test",
                    "token": "gsvd_" + "x" * 48,
                    "token_type": "Bearer",
                    "endpoint": "/v1/events",
                }).encode("utf-8")
                self.send_response(201)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

            def log_message(self, *_args) -> None:
                return

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        installer = self.plugin / "scripts" / "install_governor.py"
        device_config = self.repo / "device-feedback.json"
        device_token = self.repo / "device-feedback.token"
        endpoint = f"http://127.0.0.1:{server.server_port}/v1/events"
        device_config.write_text(json.dumps({
            "schema_version": 2,
            "endpoint": endpoint,
            "registration_endpoint": f"http://127.0.0.1:{server.server_port}/v1/devices/register",
            "token_file": str(device_token),
            "credential_mode": "auto_registered_device",
        }), encoding="utf-8")
        try:
            with mock.patch.dict(os.environ, {
                "GOAL_COMPASS_FEEDBACK_GLOBAL_CONFIG": str(device_config),
                "GOAL_COMPASS_FEEDBACK_TOKEN_FILE": str(device_token),
            }):
                run_cmd(
                    [
                        sys.executable,
                        str(installer),
                        str(self.repo),
                        "--force",
                        "--feedback-context", "enterprise",
                        "--allow-feedback-upload",
                        "--confirm-feedback-upload",
                    ],
                    cwd=self.plugin,
                    timeout=20,
                    check=True,
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        feedback = json.loads((self.repo / ".agent" / "feedback_config.json").read_text(encoding="utf-8"))
        self.assertEqual(feedback["deployment_context"], "enterprise")
        self.assertTrue(feedback["upload_enabled"])
        self.assertTrue(feedback["upload_consent_at"])
        self.assertEqual(feedback["delivery"], "realtime_with_durable_outbox")
        self.assertEqual(requests, ["/v1/devices/register"])
        self.assertTrue(device_token.is_file())

    def test_install_does_not_pollute_project(self) -> None:
        writes, skips, filtered = run_installer_no_subprocess(
            self.plugin / "scripts" / "install_governor.py",
            self.repo,
            force=True,
        )
        self.assertGreater(writes, 0)
        self.assertGreater(filtered, 0)
        self.assertEqual((self.repo / "README.md").read_text(encoding="utf-8"), "User README\n")
        self.assertEqual((self.repo / "AGENTS.md").read_text(encoding="utf-8"), "User AGENTS\n")
        self.assertEqual((self.repo / "tests" / "existing_test.py").read_text(encoding="utf-8"), "print('existing')\n")
        self.assertFalse((self.repo / "README.zh.md").exists())
        self.assertFalse((self.repo / "tests" / "test_goal_compass.py").exists())
        self.assertFalse((self.repo / ".agent" / "legacy" / "governor.py").exists())
        self.assertFalse((self.repo / ".agent" / "board_events.jsonl").exists())
        self.assertFalse((self.repo / ".agent" / "reverse_signal.jsonl").exists())
        self.assertFalse((self.repo / ".agent" / "signed_ledger.json").exists())
        self.assertFalse((self.repo / ".agent" / "tickets" / "examples").exists())
        self.assertTrue((self.repo / ".agent" / "goal_compass.py").exists())
        self.assertTrue((self.repo / ".agent" / "goal_compass_runtime" / "windows_hook.py").exists())
        self.assertTrue((self.repo / ".agent" / "quarantine_manifest.jsonl").exists())
        self.assertTrue((self.repo / ".codex" / "hooks.json").exists())
        self.assertEqual(json.loads((self.repo / ".codex" / "hooks.json").read_text()), {"hooks": {}})
        catalog = json.loads((self.repo / ".agent" / "validation_catalog.json").read_text())
        self.assertNotIn("mock_video_pipeline_test", catalog)
        self.assertNotIn("routing_mvp_test", catalog)
        self.assertNotIn("permission_guard_test", catalog)

    def test_force_update_preserves_project_state_and_merges_catalog(self) -> None:
        installer = self.plugin / "scripts" / "install_governor.py"
        run_installer_no_subprocess(installer, self.repo, force=True)
        north = {"confirmed": True, "goal": "User North Star"}
        current = {"status": "ACTIVE", "ticket_id": "USER-001"}
        (self.repo / ".agent" / "north_star_goal.json").write_text(json.dumps(north) + "\n", encoding="utf-8")
        (self.repo / ".agent" / "current_ticket.json").write_text(json.dumps(current) + "\n", encoding="utf-8")
        (self.repo / ".agent" / "backlog.jsonl").write_text('{"text":"keep me"}\n', encoding="utf-8")
        (self.repo / ".agent" / "quarantine_manifest.jsonl").write_text('{"target":"keep-me"}\n', encoding="utf-8")
        catalog = {"user_validation": {"cmd": "{python} -c \"import sys; sys.exit(0)\"", "description": "keep", "timeout_sec": 5}}
        (self.repo / ".agent" / "validation_catalog.json").write_text(json.dumps(catalog) + "\n", encoding="utf-8")

        run_installer_no_subprocess(installer, self.repo, force=True)

        self.assertEqual(json.loads((self.repo / ".agent" / "north_star_goal.json").read_text()), north)
        self.assertEqual(json.loads((self.repo / ".agent" / "current_ticket.json").read_text()), current)
        self.assertIn("keep me", (self.repo / ".agent" / "backlog.jsonl").read_text())
        self.assertIn("keep-me", (self.repo / ".agent" / "quarantine_manifest.jsonl").read_text())
        merged = json.loads((self.repo / ".agent" / "validation_catalog.json").read_text())
        self.assertIn("user_validation", merged)
        self.assertIn("project_pytest", merged)

    def test_install_merges_existing_hooks_and_is_idempotent(self) -> None:
        custom = {
            "hooks": {
                "SessionStart": [{"matcher": ".*", "hooks": [{"type": "command", "command": "echo session"}]}],
                "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo custom"}]}],
            }
        }
        hooks = self.repo / ".codex" / "hooks.json"
        hooks.parent.mkdir(parents=True)
        hooks.write_text(json.dumps(custom, indent=2) + "\n", encoding="utf-8")

        installer = self.plugin / "scripts" / "install_governor.py"
        for _ in range(2):
            run_cmd(
                [sys.executable, str(installer), str(self.repo), "--force"],
                cwd=self.plugin,
                timeout=20,
                check=True,
            )
        merged = json.loads(hooks.read_text(encoding="utf-8"))

        self.assertIn("SessionStart", merged["hooks"])
        self.assertIn("echo custom", json.dumps(merged))
        for event in (
            "PreToolUse", "PostToolUse", "PreCompact", "PostCompact",
            "SessionStart", "SubagentStart", "UserPromptSubmit", "Stop",
        ):
            handlers = [handler for group in merged["hooks"][event] for handler in group.get("hooks", [])]
            compass = [handler for handler in handlers if "goal_compass.py" in handler.get("command", "")]
            self.assertEqual(len(compass), 1)
        session_handlers = [
            handler
            for group in merged["hooks"]["SessionStart"]
            for handler in group.get("hooks", [])
        ]
        session_commands = [handler.get("command") for handler in session_handlers]
        self.assertEqual(session_commands.count("echo session"), 1)
        self.assertEqual(sum("project_hook.py" in str(command) for command in session_commands), 1)

    def test_force_update_removes_only_legacy_product_examples(self) -> None:
        examples = self.repo / ".agent" / "tickets" / "examples"
        examples.mkdir(parents=True)
        for name in ("VIDEO-MOCK-001.json", "ROUTING-MVP-001.json", "PERMISSION-GUARD-001.json"):
            shutil.copy2(FIXTURE_TICKETS / name, examples / name)
        (examples / "USER-TICKET.json").write_text('{"ticket_id":"USER-TICKET"}\n', encoding="utf-8")
        catalog_path = self.repo / ".agent" / "validation_catalog.json"
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        catalog_path.write_text(json.dumps({
            "mock_video_pipeline_test": {"cmd": "npm test -- tests/video/mock-video-pipeline.test.ts"},
            "user_validation": {"cmd": "{python} -c \"import sys; sys.exit(0)\""},
        }) + "\n", encoding="utf-8")

        run_installer_no_subprocess(self.plugin / "scripts" / "install_governor.py", self.repo, force=True)

        self.assertFalse((examples / "VIDEO-MOCK-001.json").exists())
        self.assertFalse((examples / "ROUTING-MVP-001.json").exists())
        self.assertFalse((examples / "PERMISSION-GUARD-001.json").exists())
        self.assertTrue((examples / "USER-TICKET.json").exists())
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        self.assertNotIn("mock_video_pipeline_test", catalog)
        self.assertIn("user_validation", catalog)

    def test_modified_legacy_named_ticket_is_preserved(self) -> None:
        examples = self.repo / ".agent" / "tickets" / "examples"
        examples.mkdir(parents=True)
        custom = examples / "VIDEO-MOCK-001.json"
        custom.write_text('{"ticket_id":"USER-OWNED"}\n', encoding="utf-8")

        run_installer_no_subprocess(self.plugin / "scripts" / "install_governor.py", self.repo, force=True)

        self.assertTrue(custom.exists())
        self.assertIn("USER-OWNED", custom.read_text(encoding="utf-8"))

    def test_reset_state_replaces_state_without_force(self) -> None:
        installer = self.plugin / "scripts" / "install_governor.py"
        run_installer_no_subprocess(installer, self.repo, force=True)
        north = self.repo / ".agent" / "north_star_goal.json"
        north.write_text('{"confirmed":true,"goal":"CUSTOM"}\n', encoding="utf-8")

        run_installer_no_subprocess(installer, self.repo, force=False, reset_state=True)

        self.assertNotEqual(json.loads(north.read_text(encoding="utf-8")).get("goal"), "CUSTOM")

    def test_installer_refuses_hook_symlink_outside_repo(self) -> None:
        victim = self.base / "victim.json"
        victim.write_text('{"keep":true}\n', encoding="utf-8")
        hooks = self.repo / ".codex" / "hooks.json"
        hooks.parent.mkdir(parents=True)
        os.symlink(victim, hooks)

        with self.assertRaises(SystemExit):
            run_installer_no_subprocess(self.plugin / "scripts" / "install_governor.py", self.repo, force=True)

        self.assertEqual(victim.read_text(encoding="utf-8"), '{"keep":true}\n')
