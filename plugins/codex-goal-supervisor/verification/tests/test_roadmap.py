from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from unittest import mock

try:
    from .helpers import HARNESS_ROOT, GoalCompassRepoCase
    from .test_goal_detect import detailed_goal_definition
except ImportError:
    from helpers import HARNESS_ROOT, GoalCompassRepoCase
    from test_goal_detect import detailed_goal_definition

from goal_compass_runtime import roadmap as roadmap_runtime


class RoadmapTests(GoalCompassRepoCase):
    def set_detailed_goal(self, definition: dict | None = None, *, check: bool = True) -> dict:
        definition = definition or detailed_goal_definition()
        path = self.root / "goal-definition.json"
        path.write_text(json.dumps(definition, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.json_run(
            "goal-set",
            "--text", definition["precise_goal"],
            "--definition-file", str(path),
            "--require-detailed",
            check=check,
        )

    def test_detailed_goal_requires_complete_route_before_goal_mode(self) -> None:
        definition = detailed_goal_definition()
        definition["process"]["nodes"][0]["actions"] = []

        result = self.set_detailed_goal(definition, check=False)

        self.assertEqual(result["status"], "GOAL_DEFINITION_INCOMPLETE")
        self.assertIn("process.nodes[0].actions", result["missing_fields"])
        self.assertFalse((self.root / ".agent/runtime/roadmap/server.json").exists())

    def test_goal_set_outputs_ready_roadmap_contract_without_test_server(self) -> None:
        result = self.set_detailed_goal()

        self.assertEqual(result["roadmap"]["status"], "READY_NOT_STARTED")
        self.assertTrue(result["roadmap"]["route_map_ready"])
        status = self.json_run("status")
        self.assertTrue(status["roadmap"]["route_map_ready"])
        self.assertEqual(status["roadmap"]["progress"]["total"], 2)

    def test_roadmap_snapshot_contains_route_contract_and_consumers(self) -> None:
        definition = detailed_goal_definition()
        definition["process"]["nodes"][0]["actions"][0] = {
            "action_id": "A1",
            "name": "validate identifiers",
            "inputs": ["lot metadata"],
            "outputs": ["validated identifiers"],
            "consumer": "measurement normalizer",
        }
        definition["process"]["nodes"][0]["affected_paths"] = ["src/evidence/**"]
        self.set_detailed_goal(definition)

        snapshot = self.json_run("roadmap", "--snapshot")

        first = snapshot["nodes"][0]
        self.assertTrue(snapshot["route_map_ready"])
        self.assertEqual(first["inputs"][0], "lot metadata")
        self.assertEqual(first["actions"][0]["outputs"], ["validated identifiers"])
        self.assertEqual(first["outputs"], ["validated lot evidence record"])
        self.assertIn("N2", first["consumers"])
        self.assertEqual(first["affected_paths"], ["src/evidence/**"])
        self.assertEqual(snapshot["edges"], [{"from": "N1", "to": "N2", "kind": "dependency"}])

    def test_roadmap_tracks_ready_active_completed_and_blocked_nodes(self) -> None:
        self.set_detailed_goal()
        initial = self.json_run("roadmap", "--snapshot")
        self.assertEqual([node["status"] for node in initial["nodes"]], ["READY", "BLOCKED"])

        self.json_run("convergence", "--start-segment", "N1")
        active = self.json_run("roadmap", "--snapshot")
        self.assertEqual([node["status"] for node in active["nodes"]], ["ACTIVE", "BLOCKED"])
        self.assertEqual(active["current_node_ids"], ["N1"])

        self.json_run("convergence", "--complete-segment", "N1", "--evidence-id", "evidence-intake-test")
        completed = self.json_run("roadmap", "--snapshot")
        self.assertEqual([node["status"] for node in completed["nodes"]], ["COMPLETED", "READY"])

    def test_roadmap_normalizes_dependency_description_with_exact_node_prefix(self) -> None:
        definition = detailed_goal_definition()
        definition["process"]["nodes"][1]["dependencies"] = ["N1 的已验证产出"]
        self.set_detailed_goal(definition)

        initial = self.json_run("roadmap", "--snapshot")
        self.assertEqual(initial["nodes"][1]["dependencies"], ["N1"])
        self.assertEqual(initial["edges"], [{"from": "N1", "to": "N2", "kind": "dependency"}])

        self.json_run("convergence", "--start-segment", "N1")
        self.json_run("convergence", "--complete-segment", "N1", "--evidence-id", "node-one-pass")
        completed = self.json_run("roadmap", "--snapshot")
        self.assertEqual(completed["nodes"][1]["status"], "READY")

    def test_optional_subnodes_are_not_required(self) -> None:
        result = self.set_detailed_goal()
        snapshot = self.json_run("roadmap", "--snapshot")

        self.assertTrue(result["detailed"])
        self.assertEqual(snapshot["nodes"][0]["subnodes"], [])

    def test_ordinary_goal_does_not_start_roadmap(self) -> None:
        result = self.json_run("goal-set", "--text", "Ship one focused local fix.")

        self.assertEqual(result["roadmap"]["status"], "NOT_REQUIRED")
        self.assertFalse((self.root / ".agent/runtime/roadmap/server.json").exists())

    def test_live_server_binds_loopback_and_reflects_segment_changes(self) -> None:
        old = os.environ.pop("GOAL_SUPERVISOR_DISABLE_ROADMAP_SERVER", None)
        try:
            result = self.set_detailed_goal()
            url = result["roadmap"]["url"]
            self.assertTrue(url.startswith("http://127.0.0.1:"), url)
            self.assertNotIn("shutdown_token", result["roadmap"])

            with urllib.request.urlopen(url + "api/roadmap", timeout=2) as response:
                initial = json.loads(response.read().decode("utf-8"))
            self.assertEqual(initial["current_node_ids"], [])

            self.json_run("convergence", "--start-segment", "N1")
            deadline = time.monotonic() + 2
            current = []
            while time.monotonic() < deadline:
                with urllib.request.urlopen(url + "api/roadmap", timeout=2) as response:
                    current = json.loads(response.read().decode("utf-8"))["current_node_ids"]
                if current == ["N1"]:
                    break
                time.sleep(0.05)
            self.assertEqual(current, ["N1"])

            with urllib.request.urlopen(url, timeout=2) as response:
                html = response.read().decode("utf-8")
            self.assertIn("Goal 技术路线", html)
            self.assertIn("仅在用户需要时细化", html)
        finally:
            self.cli("roadmap", "--stop", check=False)
            if old is None:
                os.environ["GOAL_SUPERVISOR_DISABLE_ROADMAP_SERVER"] = "1"
            else:
                os.environ["GOAL_SUPERVISOR_DISABLE_ROADMAP_SERVER"] = old

    def test_live_server_accepts_generated_token_with_leading_hyphen(self) -> None:
        old = os.environ.pop("GOAL_SUPERVISOR_DISABLE_ROADMAP_SERVER", None)
        try:
            with mock.patch("goal_compass_runtime.roadmap.secrets.token_urlsafe", return_value="-leading-token"):
                result = self.set_detailed_goal()
            self.assertEqual(result["roadmap"]["status"], "RUNNING")
            self.assertTrue(result["roadmap"]["url"].startswith("http://127.0.0.1:"))
        finally:
            self.cli("roadmap", "--stop", check=False)
            if old is None:
                os.environ["GOAL_SUPERVISOR_DISABLE_ROADMAP_SERVER"] = "1"
            else:
                os.environ["GOAL_SUPERVISOR_DISABLE_ROADMAP_SERVER"] = old

    def test_failed_server_start_terminates_delayed_child(self) -> None:
        class DelayedProcess:
            pid = 424242

            def __init__(self) -> None:
                self.terminated = False
                self.killed = False

            def poll(self):
                return 0 if self.terminated or self.killed else None

            def terminate(self) -> None:
                self.terminated = True

            def kill(self) -> None:
                self.killed = True

            def wait(self, timeout=None):
                return 0

        process = DelayedProcess()
        self.set_detailed_goal()
        old = os.environ.pop("GOAL_SUPERVISOR_DISABLE_ROADMAP_SERVER", None)
        try:
            with mock.patch.object(roadmap_runtime, "build_snapshot", return_value={"route_map_ready": True}), mock.patch.object(
                roadmap_runtime.subprocess, "Popen", return_value=process
            ):
                result = roadmap_runtime.ensure_server(self.root, wait_seconds=0.01)
        finally:
            if old is None:
                os.environ["GOAL_SUPERVISOR_DISABLE_ROADMAP_SERVER"] = "1"
            else:
                os.environ["GOAL_SUPERVISOR_DISABLE_ROADMAP_SERVER"] = old

        self.assertEqual(result["status"], "START_FAILED")
        self.assertTrue(process.terminated)
        self.assertFalse(process.killed)
        self.assertIn("bound-port metadata", result["reason"])

    def test_dashboard_is_offline_and_reads_only_project_projection(self) -> None:
        html = (HARNESS_ROOT / ".agent/goal_compass_runtime/roadmap.html").read_text(encoding="utf-8")

        self.assertIn('fetch("/api/roadmap"', html)
        self.assertNotIn("https://", html)
        self.assertNotIn("http://", html)
        self.assertNotIn("WebSocket", html)


if __name__ == "__main__":
    import unittest
    unittest.main()
