from __future__ import annotations

import concurrent.futures
import json
import os
import sys

try:
    from .helpers import GoalCompassRepoCase, run_cmd
except ImportError:
    from helpers import GoalCompassRepoCase, run_cmd

from goal_compass_runtime.state_store import exclusive_file_lock, load_json, process_alive, write_json


class StateConcurrencyTests(GoalCompassRepoCase):
    def _process(self, *args: str, input_text: str | None = None):
        return run_cmd(
            [sys.executable, ".agent/goal_compass.py", *args],
            cwd=self.root,
            timeout=8,
            input_text=input_text,
        )

    def test_concurrent_evidence_adds_do_not_lose_updates(self) -> None:
        self.start_video()

        def add(index: int):
            return self._process(
                "evidence-add", "--type", "manual", "--source", f"agent-{index}",
                "--summary", f"concurrent evidence {index}",
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(add, range(8)))

        self.assertTrue(all(result.returncode == 0 for result in results), [result.stderr for result in results])
        current = self.read_json(".agent/current_ticket.json")
        self.assertEqual(len(current["evidence"]), 8)
        self.assertGreaterEqual(current["state_revision"], 9)

    def test_process_alive_probe_is_non_destructive_for_current_process(self) -> None:
        current_pid = os.getpid()
        self.assertTrue(process_alive(current_pid))
        self.assertEqual(os.getpid(), current_pid)

    def test_concurrent_hook_events_are_folded_without_lost_updates(self) -> None:
        self.start_video()

        def emit(index: int):
            event = {
                "hook_event_name": "PostToolUse",
                "tool_use_id": f"concurrent-{index}",
                "tool_name": "Read",
                "tool_input": {"path": f"src/input-{index}.txt"},
                "tool_response": {"status": "ok"},
            }
            return self._process("hook", input_text=json.dumps(event))

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(emit, range(8)))

        self.assertTrue(all(result.returncode == 0 for result in results), [result.stderr for result in results])
        self.json_run("check", check=False)
        current = self.read_json(".agent/current_ticket.json")
        self.assertEqual(current["budget_used"]["tool_calls"], 8)
        self.assertEqual(current["budget_used"]["tool_calls_by_type"]["read"], 8)

    def test_state_store_lock_does_not_delete_a_successor_lock(self) -> None:
        state_path = self.root / ".agent" / "runtime" / "lock-pressure.json"
        lock_path = self.root / ".agent" / "runtime" / "lock-pressure.lock"
        write_json(state_path, {"revision": 0})

        def increment(_: int) -> None:
            for _ in range(40):
                with exclusive_file_lock(lock_path, timeout=1.0, stale_seconds=30.0):
                    state = load_json(state_path, {"revision": 0})
                    state["revision"] = int(state.get("revision", 0)) + 1
                    write_json(state_path, state)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(increment, range(8)))

        self.assertEqual(load_json(state_path, {})["revision"], 320)
        self.assertFalse(lock_path.exists())


if __name__ == "__main__":
    import unittest

    unittest.main()
