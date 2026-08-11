from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path
from unittest import mock

try:
    from .helpers import GoalCompassRepoCase
except ImportError:
    from helpers import GoalCompassRepoCase

from goal_compass_runtime.goal_return import (
    CLOSED,
    PERSISTENT_CONSTRAINT,
    PROMOTED_TO_CONSTRAINT,
    SUPERSEDED,
    classify_prompt,
    compact_status,
    on_post_compact,
    on_pre_compact,
    on_session_start,
    on_stop,
    on_tool_event,
    on_user_prompt,
)


class GoalReturnTests(GoalCompassRepoCase):
    def setUp(self) -> None:
        super().setUp()
        self.goal_video()
        runtime = self.root / ".agent" / "runtime" / "goal_return"
        self.state = runtime / "state.json"
        self.lock = runtime / "state.lock"
        self.events = runtime / "events.jsonl"
        self.session_id = "goal-return-session"

    def north(self) -> dict:
        return self.read_json(".agent/north_star_goal.json")

    def convergence(self) -> dict:
        return self.read_json(".agent/runtime/convergence_state.json")

    def event(self, phase: str, **values) -> dict:
        return {
            "session_id": self.session_id,
            "turn_id": values.pop("turn_id", "turn-1"),
            "hook_event_name": phase,
            **values,
        }

    def prompt(self, text: str, turn_id: str = "turn-1") -> str | None:
        return on_user_prompt(
            self.state,
            self.lock,
            self.events,
            self.north(),
            self.convergence(),
            self.event("UserPromptSubmit", prompt=text, turn_id=turn_id),
        )

    def stop(self, message: str, turn_id: str = "turn-1") -> None:
        on_stop(
            self.state,
            self.lock,
            self.events,
            self.north(),
            self.event("Stop", last_assistant_message=message, stop_hook_active=False, turn_id=turn_id),
        )

    def goal_return_tool(
        self,
        tool_use_id: str,
        paths: list[str],
        category: str,
        failed: bool,
        *,
        phase: str,
    ) -> dict | None:
        return on_tool_event(
            self.state,
            self.lock,
            self.events,
            self.north(),
            self.event(phase, tool_use_id=tool_use_id),
            paths=paths,
            category=category,
            failed=failed,
        )

    def compact(self, index: int) -> str | None:
        pre = self.event("PreCompact", trigger="auto", turn_id=f"compact-{index}")
        post = self.event("PostCompact", trigger="auto", turn_id=f"compact-{index}")
        start = self.event("SessionStart", source="compact", turn_id=f"compact-{index}")
        on_pre_compact(self.state, self.lock, self.events, self.north(), pre)
        on_post_compact(self.state, self.lock, self.events, self.north(), post)
        return on_session_start(
            self.state,
            self.lock,
            self.events,
            self.north(),
            self.convergence(),
            start,
        )

    def state_json(self) -> dict:
        return json.loads(self.state.read_text(encoding="utf-8"))

    def interrupt(self) -> dict:
        rows = self.state_json()["sessions"][self.session_id]["interrupts"]
        return rows[-1]

    def test_question_closes_after_one_stop(self) -> None:
        context = self.prompt("插一句：这个字段是什么意思？")
        self.assertIn("bounded temporary branch", context or "")

        self.stop("这个字段表示当前阶段的验收消费者。")

        self.assertEqual(self.interrupt()["state"], CLOSED)
        self.assertEqual(compact_status(self.state)["open_interrupts"], 0)

    def test_temporary_branch_closes_with_completion_evidence(self) -> None:
        self.prompt("先处理一个临时问题：修复 README 的链接。")
        signal = on_tool_event(
            self.state,
            self.lock,
            self.events,
            self.north(),
            self.event("PreToolUse", tool_use_id="write-1"),
            paths=["README.md"],
            category="write",
            failed=False,
        )
        self.assertIsNone(signal)

        self.stop("已完成 README 链接修复并验证通过。")

        row = self.interrupt()
        self.assertEqual(row["state"], CLOSED)
        self.assertEqual(row["affected_paths"], ["README.md"])

    def test_temporary_branch_returns_during_long_goal_turn_after_two_validations(self) -> None:
        self.prompt("临时修复运行时熔断逻辑。")
        on_tool_event(
            self.state,
            self.lock,
            self.events,
            self.north(),
            self.event("PreToolUse", tool_use_id="write-runtime"),
            paths=["src/runtime.py"],
            category="write",
            failed=False,
        )

        first = on_tool_event(
            self.state,
            self.lock,
            self.events,
            self.north(),
            self.event("PostToolUse", tool_use_id="validation-focused"),
            paths=[],
            category="validation",
            failed=False,
        )
        second = on_tool_event(
            self.state,
            self.lock,
            self.events,
            self.north(),
            self.event("PostToolUse", tool_use_id="validation-regression"),
            paths=[],
            category="validation",
            failed=False,
        )

        self.assertIsNone(first)
        self.assertEqual(second["signal"], "TEMPORARY_BRANCH_EXIT_REACHED")
        self.assertIn("Do not keep revalidating", second["reason"])
        self.assertEqual(self.interrupt()["state"], CLOSED)
        self.assertEqual(self.interrupt()["close_reason"], "consecutive_validation_passes_after_write")

        replay = on_tool_event(
            self.state,
            self.lock,
            self.events,
            self.north(),
            self.event("PreToolUse", tool_use_id="same-turn-replay"),
            paths=["src/runtime.py"],
            category="write",
            failed=False,
        )
        self.assertEqual(replay["signal"], "CLOSED_BRANCH_REPLAY_CANDIDATE")
        self.assertEqual(replay["replay_count"], 1)

    def test_new_write_resets_in_turn_validation_exit_candidate(self) -> None:
        self.prompt("临时修复运行时熔断逻辑。")
        self.goal_return_tool("write-1", ["src/runtime.py"], "write", False, phase="PreToolUse")
        self.goal_return_tool("validate-1", [], "validation", False, phase="PostToolUse")
        self.goal_return_tool("write-2", ["src/runtime.py"], "write", False, phase="PreToolUse")
        result = self.goal_return_tool("validate-2", [], "validation", False, phase="PostToolUse")

        self.assertIsNone(result)
        self.assertEqual(self.interrupt()["state"], "CLOSE_CANDIDATE")
        self.assertEqual(self.interrupt()["successful_validation_streak"], 1)

    def test_incomplete_temporary_branch_remains_open(self) -> None:
        self.prompt("临时检查一下发布脚本。")

        self.stop("还没完成，需要用户确认发布目标。")

        self.assertEqual(self.interrupt()["state"], "CLOSE_CANDIDATE")
        self.assertEqual(compact_status(self.state)["open_interrupts"], 1)

    def test_closed_branch_survives_three_compactions_without_replay(self) -> None:
        self.prompt("插一句：解释一下当前校验状态？")
        self.stop("已完成解释。")

        contexts = [self.compact(index) for index in range(3)]

        self.assertTrue(all("Closed temporary branches" in (value or "") for value in contexts))
        self.assertTrue(all("do not resume" in (value or "") for value in contexts))
        row = self.interrupt()
        self.assertEqual(row["state"], CLOSED)
        self.assertEqual(row["replay_count"], 0)

    def test_persistent_constraint_is_not_auto_closed(self) -> None:
        self.assertEqual(classify_prompt("从现在起所有输出都保持 JSON。"), PERSISTENT_CONSTRAINT)

        context = self.prompt("从现在起所有输出都保持 JSON。")
        self.stop("已完成。")

        self.assertIsNone(context)
        self.assertEqual(compact_status(self.state)["open_interrupts"], 0)
        self.assertEqual(compact_status(self.state)["closed_interrupts"], 0)

    def test_open_branch_can_be_promoted_to_persistent_constraint(self) -> None:
        self.prompt("临时把输出格式改成 JSON。")

        context = self.prompt("从现在起所有输出都保持 JSON。", turn_id="turn-2")

        self.assertIsNone(context)
        self.assertEqual(self.interrupt()["state"], PROMOTED_TO_CONSTRAINT)
        self.assertEqual(compact_status(self.state)["open_interrupts"], 0)

    def test_plain_user_interruption_is_temporary_but_continue_is_not(self) -> None:
        context = self.prompt("顺带把刚才的版本号含义解释清楚。")
        self.assertIn("bounded temporary branch", context or "")
        self.stop("版本号由主版本、次版本和缓存标识组成。")
        self.assertEqual(self.interrupt()["state"], CLOSED)

        count = compact_status(self.state)["closed_interrupts"]
        continuation = self.prompt("继续", turn_id="turn-continue")

        self.assertIsNone(continuation)
        self.assertEqual(compact_status(self.state)["closed_interrupts"], count)

    def test_old_generation_interrupt_is_superseded(self) -> None:
        self.prompt("临时检查旧目标的发布状态。")
        changed = self.north()
        changed["goal"] = "Build a different confirmed product."
        changed["confirmed_at"] = "2026-08-09T04:00:00+00:00"

        on_pre_compact(
            self.state,
            self.lock,
            self.events,
            changed,
            self.event("PreCompact", trigger="manual", turn_id="goal-change"),
        )

        self.assertEqual(self.interrupt()["state"], SUPERSEDED)
        self.assertEqual(compact_status(self.state)["open_interrupts"], 0)

    def test_compact_recovery_is_bounded_and_does_not_store_secrets(self) -> None:
        secret = "fixture-secret-abcdefghijklmnop"
        self.prompt(f"插一句：检查 token={secret} 的配置问题。")
        self.stop("已完成配置检查。")

        context = self.compact(1)

        self.assertLessEqual(len(context or ""), 1400)
        self.assertNotIn(secret, self.state.read_text(encoding="utf-8"))
        self.assertNotIn(secret, self.events.read_text(encoding="utf-8"))

    def test_replay_counter_requires_exact_affected_path_after_compaction(self) -> None:
        self.prompt("临时修复 docs/temporary.md。")
        on_tool_event(
            self.state,
            self.lock,
            self.events,
            self.north(),
            self.event("PreToolUse", tool_use_id="original-write"),
            paths=["docs/temporary.md"],
            category="write",
            failed=False,
        )
        self.stop("已完成临时文档修复。")
        self.compact(1)

        unrelated = on_tool_event(
            self.state,
            self.lock,
            self.events,
            self.north(),
            self.event("PreToolUse", tool_use_id="unrelated"),
            paths=["src/core.py"],
            category="write",
            failed=False,
        )
        signals = [
            on_tool_event(
                self.state,
                self.lock,
                self.events,
                self.north(),
                self.event("PreToolUse", tool_use_id=f"replay-{index}"),
                paths=["docs/temporary.md"],
                category="write",
                failed=False,
            )
            for index in range(1, 4)
        ]

        self.assertIsNone(unrelated)
        self.assertEqual([row["replay_count"] for row in signals if row], [1, 2, 3])
        self.assertFalse(signals[0]["needs_judge"])
        self.assertTrue(signals[-1]["needs_judge"])

    def test_goal_return_state_is_atomic_under_concurrent_hooks(self) -> None:
        prompts = [f"插一句：临时问题 {index}？" for index in range(20)]

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda item: self.prompt(item[1], turn_id=f"turn-{item[0]}"), enumerate(prompts)))

        state = self.state_json()
        session = state["sessions"][self.session_id]
        open_rows = [row for row in session["interrupts"] if row["state"] in {"OPEN", "CLOSE_CANDIDATE"}]
        self.assertLessEqual(len(open_rows), 1)
        self.assertLessEqual(len(session["interrupts"]), 32)
        for line in self.events.read_text(encoding="utf-8").splitlines():
            self.assertIsInstance(json.loads(line), dict)

    def test_event_log_is_bounded_by_count(self) -> None:
        with mock.patch("goal_compass_runtime.goal_return.MAX_EVENTS", 8):
            for index in range(12):
                on_pre_compact(
                    self.state,
                    self.lock,
                    self.events,
                    self.north(),
                    self.event("PreCompact", trigger="test", turn_id=f"bounded-{index}"),
                )

        rows = [json.loads(line) for line in self.events.read_text(encoding="utf-8").splitlines()]
        self.assertLessEqual(len(rows), 8)

    def test_saturated_event_log_does_not_drop_concurrent_stop_transitions(self) -> None:
        def exercise(session_index: int) -> None:
            session_id = f"saturated-{session_index}"
            for cycle in range(12):
                turn_id = f"turn-{cycle}"
                on_user_prompt(
                    self.state,
                    self.lock,
                    self.events,
                    self.north(),
                    self.convergence(),
                    {
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "hook_event_name": "UserPromptSubmit",
                        "prompt": f"临时检查 docs/{session_index}-{cycle}.md。",
                    },
                )
                on_stop(
                    self.state,
                    self.lock,
                    self.events,
                    self.north(),
                    {
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "hook_event_name": "Stop",
                        "last_assistant_message": "已完成检查并验证通过。",
                        "stop_hook_active": False,
                    },
                )

        with mock.patch("goal_compass_runtime.goal_return.MAX_EVENTS", 8):
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(exercise, range(8)))

        state = self.state_json()
        for session in state["sessions"].values():
            rows = session.get("interrupts", [])
            self.assertLessEqual(len(rows), 32)
            self.assertTrue(all(row.get("state") == CLOSED for row in rows), rows)
        event_rows = [json.loads(line) for line in self.events.read_text(encoding="utf-8").splitlines()]
        self.assertLessEqual(len(event_rows), 8)


if __name__ == "__main__":
    import unittest
    unittest.main()
