from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

try:
    from .helpers import GOAL_COMPASS, GoalCompassRepoCase
except ImportError:
    from helpers import GOAL_COMPASS, GoalCompassRepoCase

from goal_compass_runtime.native_goal_bridge import NativeGoalBridgeError, replace_goal


FAKE_SERVER = r'''#!/usr/bin/env python3
import json
import os
import sys
import time

thread_id = "test-thread"
goal = {
    "threadId": thread_id,
    "objective": "old blocked objective",
    "status": "blocked",
    "tokenBudget": None,
    "tokensUsed": 91,
    "timeUsedSeconds": 17,
    "createdAt": 1,
    "updatedAt": 2,
}

for line in sys.stdin:
    message = json.loads(line)
    if "id" not in message:
        continue
    method = message.get("method")
    request_id = message["id"]
    if method == "initialize":
        result = {"userAgent": "fake", "codexHome": "/tmp", "platformFamily": "test", "platformOs": "test"}
    elif method == "thread/goal/get":
        result = {"goal": goal}
    elif method == "thread/goal/set":
        if os.environ.get("FAKE_NATIVE_GOAL_SET_FAIL") == "1":
            print(json.dumps({"id": request_id, "error": {"code": -32000, "message": "forced failure"}}), flush=True)
            continue
        if os.environ.get("FAKE_NATIVE_GOAL_SET_HANG") == "1":
            time.sleep(60)
        params = message.get("params") or {}
        if params.get("objective") is not None:
            goal = {
                **goal,
                "objective": params["objective"],
                "tokensUsed": 0,
                "timeUsedSeconds": 0,
                "updatedAt": 3,
            }
        if params.get("status") is not None:
            goal["status"] = params["status"]
        result = {"goal": goal}
    else:
        result = {}
    print(json.dumps({"id": request_id, "result": result}), flush=True)
'''


class NativeGoalBridgeTests(GoalCompassRepoCase):
    def fake_server(self) -> Path:
        path = self.root / "fake_codex_app_server.py"
        path.write_text(FAKE_SERVER, encoding="utf-8")
        return path

    def test_app_server_replaces_blocked_goal_and_verifies_exact_objective(self) -> None:
        objective = "replacement objective with exact bytes"
        result = replace_goal(
            objective,
            thread_id="test-thread",
            executable=[sys.executable, str(self.fake_server())],
            timeout=2,
        )

        self.assertEqual(result["status"], "SYNCED")
        self.assertEqual(result["operation"], "REPLACED")
        self.assertEqual(result["previous"]["status"], "blocked")
        self.assertEqual(result["current"]["status"], "active")
        self.assertEqual(result["current"]["objective"], objective)
        self.assertEqual(result["current"]["tokensUsed"], 0)

    def test_app_server_timeout_is_bounded(self) -> None:
        started = time.monotonic()
        with mock.patch.dict(os.environ, {"FAKE_NATIVE_GOAL_SET_HANG": "1"}):
            with self.assertRaises(NativeGoalBridgeError):
                replace_goal(
                    "replacement objective",
                    thread_id="test-thread",
                    executable=[sys.executable, str(self.fake_server())],
                    timeout=0.5,
                )
        self.assertLess(time.monotonic() - started, 3)

    def test_package_selftest_never_touches_host_native_goal(self) -> None:
        invocation_log = self.root / "native-app-server-invoked.txt"
        trap = self.root / "trap-codex.py"
        trap.write_text(
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            f"Path({str(invocation_log)!r}).write_text('invoked\\n', encoding='utf-8')\n"
            "raise SystemExit(91)\n",
            encoding="utf-8",
        )
        plugin_root = Path(__file__).resolve().parents[2]
        selftest = plugin_root / "assets" / "governor-harness" / ".agent" / "selftest" / "test_goal_compass.py"
        env = dict(os.environ)
        env.update(
            {
                "CODEX_THREAD_ID": "real-host-task-must-not-change",
                "CODEX_EXECUTABLE": str(trap),
                "GOAL_SUPERVISOR_NATIVE_GOAL_BRIDGE": "enabled",
            }
        )

        completed = subprocess.run(
            [sys.executable, str(selftest)],
            cwd=plugin_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("Goal Compass selftest OK", completed.stdout)
        self.assertFalse(invocation_log.exists(), "selftest invoked the host native Goal bridge")

    def test_goal_set_replaces_native_goal_without_fake_completion(self) -> None:
        self.goal_video()
        old_local = self.read_json(".agent/north_star_goal.json")
        definition = {
            "precise_goal": "Build a replacement product direction with verified delivery.",
            "problem_statement": "The durable user direction changed and the old goal is no longer authoritative.",
            "first_principles": ["The current user-confirmed direction is authoritative."],
            "process": {
                "nodes": [
                    {"id": "A", "action": "implement replacement path", "output": "replacement output", "consumer": "B", "acceptance": "output exists"},
                    {"id": "B", "action": "validate replacement path", "output": "validation evidence", "consumer": "delivery", "acceptance": "validation passes"},
                ]
            },
            "deliverables": [{"name": "replacement", "acceptance": "validated replacement is delivered"}],
            "final_acceptance": [{"id": "replacement_validation", "criterion": "replacement validation passes", "consumer": "delivery"}],
            "constraints": ["preserve unrelated product behavior"],
            "non_goals": ["do not continue the superseded direction"],
        }
        self.write_json("replacement.json", definition)
        native_result = {
            "ok": True,
            "status": "SYNCED",
            "operation": "REPLACED",
            "thread_id": "test-thread",
            "previous": {
                "objective": old_local["goal_mode_objective"],
                "status": "blocked",
                "tokensUsed": 123,
                "timeUsedSeconds": 45,
            },
            "current": {},
            "verified": True,
        }
        with mock.patch.object(
            GOAL_COMPASS,
            "native_goal_bridge_availability",
            return_value={"available": True, "thread_id": "test-thread", "executable": "fake"},
        ), mock.patch.object(GOAL_COMPASS, "replace_native_goal", return_value=native_result):
            result = self.json_run(
                "goal-set",
                "--text", "Build the replacement product direction.",
                "--definition-file", "replacement.json",
                "--replace-existing",
                "--replacement-reason", "User replaced the durable product direction.",
            )

        self.assertEqual(result["native_goal_sync"]["status"], "SYNCED")
        history = [json.loads(line) for line in (self.root / ".agent/goal_replacement_history.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(history[-1]["transition"], "SUPERSEDED_BY_USER_DIRECTION_CHANGE")
        self.assertFalse(history[-1]["objective_achieved"])
        self.assertEqual(history[-1]["reason"], "User replaced the durable product direction.")
        self.assertTrue(history[-1]["restore_available"])
        self.assertEqual(history[-1]["previous_project_snapshot"]["goal"], old_local["goal"])
        self.assertEqual(
            history[-1]["previous_project_snapshot"]["goal_mode_objective"],
            old_local["goal_mode_objective"],
        )

    def test_goal_set_records_native_replacement_when_project_has_no_local_goal(self) -> None:
        native_result = {
            "ok": True,
            "status": "SYNCED",
            "operation": "REPLACED",
            "thread_id": "test-thread",
            "previous": {
                "objective": "old blocked objective",
                "status": "blocked",
                "tokensUsed": 91,
                "timeUsedSeconds": 17,
            },
            "current": {},
            "verified": True,
        }
        with mock.patch.object(
            GOAL_COMPASS,
            "native_goal_bridge_availability",
            return_value={"available": True, "thread_id": "test-thread", "executable": "fake"},
        ), mock.patch.object(GOAL_COMPASS, "replace_native_goal", return_value=native_result):
            result = self.json_run(
                "goal-set",
                "--text", "Build the newly confirmed product direction.",
            )

        self.assertEqual(result["native_goal_sync"]["operation"], "REPLACED")
        self.assertEqual(
            result["native_goal_sync"]["transition"],
            "SUPERSEDED_BY_USER_DIRECTION_CHANGE",
        )
        history = [
            json.loads(line)
            for line in (self.root / ".agent/goal_replacement_history.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(history[-1]["transition"], "SUPERSEDED_BY_USER_DIRECTION_CHANGE")
        self.assertEqual(history[-1]["previous_status"], "blocked")
        self.assertEqual(history[-1]["previous_tokens_used"], 91)
        self.assertFalse(history[-1]["objective_achieved"])
        self.assertEqual(history[-1]["previous_native_snapshot"]["objective"], "old blocked objective")
        self.assertIsNone(history[-1]["previous_project_snapshot"])
        self.assertTrue(history[-1]["restore_available"])

    def test_active_codex_task_without_app_server_does_not_commit_project_goal(self) -> None:
        before = self.read_json(".agent/north_star_goal.json")
        with mock.patch.object(
            GOAL_COMPASS,
            "native_goal_bridge_availability",
            return_value={
                "available": False,
                "reason": "codex_executable_unavailable",
                "thread_id": "test-thread",
                "executable": None,
            },
        ):
            result = self.json_run(
                "goal-set",
                "--text", "Build the confirmed product direction.",
                check=False,
            )

        self.assertEqual(result["status"], "NATIVE_GOAL_SYNC_FAILED")
        self.assertEqual(self.read_json(".agent/north_star_goal.json"), before)

    def test_native_sync_failure_does_not_change_project_goal(self) -> None:
        self.goal_video()
        before = self.read_json(".agent/north_star_goal.json")
        with mock.patch.object(
            GOAL_COMPASS,
            "native_goal_bridge_availability",
            return_value={"available": True, "thread_id": "test-thread", "executable": "fake"},
        ), mock.patch.object(
            GOAL_COMPASS,
            "replace_native_goal",
            side_effect=NativeGoalBridgeError("forced failure"),
        ):
            result = self.json_run(
                "goal-set",
                "--text", "Build another durable direction.",
                "--replace-existing",
                "--replacement-reason", "User confirmed a durable direction change.",
                check=False,
            )

        self.assertEqual(result["status"], "NATIVE_GOAL_SYNC_FAILED")
        self.assertEqual(self.read_json(".agent/north_star_goal.json"), before)
