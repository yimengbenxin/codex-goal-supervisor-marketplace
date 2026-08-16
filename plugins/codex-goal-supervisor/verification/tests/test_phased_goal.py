from __future__ import annotations

import copy
import json
import sys
from unittest import mock

try:
    from .helpers import GOAL_COMPASS, DEFAULT_TIMEOUT, GoalCompassRepoCase, pushd, run_cmd
    from .test_goal_detect import detailed_goal_definition
except ImportError:
    from helpers import GOAL_COMPASS, DEFAULT_TIMEOUT, GoalCompassRepoCase, pushd, run_cmd
    from test_goal_detect import detailed_goal_definition


NORTH_STAR = "Build an AI automatic video generation system."


class PhasedGoalTests(GoalCompassRepoCase):
    def setUp(self) -> None:
        super().setUp()
        self.goal_video()
        catalog = self.read_json(".agent/validation_catalog.json")
        catalog.update({
            "phase_one_pass": {
                "cmd": "{python} -c \"import sys; sys.exit(0)\"",
                "description": "Phase one deterministic pass.",
                "timeout_sec": 8,
            },
            "phase_two_pass": {
                "cmd": "{python} -c \"import sys; sys.exit(0)\"",
                "description": "Phase two deterministic pass.",
                "timeout_sec": 8,
            },
            "phase_fail": {
                "cmd": "{python} -c \"import sys; sys.exit(1)\"",
                "description": "Phase deterministic failure.",
                "timeout_sec": 8,
            },
        })
        self.write_json(".agent/validation_catalog.json", catalog)

    def outline(self) -> dict:
        return {
            "north_star_goal": NORTH_STAR,
            "planning_research": {
                "completed": True,
                "performed_at": "2026-08-16T00:00:00+00:00",
                "queries": ["open source prompt to video orchestration project architecture"],
                "sources": ["https://example.test/program-outline"],
                "reuse_decision": "Reuse the standard-library job boundary; do not adopt a workflow platform.",
            },
            "phases": [
                {
                    "phase_id": "P1",
                    "title": "Mock artifact path",
                    "outcome": "Prove prompt to deterministic mock video artifact end to end.",
                    "dependencies": [],
                    "outputs": ["mock artifact record"],
                    "consumers": ["routing phase"],
                    "contribution_to_goal": "Proves the smallest executable product path.",
                    "estimated_hours": 4,
                },
                {
                    "phase_id": "P2",
                    "title": "Routing integration",
                    "outcome": "Route a validated prompt through the mock adapter contract.",
                    "dependencies": ["P1"],
                    "outputs": ["routing result"],
                    "consumers": ["project regression"],
                    "contribution_to_goal": "Connects the proven artifact path to the product route.",
                    "estimated_hours": 6,
                },
            ],
            "shared_contracts": ["artifact paths are project-relative strings"],
            "final_acceptance": ["the project regression proves prompt to routed video artifact"],
        }

    def phase(self, phase_id: str, validation_id: str, *, hours: int | float | None = None) -> dict:
        definition = detailed_goal_definition()
        title = "mock video artifact pipeline" if phase_id == "P1" else "mock video routing integration"
        definition["precise_goal"] = f"Build and verify the {title} as the current project phase."
        definition["problem_statement"] = f"The {title} has not yet been proven with deterministic machine evidence."
        definition["current_state"] = f"The project outline identifies {phase_id}, but its business outcome is not yet accepted."
        definition["desired_state"] = f"The {title} passes its phase validation and produces the declared downstream output."
        research = {
            "completed": True,
            "researched_at": "2026-08-16T01:00:00Z" if phase_id == "P1" else "2026-08-16T06:00:00Z",
            "queries": [f"open source {title} implementation"],
            "sources": [f"https://example.test/{phase_id.lower()}-research"],
            "tool_sources_reviewed": 2,
            "article_sources_reviewed": 1,
            "refresh_interval_hours": 24,
            "reusable_candidate_found": False,
            "no_suitable_reuse_reason": f"No reviewed candidate satisfies the bounded {phase_id} contract and local validation.",
        }
        definition["planning_research"] = research
        listed = next(row for row in self.outline()["phases"] if row["phase_id"] == phase_id)
        return {
            "phase_id": phase_id,
            "estimated_hours": listed["estimated_hours"] if hours is None else hours,
            "dependencies": list(listed["dependencies"]),
            "validation_ids": [validation_id],
            "planning_research": research,
            "goal_definition": definition,
        }

    def write_contracts(self, phase: dict, outline: dict | None = None) -> None:
        self.write_json("program-outline.json", outline or self.outline())
        self.write_json("phase.json", phase)

    def start_structured_phase(self, phase: dict | None = None, outline: dict | None = None) -> dict:
        self.write_contracts(phase or self.phase("P1", "phase_one_pass"), outline)
        return self.json_run(
            "phase-set",
            "--outline-file", "program-outline.json",
            "--definition-file", "phase.json",
        )

    def test_structured_phase_set_projects_only_current_phase_goal(self) -> None:
        result = self.start_structured_phase()
        stored = self.read_json(".agent/program_phase.json")
        north = self.read_json(".agent/north_star_goal.json")

        self.assertEqual(stored["mode"], "STRUCTURED_PHASED_GOAL")
        self.assertEqual(stored["phase_id"], "P1")
        self.assertEqual(result["goal_mode_objective"], north["goal_mode_objective"])
        self.assertEqual(result["native_goal_sync"]["objective_chars"], len(result["goal_mode_objective"]))
        self.assertIn("mock video artifact pipeline", result["goal_mode_objective"])
        self.assertNotIn("project regression proves prompt", result["goal_mode_objective"])
        self.assertEqual(self.json_run("status")["program_phase"]["estimated_hours"], 4.0)

    def test_phase_set_records_replaced_native_goal_without_fake_completion(self) -> None:
        self.write_contracts(self.phase("P1", "phase_one_pass"))
        previous_project = self.read_json(".agent/north_star_goal.json")
        native_result = {
            "ok": True,
            "status": "SYNCED",
            "operation": "REPLACED",
            "thread_id": "test-thread",
            "previous": {
                "objective": "old blocked program objective",
                "status": "blocked",
                "tokensUsed": 77,
                "timeUsedSeconds": 31,
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
                "phase-set",
                "--outline-file", "program-outline.json",
                "--definition-file", "phase.json",
            )

        self.assertEqual(
            result["native_goal_sync"]["transition"],
            "SUPERSEDED_BY_PROGRAM_PHASE_ACTIVATION",
        )
        history = [
            json.loads(line)
            for line in (self.root / ".agent/goal_replacement_history.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(history[-1]["previous_status"], "blocked")
        self.assertFalse(history[-1]["objective_achieved"])
        self.assertEqual(history[-1]["previous_project_snapshot"]["goal"], previous_project["goal"])

    def test_phase_set_accepts_documented_aliases_without_schema_guessing(self) -> None:
        outline = self.outline()
        outline["north_star"] = outline.pop("north_star_goal")
        outline["shared_contract"] = outline.pop("shared_contracts")
        outline["total_acceptance"] = outline.pop("final_acceptance")
        for row in outline["phases"]:
            row["id"] = row.pop("phase_id")
            row["name"] = row.pop("title")
            row["business_result"] = row.pop("outcome")
            row["depends_on"] = row.pop("dependencies")

        phase = self.phase("P1", "phase_one_pass")
        phase["id"] = phase.pop("phase_id")
        phase["timebox_hours"] = phase.pop("estimated_hours")
        phase["depends_on"] = phase.pop("dependencies")
        phase["validation_catalog_ids"] = phase.pop("validation_ids")
        phase["detailed_goal_definition"] = phase.pop("goal_definition")
        self.write_contracts(phase, outline)

        result = self.json_run(
            "phase-set",
            "--outline-file", "program-outline.json",
            "--definition-file", "phase.json",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["program_phase"]["phase_id"], "P1")
        self.assertEqual(result["native_goal_sync"]["objective_chars"], len(result["goal_mode_objective"]))

    def test_phase_contract_error_points_to_installed_canonical_shape(self) -> None:
        phase = self.phase("P1", "phase_one_pass")
        phase.pop("goal_definition")
        self.write_contracts(phase)

        result = self.json_run(
            "phase-set",
            "--outline-file", "program-outline.json",
            "--definition-file", "phase.json",
            check=False,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["contract_reference"],
            ".agent/docs/README_GOAL_COMPASS.md#structured-phased-goal-input",
        )

    def test_authored_phase_goal_compresses_complete_definition_without_truncation(self) -> None:
        phase = self.phase("P1", "phase_one_pass")
        phase["goal_definition"]["precise_goal"] += " Preserve the complete structured execution contract." * 80
        authored = ("目标：完成当前 mock video artifact phase，并保持模块、输入输出、依赖、验收与复用决定可执行。" * 80)[:2400]
        phase["goal_mode_objective"] = authored
        self.write_contracts(phase)

        result = self.json_run(
            "phase-set",
            "--outline-file", "program-outline.json",
            "--definition-file", "phase.json",
        )

        self.assertEqual(result["goal_mode_objective"], authored)
        self.assertEqual(result["native_goal_sync"]["objective_chars"], len(authored))
        self.assertEqual(
            self.read_json(".agent/program_phase.json")["current_phase"]["goal_definition"]["quality"],
            "STRUCTURED_DETAILED",
        )

    def test_long_authored_phase_goal_cannot_replace_missing_structure(self) -> None:
        phase = self.phase("P1", "phase_one_pass")
        phase["goal_definition"] = {"precise_goal": "A long objective is not a structured phase contract."}
        phase["goal_mode_objective"] = ("目标正文不能替代结构化字段。" * 200)[:2200]
        self.write_contracts(phase)

        result = self.json_run(
            "phase-set",
            "--outline-file", "program-outline.json",
            "--definition-file", "phase.json",
            check=False,
        )

        self.assertFalse(result["ok"])
        self.assertIn("phase goal_definition must be STRUCTURED_DETAILED", result["errors"])

    def test_phase_estimate_must_be_between_two_and_twenty_four_hours(self) -> None:
        for hours in (1, 25):
            outline = self.outline()
            outline["phases"][0]["estimated_hours"] = hours
            self.write_contracts(self.phase("P1", "phase_one_pass", hours=hours), outline)
            result = self.json_run(
                "phase-set",
                "--outline-file", "program-outline.json",
                "--definition-file", "phase.json",
                check=False,
            )
            self.assertFalse(result["ok"])
            self.assertTrue(any("between 2 and 24" in error for error in result["errors"]))

    def test_outline_rejects_unknown_and_self_dependencies(self) -> None:
        outline = self.outline()
        outline["phases"][0]["dependencies"] = ["P1"]
        outline["phases"][1]["dependencies"] = ["P1", "P9"]
        self.write_contracts(self.phase("P1", "phase_one_pass"), outline)

        result = self.json_run(
            "phase-set",
            "--outline-file", "program-outline.json",
            "--definition-file", "phase.json",
            check=False,
        )

        self.assertFalse(result["ok"])
        self.assertIn("phase P1 cannot depend on itself", result["errors"])
        self.assertIn("phase P2 has unknown dependencies: P9", result["errors"])

    def test_phase_research_must_be_distinct_from_outline_research(self) -> None:
        outline = self.outline()
        phase = self.phase("P1", "phase_one_pass")
        phase["planning_research"] = copy.deepcopy(outline["planning_research"])
        phase["goal_definition"]["planning_research"] = copy.deepcopy(outline["planning_research"])
        self.write_contracts(phase, outline)

        result = self.json_run(
            "phase-set",
            "--outline-file", "program-outline.json",
            "--definition-file", "phase.json",
            check=False,
        )

        self.assertFalse(result["ok"])
        self.assertIn("distinct from program-outline research", " ".join(result["errors"]))

    def test_phase_validation_failure_cannot_complete(self) -> None:
        self.start_structured_phase(self.phase("P1", "phase_fail"))

        result = self.json_run("phase-complete", "--reason", "Attempted phase close", check=False)

        self.assertEqual(result["status"], "PHASE_VALIDATION_FAILED")
        self.assertEqual(self.read_json(".agent/program_phase.json")["status"], "ACTIVE")
        self.assertEqual(result["validation"]["status"], "FAIL")

    def test_phase_must_complete_before_dependency_ready_advance(self) -> None:
        self.start_structured_phase()
        self.write_json("phase-two.json", self.phase("P2", "phase_two_pass"))

        blocked = self.json_run(
            "phase-advance", "--definition-file", "phase-two.json", "--reason", "P1 done",
            check=False,
        )
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["required_action"], "phase-complete")

        completed = self.json_run("phase-complete", "--reason", "P1 validation passed")
        advanced = self.json_run(
            "phase-advance", "--definition-file", "phase-two.json", "--reason", "P1 validated",
        )

        self.assertEqual(completed["program_phase"]["status"], "COMPLETED")
        self.assertEqual(advanced["program_phase"]["phase_id"], "P2")
        self.assertEqual(advanced["native_goal_sync"]["status"], "CREATE_REQUIRED")
        self.assertEqual(advanced["goal_mode_objective"], self.read_json(".agent/north_star_goal.json")["goal_mode_objective"])
        self.assertEqual(advanced["program_phase"]["completed_phase_ids"], ["P1"])

    def test_phase_advance_replaces_native_goal_after_validation(self) -> None:
        self.start_structured_phase()
        previous_objective = self.read_json(".agent/north_star_goal.json")["goal_mode_objective"]
        self.json_run("phase-complete", "--reason", "P1 validation passed")
        self.write_json("phase-two.json", self.phase("P2", "phase_two_pass"))

        captured: dict[str, str] = {}

        def replace(objective: str, **_: object) -> dict:
            captured["objective"] = objective
            return {
                "ok": True,
                "status": "SYNCED",
                "operation": "REPLACED",
                "thread_id": "test-thread",
                "previous": {
                    "objective": previous_objective,
                    "status": "complete",
                    "tokensUsed": 50,
                    "timeUsedSeconds": 20,
                },
                "current": {"objective": objective, "status": "active"},
                "verified": True,
            }

        with mock.patch.object(
            GOAL_COMPASS,
            "native_goal_bridge_availability",
            return_value={"available": True, "thread_id": "test-thread", "executable": "fake"},
        ), mock.patch.object(GOAL_COMPASS, "replace_native_goal", side_effect=replace):
            advanced = self.json_run(
                "phase-advance", "--definition-file", "phase-two.json", "--reason", "P1 validated",
            )

        self.assertEqual(advanced["native_goal_sync"]["status"], "SYNCED")
        self.assertEqual(captured["objective"], advanced["goal_mode_objective"])
        history = [
            json.loads(line)
            for line in (self.root / ".agent/goal_replacement_history.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(history[-1]["transition"], "PHASE_ADVANCE_AFTER_VALIDATION")
        self.assertTrue(history[-1]["objective_achieved"])

    def test_phase_telemetry_records_product_action_and_validation(self) -> None:
        self.start_structured_phase()
        write_event = {
            "hook_event_name": "PostToolUse",
            "tool_use_id": "phase-write",
            "tool_name": "apply_patch",
            "tool_input": {"patch": "*** Begin Patch\n*** Add File: src/video/mock/phase.ts\n+x\n*** End Patch"},
        }
        validation_event = {
            "hook_event_name": "PostToolUse",
            "tool_use_id": "phase-validation",
            "tool_name": "exec_command",
            "tool_input": {"cmd": "python -m unittest verification.tests.test_phase"},
        }
        with pushd(self.root):
            self.assertEqual(GOAL_COMPASS.hook_post(write_event), 0)
            self.assertEqual(GOAL_COMPASS.hook_post(validation_event), 0)

        telemetry = self.read_json(".agent/program_phase.json")["current_phase"]["telemetry"]
        self.assertTrue(telemetry["first_product_action_at"])
        self.assertTrue(telemetry["first_valid_evidence_at"])
        self.assertTrue(telemetry["deadline_at"])

    def test_lightweight_project_hook_records_structured_phase_telemetry_without_ticket(self) -> None:
        self.start_structured_phase()
        hook = self.root / ".agent" / "goal_compass_runtime" / "project_hook.py"
        events = (
            {
                "hook_event_name": "PostToolUse",
                "tool_use_id": "lightweight-phase-write",
                "tool_name": "apply_patch",
                "tool_input": {
                    "patch": "*** Begin Patch\n*** Add File: src/video/mock/phase.ts\n+x\n*** End Patch"
                },
            },
            {
                "hook_event_name": "PostToolUse",
                "tool_use_id": "lightweight-phase-validation",
                "tool_name": "exec_command",
                "tool_input": {"cmd": "python -m unittest verification.tests.test_phase"},
                "tool_response": {"exit_code": 0},
            },
        )
        for event in events:
            run_cmd(
                [sys.executable, str(hook)],
                cwd=self.root,
                timeout=DEFAULT_TIMEOUT,
                check=True,
                input_text=json.dumps(event),
            )

        telemetry = self.read_json(".agent/program_phase.json")["current_phase"]["telemetry"]
        self.assertTrue(telemetry["first_product_action_at"])
        self.assertTrue(telemetry["first_valid_evidence_at"])

    def test_successful_phase_complete_records_first_valid_evidence(self) -> None:
        self.start_structured_phase()

        completed = self.json_run("phase-complete", "--reason", "Catalog validation passed")

        self.assertTrue(completed["ok"])
        telemetry = self.read_json(".agent/program_phase.json")["current_phase"]["telemetry"]
        self.assertTrue(telemetry["first_valid_evidence_at"])
        self.assertIsNone(telemetry["first_product_action_at"])

    def test_legacy_phase_commands_remain_compatible(self) -> None:
        set_result = self.json_run(
            "phase-set", "--id", "LEGACY", "--goal", "Keep legacy phase behavior", "--exit-criterion", "tests pass",
        )
        completed = self.json_run("phase-complete", "--reason", "Legacy evidence passed")

        self.assertEqual(set_result["program_phase"]["status"], "ACTIVE")
        self.assertEqual(completed["program_phase"]["status"], "COMPLETED")


if __name__ == "__main__":
    import unittest
    unittest.main()
