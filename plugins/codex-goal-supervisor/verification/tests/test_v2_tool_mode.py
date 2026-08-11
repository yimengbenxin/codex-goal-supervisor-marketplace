from __future__ import annotations

import contextlib
import io
import json

try:
    from .helpers import GOAL_COMPASS, GoalCompassRepoCase, pushd
except ImportError:
    from helpers import GOAL_COMPASS, GoalCompassRepoCase, pushd

from goal_compass_runtime.observer import apply_observation, empty_state, observation_event, persist_recent_events


class V2ToolModeTests(GoalCompassRepoCase):
    def hook_output(self, event: dict, phase: str = "pre") -> str:
        output = io.StringIO()
        with pushd(self.root), contextlib.redirect_stdout(output):
            if phase == "post":
                GOAL_COMPASS.hook_post(event)
            else:
                GOAL_COMPASS.hook_pre(event)
        return output.getvalue()

    def test_init_enables_background_observer_without_requiring_ticket(self) -> None:
        mode = self.read_json(".agent/tool_mode.json")
        status = self.json_run("status")

        self.assertTrue(mode["enabled"])
        self.assertEqual(mode["mode"], "BACKGROUND_ADVISORY")
        self.assertFalse(mode["visible_ticket_required"])
        self.assertFalse(status["active"])
        self.assertEqual(status["observer"]["mode"], "BACKGROUND_OBSERVING")
        self.assertEqual(status["mdcp"]["current_required_action"], "continue_normal_execution")

    def test_ordinary_edit_is_silent_and_observed_without_ticket(self) -> None:
        event = {
            "tool_name": "apply_patch",
            "tool_input": {"patch": "*** Begin Patch\n*** Add File: src/app.py\n+VALUE = 1\n*** End Patch"},
            "tool_use_id": "ordinary-edit",
        }

        self.assertEqual(self.hook_output(event), "")
        observer = self.read_json(".agent/runtime/observer_state.json")
        self.assertEqual(observer["pre_events"], 1)
        self.assertIn("src/app.py", observer["changed_path_candidates"])

    def test_control_state_edit_is_still_denied_without_ticket(self) -> None:
        event = {
            "tool_name": "apply_patch",
            "tool_input": {"patch": "*** Begin Patch\n*** Update File: .agent/current_ticket.json\n+{}\n*** End Patch"},
            "tool_use_id": "control-edit",
        }

        payload = json.loads(self.hook_output(event))
        self.assertEqual(payload["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_project_authored_antigoal_is_warning_not_hidden_deny(self) -> None:
        north = self.read_json(".agent/north_star_goal.json")
        north.update({
            "confirmed": True,
            "goal": "Build an internal package registry.",
            "anti_goals": ["public marketplace"],
        })
        self.write_json(".agent/north_star_goal.json", north)
        event = {
            "tool_name": "apply_patch",
            "tool_input": {"patch": "*** Begin Patch\n*** Add File: src/public_marketplace.py\n+# public marketplace\n*** End Patch"},
            "tool_use_id": "anti-goal-edit",
        }

        payload = json.loads(self.hook_output(event))
        hook = payload["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", hook)
        self.assertIn("public marketplace", hook["additionalContext"])

    def test_three_consecutive_failures_emit_one_strong_warning(self) -> None:
        outputs = []
        for index in range(3):
            outputs.append(self.hook_output({
                "tool_name": "Bash",
                "tool_input": {"command": "python3 failing_task.py"},
                "tool_response": {"status": "failed"},
                "tool_use_id": f"failure-{index}",
            }, phase="post"))

        self.assertEqual(outputs[:2], ["", ""])
        self.assertIn("Three consecutive tool failures", outputs[2])
        self.assertNotIn("permissionDecision", outputs[2])

    def test_exit_code_fields_drive_observer_failure_semantics(self) -> None:
        outputs = []
        for index, field in enumerate(("exit_code", "exitCode", "returncode")):
            outputs.append(self.hook_output({
                "tool_name": "Bash",
                "tool_input": {"command": "python3 failing_task.py"},
                "tool_response": {field: "1" if index == 1 else 1},
                "tool_use_id": f"exit-failure-{index}",
            }, phase="post"))

        state = self.read_json(".agent/runtime/observer_state.json")
        self.assertEqual(state["failed_events"], 3)
        self.assertEqual(state["consecutive_failures"], 3)
        self.assertIn("Three consecutive tool failures", outputs[-1])

        self.hook_output({
            "tool_name": "Bash",
            "tool_input": {"command": "python3 passing_task.py"},
            "tool_response": {"exit_code": 0},
            "tool_use_id": "exit-success",
        }, phase="post")
        state = self.read_json(".agent/runtime/observer_state.json")
        self.assertEqual(state["consecutive_failures"], 0)

    def test_observer_recent_event_projection_is_bounded(self) -> None:
        state = empty_state()
        for index in range(1000):
            state, _ = apply_observation(state, observation_event(
                event_id=f"bounded-{index}",
                phase="PostToolUse",
                category="write",
                paths=[f"src/generated/{index:04d}.py"],
                failed=False,
                observed_at=f"2026-07-19T00:00:{index % 60:02d}+00:00",
            ))
        target = self.root / ".agent" / "runtime" / "bounded-observer-events.jsonl"
        persist_recent_events(target, state)

        self.assertLessEqual(len(target.read_text(encoding="utf-8").splitlines()), 128)
        self.assertLessEqual(target.stat().st_size, 64 * 1024)

    def test_custodian_can_recommend_ticket_without_requiring_it(self) -> None:
        self.goal_video()
        result = self.json_run(
            "request", "--text",
            "Build an AI automatic video generation system by adding one validation path",
        )

        self.assertFalse(result["requires_new_ticket"])
        self.assertTrue(result["ticket_recommended"])
        self.assertEqual(result["custodian"]["invocation"], "AI_OPTIONAL")
        self.assertFalse(result["custodian"]["binding"])


if __name__ == "__main__":
    import unittest

    unittest.main()
