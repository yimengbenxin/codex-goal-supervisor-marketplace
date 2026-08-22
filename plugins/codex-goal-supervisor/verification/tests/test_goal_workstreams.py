from __future__ import annotations

import copy
import json
import sys
from unittest import mock

try:
    from .helpers import GOAL_COMPASS, GoalCompassRepoCase, run_cmd
except ImportError:
    from helpers import GOAL_COMPASS, GoalCompassRepoCase, run_cmd


PARENT_GOAL = "Deliver a modular local application with independently verifiable components and one integrated product path."


def detailed_definition(title: str) -> dict:
    return {
        "precise_goal": f"Implement and verify {title} for the parent product.",
        "problem_statement": f"{title} lacks a stable contract and machine evidence.",
        "current_state": f"{title} is planned but not accepted.",
        "desired_state": f"{title} produces validated outputs for its consumers.",
        "stakeholders": ["parent integration owner", "downstream module owner", "quality verifier"],
        "source_requirements": [
            "Preserve the parent contract.",
            "Return validated outputs to the parent.",
        ],
        "first_principles": [
            {
                "principle": "Every child output needs a consumer.",
                "rationale": "Unconsumed parallel output is noise.",
                "implications": ["Define the output first", "Validate the consumer-facing result"],
            },
            {
                "principle": "Parallel work shares one stable contract.",
                "rationale": "Schema drift causes integration rework.",
                "implications": ["Use the shared contract", "Return contract changes to the parent"],
            },
        ],
        "process": {
            "entry_conditions": ["The parent assignment and shared contracts are available"],
            "nodes": [
                {
                    "node_id": "C1",
                    "name": "Contract and reuse check",
                    "objective": f"Confirm the smallest route and contract for {title}.",
                    "inputs": ["parent assignment", "shared contracts", "current reusable tools"],
                    "actions": ["research reusable tools", "compare fit", "freeze input and output shapes"],
                    "outputs": ["bounded implementation route", "consumer-facing contract"],
                    "exit_criteria": ["the route does not change another workstream"],
                    "dependencies": [],
                    "execution_mode": "SERIAL",
                    "contribution_to_goal": "Prevents incompatible outputs and duplicate work.",
                    "timebox_hours": 2,
                    "reminder_interval_hours": 0,
                },
                {
                    "node_id": "C2",
                    "name": "Implementation and evidence",
                    "objective": f"Implement {title} and return validated evidence.",
                    "inputs": ["bounded implementation route", "consumer-facing contract"],
                    "actions": ["implement the smallest path", "run validation", "record evidence"],
                    "outputs": ["validated output", "validation evidence", "completion summary"],
                    "exit_criteria": ["validation passes", "declared outputs are available"],
                    "dependencies": ["C1"],
                    "execution_mode": "SERIAL",
                    "contribution_to_goal": "Produces one accepted input for parent integration.",
                    "timebox_hours": 4,
                    "reminder_interval_hours": 2,
                },
            ],
            "completion_conditions": ["Validated outputs and evidence are returned to the parent"],
        },
        "deliverables": [
            {
                "name": f"{title} output package",
                "description": "Bounded implementation and evidence.",
                "format": "project files plus machine-readable evidence",
                "consumer": "parent integration owner",
                "acceptance": ["validation passes", "outputs match the shared contract"],
            }
        ],
        "final_acceptance": [
            {
                "criterion": f"{title} produces its declared output.",
                "evidence": "validation result and output reference",
                "validation_method": "run the assigned validation command",
            }
        ],
        "constraints": ["Do not rewrite the parent North Star", "Respect workstream paths"],
        "non_goals": ["Unrequested generalization", "Unrelated modules"],
        "assumptions": ["The parent-provided shared contract is current at activation time"],
        "open_questions": [],
        "planning_research": {
            "completed": True,
            "researched_at": "2026-08-22T00:00:00Z",
            "tool_sources_reviewed": 2,
            "article_sources_reviewed": 1,
            "refresh_interval_hours": 24,
            "reusable_candidate_found": False,
            "no_suitable_reuse_reason": "Reviewed candidates do not satisfy the local contract and validation.",
        },
    }


class GoalWorkstreamTests(GoalCompassRepoCase):
    def setUp(self) -> None:
        super().setUp()
        catalog = self.read_json(".agent/validation_catalog.json")
        for validation_id in ("module_alpha_pass", "module_beta_pass", "integration_pass"):
            catalog[validation_id] = {
                "cmd": "{python} -c \"import sys; sys.exit(0)\"",
                "description": "Deterministic generic workstream validation.",
                "timeout_sec": 8,
            }
        self.write_json(".agent/validation_catalog.json", catalog)
        self.write_json("parent-goal.json", detailed_definition("the complete modular product path"))
        self.json_run(
            "goal-set", "--text", PARENT_GOAL,
            "--definition-file", "parent-goal.json", "--require-detailed",
        )

    def plan(self) -> dict:
        return {
            "parent_north_star_goal": PARENT_GOAL,
            "fanout_reason": "Two independent modules can produce separately validated outputs before bounded integration.",
            "integration_owner": "parent Codex thread",
            "expected_net_benefit": {
                "serial_hours": 14,
                "parallel_hours": 6,
                "coordination_hours": 1,
                "integration_hours": 2,
            },
            "shared_contracts": [
                {
                    "contract_id": "result-contract",
                    "subject": "module result envelope",
                    "rule": "Every result uses one versioned identifier, status field, and evidence reference.",
                    "consumers": ["module-alpha", "module-beta", "integration"],
                }
            ],
            "workstreams": [
                {
                    "workstream_id": "module-alpha",
                    "title": "Module Alpha",
                    "responsibility": "Implement the alpha result producer and its focused validation.",
                    "parent_contribution": "Produces one input consumed by final integration.",
                    "execution_mode": "PARALLEL",
                    "parallel_group": "foundation",
                    "estimated_hours": 5,
                    "dependencies": [],
                    "inputs": ["result-contract"],
                    "outputs": ["alpha result envelope"],
                    "consumers": ["integration"],
                    "writable_paths": ["src/module_alpha/**", "tests/module_alpha/**"],
                    "read_dependencies": ["contracts/result.json"],
                    "immutable_paths": ["contracts/result.json"],
                    "validation_ids": ["module_alpha_pass"],
                    "shared_contract_ids": ["result-contract"],
                },
                {
                    "workstream_id": "module-beta",
                    "title": "Module Beta",
                    "responsibility": "Implement the beta result producer and its focused validation.",
                    "parent_contribution": "Produces the second input consumed by final integration.",
                    "execution_mode": "PARALLEL",
                    "parallel_group": "foundation",
                    "estimated_hours": 6,
                    "dependencies": [],
                    "inputs": ["result-contract"],
                    "outputs": ["beta result envelope"],
                    "consumers": ["integration"],
                    "writable_paths": ["src/module_beta/**", "tests/module_beta/**"],
                    "read_dependencies": ["contracts/result.json"],
                    "immutable_paths": ["contracts/result.json"],
                    "validation_ids": ["module_beta_pass"],
                    "shared_contract_ids": ["result-contract"],
                },
                {
                    "workstream_id": "integration",
                    "title": "Final integration",
                    "responsibility": "Consume validated alpha output and prove the parent-facing integration path.",
                    "parent_contribution": "Turns independent outputs into one accepted product route.",
                    "execution_mode": "SERIAL",
                    "parallel_group": "",
                    "estimated_hours": 3,
                    "dependencies": ["module-alpha"],
                    "inputs": ["alpha result envelope", "result-contract"],
                    "outputs": ["integrated product result"],
                    "consumers": ["parent acceptance"],
                    "writable_paths": ["src/integration/**", "tests/integration/**"],
                    "read_dependencies": ["src/module_alpha/**"],
                    "immutable_paths": ["contracts/result.json"],
                    "validation_ids": ["integration_pass"],
                    "shared_contract_ids": ["result-contract"],
                },
            ],
            "final_integration": {
                "inputs": ["alpha result envelope", "beta result envelope", "integrated product result"],
                "validation_ids": ["integration_pass"],
                "acceptance": "The parent path consumes both module results through the shared contract.",
            },
        }

    def save_plan(self, plan: dict | None = None) -> None:
        self.write_json("workstreams.json", plan or self.plan())

    def plan_workstreams(self, plan: dict | None = None) -> dict:
        self.save_plan(plan)
        return self.json_run("goal-workstreams", "--plan-file", "workstreams.json")

    def activate(self, workstream_id: str = "module-alpha", thread_id: str = "thread-alpha") -> dict:
        self.write_json("child-goal.json", detailed_definition(f"the {workstream_id} workstream"))
        native_result = {
            "ok": True,
            "operation": "CREATED",
            "thread_id": thread_id,
            "previous": None,
            "current": {"status": "active"},
            "verified": True,
        }
        with mock.patch.object(
            GOAL_COMPASS,
            "native_goal_bridge_availability",
            return_value={"available": True, "thread_id": thread_id, "executable": "fake"},
        ), mock.patch.object(GOAL_COMPASS, "replace_native_goal", return_value=native_result):
            return self.json_run(
                "goal-workstreams", "--set-goal", workstream_id,
                "--definition-file", "child-goal.json",
            )

    def test_parent_plan_returns_only_dependency_ready_thread_launches(self) -> None:
        result = self.plan_workstreams()
        self.assertEqual(result["status"], "WORKSTREAM_PLAN_READY")
        self.assertEqual(
            {row["workstream_id"] for row in result["thread_launches"]},
            {"module-alpha", "module-beta"},
        )
        self.assertTrue(all(row["required_action"] == "parent_codex_create_thread" for row in result["thread_launches"]))

    def test_parallel_workstreams_reject_writable_overlap(self) -> None:
        plan = self.plan()
        plan["workstreams"][1]["writable_paths"] = ["src/module_alpha/internal/**"]
        self.save_plan(plan)
        result = self.json_run("goal-workstreams", "--plan-file", "workstreams.json", check=False)
        self.assertEqual(result["status"], "WORKSTREAM_PLAN_INVALID")
        self.assertTrue(any("overlap writable paths" in error for error in result["errors"]))

    def test_dependency_inside_parallel_group_is_rejected(self) -> None:
        plan = self.plan()
        plan["workstreams"][1]["dependencies"] = ["module-alpha"]
        self.save_plan(plan)
        result = self.json_run("goal-workstreams", "--plan-file", "workstreams.json", check=False)
        self.assertEqual(result["status"], "WORKSTREAM_PLAN_INVALID")
        self.assertTrue(any("cannot be inside one parallel group" in error for error in result["errors"]))

    def test_plan_requires_positive_net_benefit(self) -> None:
        plan = self.plan()
        plan["expected_net_benefit"]["coordination_hours"] = 10
        self.save_plan(plan)
        result = self.json_run("goal-workstreams", "--plan-file", "workstreams.json", check=False)
        self.assertEqual(result["status"], "WORKSTREAM_PLAN_INVALID")
        self.assertTrue(any("must save more time" in error for error in result["errors"]))

    def test_plan_rejects_unregistered_validation_before_fanout(self) -> None:
        catalog = self.read_json(".agent/validation_catalog.json")
        catalog.pop("module_beta_pass")
        self.write_json(".agent/validation_catalog.json", catalog)
        self.save_plan()

        result = self.json_run("goal-workstreams", "--plan-file", "workstreams.json", check=False)

        self.assertEqual(result["status"], "WORKSTREAM_PLAN_INVALID")
        self.assertFalse(result["state_changed"])
        self.assertTrue(any(
            "workstream module-beta references validation_catalog id not ready before fanout: module_beta_pass" in error
            for error in result["errors"]
        ))
        self.assertFalse((self.root / ".agent/runtime/goal_workstreams.json").exists())

    def test_child_goal_sync_does_not_rewrite_parent_north_star(self) -> None:
        self.plan_workstreams()
        before = (self.root / ".agent/north_star_goal.json").read_bytes()
        result = self.activate()
        after = (self.root / ".agent/north_star_goal.json").read_bytes()
        self.assertEqual(result["status"], "CHILD_GOAL_ACTIVE")
        self.assertEqual(before, after)
        state = self.read_json(".agent/runtime/goal_workstreams.json")
        self.assertEqual(state["workstreams"]["module-alpha"]["thread_id"], "thread-alpha")

    def test_workstream_cannot_bind_to_two_child_threads(self) -> None:
        self.plan_workstreams()
        self.activate(thread_id="thread-alpha")
        self.write_json("child-goal.json", detailed_definition("the module-alpha workstream"))
        with mock.patch.object(
            GOAL_COMPASS,
            "native_goal_bridge_availability",
            return_value={"available": True, "thread_id": "thread-beta", "executable": "fake"},
        ), mock.patch.object(GOAL_COMPASS, "replace_native_goal") as native_sync:
            result = self.json_run(
                "goal-workstreams", "--set-goal", "module-alpha",
                "--definition-file", "child-goal.json", check=False,
            )
        self.assertEqual(result["status"], "WORKSTREAM_ALREADY_BOUND")
        native_sync.assert_not_called()
        state = self.read_json(".agent/runtime/goal_workstreams.json")
        self.assertEqual(state["workstreams"]["module-alpha"]["thread_id"], "thread-alpha")

    def test_child_goal_rejects_parent_goal_change(self) -> None:
        self.plan_workstreams()
        north = self.read_json(".agent/north_star_goal.json")
        north["goal"] = "A different durable product direction."
        self.write_json(".agent/north_star_goal.json", north)
        self.write_json("child-goal.json", detailed_definition("the module-alpha workstream"))
        result = self.json_run(
            "goal-workstreams", "--set-goal", "module-alpha",
            "--definition-file", "child-goal.json", check=False,
        )
        self.assertEqual(result["status"], "PARENT_GOAL_CHANGED")

    def test_child_completion_runs_validation_and_unlocks_dependency(self) -> None:
        self.plan_workstreams()
        self.activate()
        native_result = {
            "ok": True,
            "operation": "STATUS_REFRESHED",
            "thread_id": "thread-alpha",
            "previous": {"status": "active"},
            "current": {"status": "complete"},
            "verified": True,
        }
        with mock.patch.object(
            GOAL_COMPASS,
            "native_goal_bridge_availability",
            return_value={"available": True, "thread_id": "thread-alpha", "executable": "fake"},
        ), mock.patch.object(GOAL_COMPASS, "replace_native_goal", return_value=native_result):
            result = self.json_run(
                "goal-workstreams", "--complete", "module-alpha",
                "--evidence-id", "alpha-validation-evidence",
                "--summary", "Alpha output and its validation evidence were returned to the parent.",
            )
        self.assertEqual(result["status"], "WORKSTREAM_COMPLETE")
        self.assertTrue(result["validation_results"][0]["ok"])
        self.assertIn("integration", {row["workstream_id"] for row in result["thread_launches"]})

    def test_child_context_restores_parent_alignment_after_compaction(self) -> None:
        self.plan_workstreams()
        self.activate()
        hook = self.root / ".agent/goal_compass_runtime/project_hook.py"
        event = {"hook_event_name": "PostCompact", "session_id": "thread-alpha"}
        result = run_cmd([sys.executable, str(hook)], self.root, input_text=json.dumps(event), check=True)
        payload = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertIn("Goal workstream module-alpha", payload["additionalContext"])
        self.assertIn(PARENT_GOAL, payload["additionalContext"])

    def test_parent_goal_change_blocks_only_child_product_writes(self) -> None:
        self.plan_workstreams()
        self.activate()
        north = self.read_json(".agent/north_star_goal.json")
        north["goal_mode_objective"] += " changed"
        self.write_json(".agent/north_star_goal.json", north)
        hook = self.root / ".agent/goal_compass_runtime/project_hook.py"
        event = {
            "hook_event_name": "PreToolUse",
            "session_id": "thread-alpha",
            "tool_name": "write_file",
            "tool_input": {"path": "src/module_alpha/result.py"},
        }
        result = run_cmd([sys.executable, str(hook)], self.root, input_text=json.dumps(event), check=True)
        payload = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(payload["permissionDecision"], "deny")
        self.assertIn("parent North Star or detailed Goal changed", payload["permissionDecisionReason"])


if __name__ == "__main__":
    import unittest

    unittest.main()
