from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path

try:
    from .helpers import DEFAULT_TIMEOUT, PLUGIN_ROOT, copy_goal_compass_runtime, run_cmd, run_goal_compass
except ImportError:
    from helpers import DEFAULT_TIMEOUT, PLUGIN_ROOT, copy_goal_compass_runtime, run_cmd, run_goal_compass


HOOK = PLUGIN_ROOT / "scripts" / "goal_hook.py"


class ProcedureMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.parent = Path(self.tmp.name)
        self.repo = self.parent / "project"
        copy_goal_compass_runtime(self.repo, writable=True)
        result = run_goal_compass(["init"], cwd=self.repo)
        self.assertEqual(result.returncode, 0, result.stderr)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def hook(self, event: dict) -> str:
        payload = {
            "cwd": str(self.repo),
            "tool_name": "exec_command",
            **event,
        }
        result = run_cmd(
            [sys.executable, str(HOOK)],
            cwd=self.parent,
            timeout=DEFAULT_TIMEOUT,
            check=True,
            input_text=json.dumps(payload),
        )
        return result.stdout

    def successful_command(self, session_id: str, command: str) -> None:
        self.hook({
            "session_id": session_id,
            "hook_event_name": "PostToolUse",
            "tool_input": {"command": command},
            "tool_response": {"exit_code": 0},
        })

    def stop(self, session_id: str, message: str = "Task completed and verified.") -> None:
        self.hook({
            "session_id": session_id,
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": message,
        })

    def test_init_creates_empty_compact_procedure_index(self) -> None:
        index = json.loads((self.repo / ".agent/procedures/index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["procedures"], [])
        result = run_goal_compass(["procedure"], cwd=self.repo)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "EMPTY")

    def test_post_tool_success_auto_materializes_verified_local_service(self) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.successful_command("service-session", f"{sys.executable} -m http.server {port} --bind 127.0.0.1")

        index = json.loads((self.repo / ".agent/procedures/index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(index["procedures"]), 1)
        row = index["procedures"][0]
        self.assertEqual(row["kind"], "LOCAL_SERVICE")
        skill = self.repo / row["skill_path"]
        runner = self.repo / row["runner_path"]
        self.assertTrue(skill.is_file())
        self.assertTrue(runner.is_file())

        started = run_cmd([sys.executable, str(runner), "start"], cwd=self.repo, timeout=5, check=True)
        self.assertEqual(json.loads(started.stdout)["status"], "STARTED")
        time.sleep(0.15)
        status = run_cmd([sys.executable, str(runner), "status"], cwd=self.repo, timeout=5)
        self.assertEqual(status.returncode, 0)
        self.assertEqual(json.loads(status.stdout)["status"], "RUNNING")
        stopped = run_cmd([sys.executable, str(runner), "stop"], cwd=self.repo, timeout=5, check=True)
        self.assertEqual(json.loads(stopped.stdout)["status"], "STOPPED")
        verbose = run_goal_compass(["status", "--verbose"], cwd=self.repo)
        self.assertEqual(verbose.returncode, 0)
        self.assertEqual(json.loads(verbose.stdout)["procedures"]["ready_count"], 1)

    def test_generic_sequence_requires_two_independent_successful_threads(self) -> None:
        command = f"{sys.executable} -m unittest -q"
        self.successful_command("thread-one", command)
        self.stop("thread-one")
        first = json.loads((self.repo / ".agent/procedures/index.json").read_text(encoding="utf-8"))
        self.assertEqual(first["procedures"], [])

        self.successful_command("thread-two", command)
        self.stop("thread-two")
        second = json.loads((self.repo / ".agent/procedures/index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(second["procedures"]), 1)
        self.assertEqual(second["procedures"][0]["kind"], "DETERMINISTIC_COMMAND")
        self.assertEqual(len(second["procedures"][0]["verified_sessions"]), 2)

        listed = run_goal_compass(["procedure"], cwd=self.repo)
        self.assertEqual(listed.returncode, 0)
        listed_payload = json.loads(listed.stdout)
        self.assertEqual(listed_payload["ready_count"], 1)
        procedure_id = listed_payload["procedures"][0]["procedure_id"]
        shown = run_goal_compass(["procedure", "--id", procedure_id], cwd=self.repo)
        self.assertEqual(shown.returncode, 0)
        self.assertEqual(json.loads(shown.stdout)["procedure"]["procedure_id"], procedure_id)
        runner = self.repo / listed_payload["procedures"][0]["runner_path"]
        executed = run_cmd([sys.executable, str(runner), "run"], cwd=self.repo, timeout=5)
        self.assertEqual(executed.returncode, 0, executed.stderr)

    def test_failed_sensitive_and_read_commands_are_never_persisted(self) -> None:
        self.successful_command("unsafe", "TOKEN=secret python3 scripts/start.py")
        self.successful_command("unsafe", "cat README.md")
        self.hook({
            "session_id": "unsafe",
            "hook_event_name": "PostToolUse",
            "tool_input": {"command": f"{sys.executable} -m unittest -q"},
            "tool_response": {"exit-code": 1},
        })
        self.stop("unsafe")

        state = json.loads((self.repo / ".agent/runtime/procedure_memory.json").read_text(encoding="utf-8"))
        session_key = next(iter(state["sessions"]), None)
        if session_key:
            self.assertEqual(state["sessions"][session_key]["commands"], [])
        self.assertEqual(state["procedures"], {})

    def test_test_file_name_does_not_masquerade_as_service(self) -> None:
        self.successful_command("test-file", f"{sys.executable} scripts/test_server.py")
        index = json.loads((self.repo / ".agent/procedures/index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["procedures"], [])

    def test_thread_summary_is_bounded_redacted_and_replaced_per_session(self) -> None:
        self.successful_command("summary", f"{sys.executable} -m unittest -q")
        self.stop("summary", "First result TOKEN=private-value " + "x" * 900)
        self.stop("summary", "Final result PASSWORD=second-secret")
        state = json.loads((self.repo / ".agent/runtime/procedure_memory.json").read_text(encoding="utf-8"))
        summaries = state["thread_summaries"]
        self.assertEqual(len(summaries), 1)
        excerpt = summaries[0]["outcome_excerpt"]
        self.assertNotIn("private-value", excerpt)
        self.assertNotIn("second-secret", excerpt)
        self.assertLessEqual(len(excerpt), 600)

    def test_procedures_are_not_injected_into_unrelated_prompt(self) -> None:
        self.successful_command("service-session", f"{sys.executable} -m http.server 8765 --bind 127.0.0.1")
        output = self.hook({
            "session_id": "new-thread",
            "turn_id": "question",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Explain the product roadmap.",
        })
        self.assertNotIn("procedure", output.lower())
        self.assertNotIn("http.server", output.lower())


if __name__ == "__main__":
    unittest.main()
