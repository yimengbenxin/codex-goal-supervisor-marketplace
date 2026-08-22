from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

try:
    from .helpers import GOAL_COMPASS, PLUGIN_ROOT, GoalCompassRepoCase, pushd
except ImportError:
    from helpers import GOAL_COMPASS, PLUGIN_ROOT, GoalCompassRepoCase, pushd

from goal_compass_runtime.convergence import (
    apply_observation,
    auto_start_segment,
    empty_state,
    external_prerequisite_stop_review,
    goal_contract_fingerprint,
    judge_trigger,
    record_blocker_scope_review,
    record_collaboration_round,
    record_iteration,
    refresh,
    start_segment,
    complete_segment,
    due_segment_reminder,
)
from goal_compass_runtime.llm_judge import invoke


class ConvergenceStateTests(GoalCompassRepoCase):
    def certifiable_goal(self) -> None:
        self.goal_video()
        north = self.read_json(".agent/north_star_goal.json")
        north["goal_definition"] = {
            "quality": "STRUCTURED_DETAILED",
            "success_criteria": ["The end-to-end mock video pipeline passes its registered regression."],
            "final_acceptance": [{
                "criterion": "The end-to-end mock video pipeline passes its registered regression.",
                "evidence": "mock_video_pipeline_test",
                "validation_method": "validation_catalog",
            }],
            "process": {"nodes": []},
        }
        self.write_json(".agent/north_star_goal.json", north)

    def test_init_writes_convergence_state_and_judge_schema(self) -> None:
        self.assertTrue((self.root / ".agent/runtime/convergence_state.json").is_file())
        schema = self.read_json(".agent/protocols/llm_judge.schema.json")
        self.assertIn("CONFIRM_TARGETED_RAIL", schema["properties"]["verdict"]["enum"])

    def test_goal_change_supersedes_old_segments_and_resets_goal_scoped_progress(self) -> None:
        old_north = {
            "goal": "Deliver the old product direction.",
            "goal_mode_objective": "Old detailed objective",
            "goal_definition": {
                "process": {"nodes": [{
                    "node_id": "OLD",
                    "name": "Old route",
                    "objective": "Finish the old route.",
                    "dependencies": [],
                    "inputs": ["old input"],
                    "actions": ["old action"],
                    "outputs": ["old output"],
                    "exit_criteria": ["old evidence"],
                    "execution_mode": "SERIAL",
                    "contribution_to_goal": "old contribution",
                    "timebox_hours": 2,
                    "reminder_interval_hours": 0,
                }]},
            },
        }
        state = refresh(
            empty_state(), north_star=old_north, phase={}, ticket={},
            updated_at="2026-08-22T00:00:00+00:00",
        )
        state, _ = start_segment(state, node_id="OLD", observed_at="2026-08-22T00:01:00+00:00")
        state["activity"]["writes"] = 12
        state["progress"]["evidence_count"] = 3

        new_north = {
            "goal": "Deliver the new product direction.",
            "goal_mode_objective": "New detailed objective",
            "goal_definition": {
                "process": {"nodes": [{
                    "node_id": "NEW",
                    "name": "New route",
                    "objective": "Finish the new route.",
                    "dependencies": [],
                    "inputs": ["new input"],
                    "actions": ["new action"],
                    "outputs": ["new output"],
                    "exit_criteria": ["new evidence"],
                    "execution_mode": "SERIAL",
                    "contribution_to_goal": "new contribution",
                    "timebox_hours": 2,
                    "reminder_interval_hours": 0,
                }]},
            },
        }
        changed = refresh(
            state, north_star=new_north, phase={}, ticket={},
            updated_at="2026-08-22T01:00:00+00:00",
        )

        self.assertEqual(changed["segments"]["active"], {})
        self.assertEqual(changed["schema_version"], "1.1")
        self.assertEqual(changed["segments"]["completed"], [])
        self.assertEqual(changed["segments"]["superseded"][-1]["node_id"], "OLD")
        self.assertEqual(changed["segments"]["superseded"][-1]["status"], "SUPERSEDED")
        self.assertEqual(changed["goal_history"][-1]["transition"], "SUPERSEDED_BY_GOAL_CHANGE")
        self.assertEqual(changed["activity"]["writes"], 0)
        self.assertEqual(changed["progress"]["evidence_count"], 0)
        self.assertEqual(changed["goal_stack"]["l0_final_goal"], "Deliver the new product direction.")

    def test_goal_certificate_fingerprint_ignores_read_time_defaults_but_not_contract_change(self) -> None:
        raw = {
            "confirmed": True,
            "goal": "Deliver the verified product.",
            "goal_mode_objective": "Detailed verified product objective.",
            "anti_goals": [],
            "goal_definition": {
                "non_goals": ["Do not build the unrelated marketplace."],
                "final_acceptance": [{"criterion": "Project regression passes."}],
            },
        }
        enriched = dict(raw)
        enriched["source"] = "read_time_compatibility"
        enriched["confirmed_at"] = "2026-08-22T00:00:00+00:00"
        enriched["anti_goals"] = ["Do not build the unrelated marketplace."]

        self.assertEqual(goal_contract_fingerprint(raw), goal_contract_fingerprint(enriched))
        changed = json.loads(json.dumps(raw))
        changed["goal_mode_objective"] = "A materially changed objective."
        self.assertNotEqual(goal_contract_fingerprint(raw), goal_contract_fingerprint(changed))

    def test_successful_hook_refresh_does_not_stale_current_goal_certificate(self) -> None:
        self.certifiable_goal()
        self.json_run(
            "convergence", "--certify-goal",
            "--final-validation-id", "mock_video_pipeline_test",
        )
        state = self.read_json(".agent/runtime/convergence_state.json")
        raw_north = self.read_json(".agent/north_star_goal.json")

        refreshed = refresh(
            state,
            north_star=raw_north,
            phase={},
            ticket={},
            updated_at="2026-08-22T01:00:00+00:00",
        )

        self.assertEqual(refreshed["goal_completion"]["status"], "CERTIFIED_COMPLETE")

    def test_same_goal_refresh_preserves_active_segment_and_progress(self) -> None:
        north = {
            "goal": "Deliver one stable direction.",
            "goal_mode_objective": "Stable detailed objective",
            "goal_definition": {
                "process": {"nodes": [{
                    "node_id": "N1",
                    "name": "Stable route",
                    "objective": "Finish the stable route.",
                    "dependencies": [],
                    "inputs": ["input"],
                    "actions": ["action"],
                    "outputs": ["output"],
                    "exit_criteria": ["evidence"],
                    "execution_mode": "SERIAL",
                    "contribution_to_goal": "contribution",
                    "timebox_hours": 2,
                    "reminder_interval_hours": 0,
                }]},
            },
        }
        state = refresh(
            empty_state(), north_star=north, phase={}, ticket={},
            updated_at="2026-08-22T00:00:00+00:00",
        )
        state, _ = start_segment(state, node_id="N1", observed_at="2026-08-22T00:01:00+00:00")
        state["progress"]["evidence_count"] = 2

        same = refresh(
            state, north_star=north, phase={}, ticket={},
            updated_at="2026-08-22T00:30:00+00:00",
        )

        self.assertIn("N1", same["segments"]["active"])
        self.assertEqual(same["progress"]["evidence_count"], 2)
        self.assertEqual(same["goal_history"], [])

    def test_segment_start_creates_real_deadline_and_short_segment_waits_until_deadline(self) -> None:
        state = empty_state()
        state["goal_stack"]["goal_contract"]["modules"] = [{
            "node_id": "N1",
            "name": "Telemetry data bridge",
            "objective": "Read telemetry data through the accepted bridge.",
            "dependencies": [],
            "timebox_hours": 2,
            "reminder_interval_hours": 0,
        }]
        state, started = start_segment(state, node_id="N1", observed_at="2026-08-14T00:00:00+00:00")

        self.assertEqual(started["deadline_at"], "2026-08-14T02:00:00+00:00")
        state, early = due_segment_reminder(state, observed_at="2026-08-14T01:59:59+00:00")
        self.assertIsNone(early)
        state, due = due_segment_reminder(state, observed_at="2026-08-14T02:00:00+00:00", consume=True)
        self.assertEqual(due["status"], "OVERDUE")

        state, completed = complete_segment(
            state,
            node_id="N1",
            observed_at="2026-08-14T02:05:00+00:00",
            evidence_ids=["telemetry-bridge-test"],
        )
        self.assertEqual(completed["status"], "COMPLETED")
        self.assertEqual(state["segments"]["active"], {})
        _, later = due_segment_reminder(state, observed_at="2026-08-15T00:00:00+00:00")
        self.assertIsNone(later)

    def test_descriptive_dependency_with_exact_node_prefix_uses_completed_node(self) -> None:
        state = empty_state()
        state["goal_stack"]["goal_contract"]["modules"] = [
            {
                "node_id": "DOMAIN",
                "name": "Domain rules",
                "dependencies": [],
                "timebox_hours": 1,
            },
            {
                "node_id": "LOOPBACK_E2E",
                "name": "Loopback lifecycle",
                "dependencies": ["DOMAIN 的领域结果和错误契约"],
                "timebox_hours": 1,
            },
        ]
        state, _ = start_segment(
            state,
            node_id="DOMAIN",
            observed_at="2026-08-14T00:00:00+00:00",
        )
        state, _ = complete_segment(
            state,
            node_id="DOMAIN",
            observed_at="2026-08-14T00:30:00+00:00",
            evidence_ids=["domain-rules-pass"],
        )

        state, started = start_segment(
            state,
            node_id="LOOPBACK_E2E",
            observed_at="2026-08-14T00:31:00+00:00",
        )

        self.assertEqual(started["node_id"], "LOOPBACK_E2E")

    def test_unmapped_descriptive_dependency_remains_blocked(self) -> None:
        state = empty_state()
        state["goal_stack"]["goal_contract"]["modules"] = [{
            "node_id": "LOOPBACK_E2E",
            "name": "Loopback lifecycle",
            "dependencies": ["domain results and error contract"],
            "timebox_hours": 1,
        }]

        with self.assertRaisesRegex(ValueError, "segment dependencies are not complete"):
            start_segment(
                state,
                node_id="LOOPBACK_E2E",
                observed_at="2026-08-14T00:31:00+00:00",
            )

    def test_completed_program_phase_satisfies_current_node_dependency(self) -> None:
        state = empty_state()
        state["goal_stack"]["goal_contract"].update({
            "completed_program_phases": ["P1"],
            "modules": [{
                "node_id": "P2-N1",
                "name": "Phase two implementation",
                "dependencies": ["P1"],
                "timebox_hours": 2,
            }],
        })

        state, started = start_segment(
            state,
            node_id="P2-N1",
            observed_at="2026-08-14T01:00:00+00:00",
        )

        self.assertEqual(started["node_id"], "P2-N1")

    def test_long_segment_uses_goal_selected_reminder_cadence(self) -> None:
        state = empty_state()
        state["goal_stack"]["goal_contract"]["modules"] = [{
            "node_id": "UI",
            "name": "Mobile UI",
            "objective": "Complete the accepted mobile UI flow.",
            "dependencies": [],
            "timebox_hours": 5,
            "reminder_interval_hours": 2,
        }]
        state, _ = start_segment(state, node_id="UI", observed_at="2026-08-14T00:00:00+00:00")
        _, early = due_segment_reminder(state, observed_at="2026-08-14T01:59:59+00:00")
        self.assertIsNone(early)
        state, due = due_segment_reminder(state, observed_at="2026-08-14T02:00:00+00:00", consume=True)
        self.assertEqual(due["status"], "TIMEBOX_CHECKPOINT")
        self.assertEqual(state["segments"]["active"]["UI"]["next_reminder_at"], "2026-08-14T04:00:00+00:00")
        state, due = due_segment_reminder(state, observed_at="2026-08-14T04:00:00+00:00", consume=True)
        self.assertEqual(due["status"], "TIMEBOX_CHECKPOINT")
        self.assertEqual(state["segments"]["active"]["UI"]["next_reminder_at"], "2026-08-14T05:00:00+00:00")
        _, deadline = due_segment_reminder(state, observed_at="2026-08-14T05:00:00+00:00")
        self.assertEqual(deadline["status"], "OVERDUE")

    def test_background_start_requires_one_unambiguous_segment(self) -> None:
        state = empty_state()
        state["goal_stack"]["goal_contract"]["modules"] = [
            {
                "node_id": "UI",
                "name": "Mobile UI",
                "dependencies": [],
                "timebox_hours": 5,
                "reminder_interval_hours": 2,
            },
            {
                "node_id": "TELEMETRY",
                "name": "Telemetry data bridge",
                "dependencies": [],
                "timebox_hours": 2,
                "reminder_interval_hours": 0,
            },
        ]
        state, ambiguous = auto_start_segment(
            state,
            observed_at="2026-08-14T00:00:00+00:00",
            hints=["Implement the next feature."],
        )
        self.assertIsNone(ambiguous)
        self.assertEqual(state["segments"]["active"], {})

        state, started = auto_start_segment(
            state,
            observed_at="2026-08-14T00:00:00+00:00",
            hints=["Begin the telemetry data bridge implementation."],
        )
        self.assertEqual(started["node_id"], "TELEMETRY")
        self.assertEqual(started["started_by"], "BACKGROUND_HIGH_CONFIDENCE")

    def test_init_projects_an_existing_confirmed_north_star(self) -> None:
        north = self.read_json(".agent/north_star_goal.json")
        north.update({"confirmed": True, "goal": "Deliver the verified registry."})
        self.write_json(".agent/north_star_goal.json", north)
        self.write_json(".agent/runtime/convergence_state.json", empty_state())

        self.cli("init")

        state = self.read_json(".agent/runtime/convergence_state.json")
        self.assertEqual(state["goal_stack"]["l0_final_goal"], "Deliver the verified registry.")

    def test_status_exposes_four_level_goal_stack(self) -> None:
        north = self.read_json(".agent/north_star_goal.json")
        north.update({
            "confirmed": True,
            "goal": "Deliver a reliable package registry.",
            "goal_definition": {
                "quality": "STRUCTURED_DETAILED",
                "success_criteria": ["Uploads are validated", "Downloads preserve the accepted package"],
                "final_acceptance": [],
            },
        })
        self.write_json(".agent/north_star_goal.json", north)
        self.cli("phase-set", "--id", "P1", "--goal", "Prove the upload and validation path", "--exit-criterion", "valid package is accepted")
        self.cli("convergence", "--current-action", "Run the accepted package fixture", "--expected-evidence", "validation result")

        result = self.json_run("status")
        detail = self.json_run("convergence")
        stack = detail["convergence"]["goal_stack"]
        self.assertEqual(stack["l0_final_goal"], "Deliver a reliable package registry.")
        self.assertEqual(stack["l2_current_stage"], "Prove the upload and validation path")
        self.assertEqual(stack["l3_current_action"], "Run the accepted package fixture")
        self.assertEqual(stack["l3_expected_evidence"], "validation result")
        self.assertEqual(len(stack["l1_success_criteria"]), 2)

    def test_convergence_projects_specific_goal_modules_and_acceptance(self) -> None:
        north = self.read_json(".agent/north_star_goal.json")
        north.update({
            "confirmed": True,
            "goal": "Deliver a traceable packaging release workflow.",
            "goal_definition": {
                "precise_goal": "Link each packaging lot to evidence and a release decision.",
                "current_state": "Evidence is fragmented.",
                "desired_state": "Each release is reproducible.",
                "process": {"nodes": [
                    {
                        "node_id": "N1",
                        "name": "Evidence intake",
                        "objective": "Validate lot evidence.",
                        "inputs": ["lot data"],
                        "outputs": ["validated evidence record"],
                        "exit_criteria": ["required measurements are resolved"],
                        "dependencies": [],
                        "execution_mode": "SERIAL",
                        "contribution_to_goal": "Creates the evidence foundation.",
                    },
                    {
                        "node_id": "N2",
                        "name": "Release decision",
                        "objective": "Evaluate release rules.",
                        "inputs": ["validated evidence record"],
                        "outputs": ["release result"],
                        "exit_criteria": ["every rule has evidence"],
                        "dependencies": ["N1"],
                        "execution_mode": "SERIAL",
                        "contribution_to_goal": "Produces the accepted user result.",
                    },
                ]},
                "final_acceptance": [{
                    "criterion": "A fixture lot completes the workflow.",
                    "evidence": "fixture result",
                    "validation_method": "run focused validation",
                }],
                "constraints": ["Do not replace plant MES"],
                "non_goals": ["Enterprise compliance platform"],
            },
        })
        self.write_json(".agent/north_star_goal.json", north)
        self.cli("init")

        state = self.read_json(".agent/runtime/convergence_state.json")
        contract = state["goal_stack"]["goal_contract"]
        self.assertEqual(contract["objective"], "Link each packaging lot to evidence and a release decision.")
        self.assertEqual(contract["modules"][1]["dependencies"], ["N1"])
        self.assertEqual(contract["modules"][1]["outputs"], ["release result"])
        self.assertEqual(contract["final_acceptance"][0]["evidence"], "fixture result")
        compact = self.json_run("status")["convergence"]["goal_stack"]["goal_contract"]
        self.assertEqual(compact["module_count"], 2)
        self.assertEqual(compact["final_acceptance_count"], 1)

    def test_external_prerequisite_selects_dependency_ready_goal_path(self) -> None:
        state = empty_state()
        state["goal_stack"]["l0_final_goal"] = "Deliver the complete multi-surface product."
        state["goal_stack"]["goal_contract"] = {
            "modules": [
                {"node_id": "N1", "name": "Primary client path"},
                {"node_id": "N2", "name": "Secondary client path"},
                {"node_id": "N3", "name": "Companion client path"},
                {"node_id": "N4", "name": "Shared session"},
            ],
            "module_count_total": 4,
            "projection_truncated": False,
            "final_acceptance": [{"criterion": "Run the complete field demo three times."}],
        }

        review = external_prerequisite_stop_review(
            state,
            "已进入安全暂停。等待你物理打开 Wi-Fi 后才能继续。",
        )

        self.assertTrue(review["should_continue"])
        self.assertEqual(review["status"], "CONTINUE_INDEPENDENT_PATH")
        self.assertIn("Primary client path", review["reason"])
        self.assertIn("Companion client path", review["reason"])
        self.assertIn("use tools now", review["reason"])
        recorded = record_blocker_scope_review(
            state,
            review=review,
            observed_at="2026-08-12T00:00:00+00:00",
        )
        recovery = recorded["recovery"]
        self.assertEqual(recovery["blocker_scope_review"]["goal_module_count"], 4)
        self.assertEqual(recovery["blocker_scope_review"]["status"], "CONTINUE_INDEPENDENT_PATH")
        self.assertNotIn("Wi-Fi", json.dumps(recovery, ensure_ascii=False))

    def test_external_prerequisite_retries_one_planning_only_follow_up_then_stops(self) -> None:
        state = empty_state()
        state["goal_stack"]["l0_final_goal"] = "Deliver the verified product."
        state["goal_stack"]["l1_success_criteria"] = [{"criterion": "The product regression passes."}]

        initial = external_prerequisite_stop_review(
            state,
            "Waiting for the user to connect the physical device before continuing.",
        )
        self.assertTrue(initial["should_continue"])
        state = record_blocker_scope_review(
            state,
            review=initial,
            observed_at="2026-08-12T00:00:00+00:00",
        )

        retry = external_prerequisite_stop_review(
            state,
            "Waiting for the user to connect the physical device before continuing.",
            stop_hook_active=True,
        )
        self.assertTrue(retry["should_continue"])
        self.assertEqual(retry["status"], "EXECUTION_RETRY_REQUIRED")
        state = record_blocker_scope_review(
            state,
            review=retry,
            observed_at="2026-08-12T00:01:00+00:00",
        )

        exhausted = external_prerequisite_stop_review(
            state,
            "Waiting for the user to connect the physical device before continuing.",
            stop_hook_active=True,
        )
        self.assertFalse(exhausted["should_continue"])
        self.assertEqual(exhausted["status"], "NO_PROGRESS_RETRY_EXHAUSTED")

    def test_productive_external_blocker_follow_up_renews_continuation(self) -> None:
        state = empty_state()
        state["goal_stack"]["l0_final_goal"] = "Deliver the verified product."
        state["goal_stack"]["goal_contract"] = {
            "modules": [
                {"node_id": "N1", "name": "Device path", "dependencies": []},
                {"node_id": "N2", "name": "Offline contract tests", "dependencies": []},
            ],
            "module_count_total": 2,
            "final_acceptance": [],
        }
        state["segments"]["active"] = {"N1": {"node_id": "N1", "status": "ACTIVE"}}
        initial = external_prerequisite_stop_review(
            state,
            "已进入安全暂停，等待你连接物理设备后才能继续。",
        )
        self.assertEqual([row["node_id"] for row in initial["candidate_paths"]], ["N2"])
        state = record_blocker_scope_review(
            state,
            review=initial,
            observed_at="2026-08-12T00:00:00+00:00",
        )
        state["activity"]["writes"] = 1

        renewed = external_prerequisite_stop_review(
            state,
            "设备仍需人工连接，我需要暂停执行。",
            stop_hook_active=True,
        )

        self.assertTrue(renewed["should_continue"])
        self.assertEqual(renewed["status"], "CONTINUE_INDEPENDENT_PATH")
        self.assertIn("N2 Offline contract tests", renewed["reason"])

    def test_external_blocker_with_no_independent_path_can_stop(self) -> None:
        state = empty_state()
        state["goal_stack"]["l0_final_goal"] = "Deliver the verified device product."
        state["goal_stack"]["goal_contract"] = {
            "modules": [
                {"node_id": "N1", "name": "Physical device session", "dependencies": []},
                {"node_id": "N2", "name": "Device acceptance", "dependencies": ["N1"]},
            ],
            "module_count_total": 2,
            "final_acceptance": [],
        }
        state["segments"]["active"] = {"N1": {"node_id": "N1", "status": "ACTIVE"}}

        review = external_prerequisite_stop_review(
            state,
            "等待你连接物理设备后才能继续。",
        )

        self.assertFalse(review["should_continue"])
        self.assertEqual(review["status"], "NO_DEPENDENCY_READY_INDEPENDENT_PATH")

    def test_false_global_blocker_claim_cannot_hide_ready_path(self) -> None:
        state = empty_state()
        state["goal_stack"]["l0_final_goal"] = "Deliver the verified product."
        state["goal_stack"]["goal_contract"] = {
            "modules": [
                {"node_id": "N1", "name": "Physical device path", "dependencies": []},
                {"node_id": "N2", "name": "Offline contract tests", "dependencies": []},
            ],
            "module_count_total": 2,
            "final_acceptance": [],
        }
        state["segments"]["active"] = {"N1": {"node_id": "N1", "status": "ACTIVE"}}
        initial = external_prerequisite_stop_review(
            state,
            "等待你连接物理设备后才能继续。",
        )
        state = record_blocker_scope_review(
            state,
            review=initial,
            observed_at="2026-08-12T00:00:00+00:00",
        )

        review = external_prerequisite_stop_review(
            state,
            "所有剩余路径都依赖物理设备，所以暂停执行。",
            stop_hook_active=True,
        )

        self.assertTrue(review["should_continue"])
        self.assertEqual(review["status"], "EXECUTION_RETRY_REQUIRED")
        self.assertIn("N2 Offline contract tests", review["reason"])

    def test_external_prerequisite_does_not_claim_goal_review_without_goal_structure(self) -> None:
        state = empty_state()
        state["goal_stack"]["l0_final_goal"] = "Deliver the verified product."

        review = external_prerequisite_stop_review(
            state,
            "Waiting for the user to connect the physical device before continuing.",
        )

        self.assertFalse(review["should_continue"])
        self.assertEqual(review["status"], "INSUFFICIENT_GOAL_STRUCTURE")

    def test_continuing_around_external_prerequisite_is_not_interrupted(self) -> None:
        state = empty_state()
        state["goal_stack"]["l0_final_goal"] = "Deliver the verified product."
        state["goal_stack"]["l1_success_criteria"] = [{"criterion": "The product regression passes."}]

        review = external_prerequisite_stop_review(
            state,
            "无需等待物理 Wi-Fi，我会继续推进其他可执行模块。",
        )

        self.assertFalse(review["should_continue"])

    def test_completed_phase_clears_current_stage_and_action(self) -> None:
        self.cli("phase-set", "--id", "P1", "--goal", "Verify the bounded change", "--exit-criterion", "tests pass")
        self.cli("convergence", "--current-action", "Run the focused tests", "--expected-evidence", "test output")

        self.cli("phase-complete", "--reason", "Focused tests passed")

        stack = self.json_run("status")["convergence"]["goal_stack"]
        self.assertIsNone(stack["l2_current_stage"])
        self.assertIsNone(stack["l3_current_action"])
        self.assertIsNone(stack["l3_expected_evidence"])

    def test_north_star_completion_requires_final_regression(self) -> None:
        self.certifiable_goal()

        result = self.json_run("convergence", "--certify-goal", check=False)

        self.assertFalse(result["ok"])
        self.assertEqual(result["goal_completion"]["status"], "NEEDS_FINAL_REGRESSION")
        self.assertNotEqual(result["convergence"]["goal_completion"]["status"], "CERTIFIED_COMPLETE")

    def test_failed_final_regression_cannot_certify_north_star(self) -> None:
        self.certifiable_goal()
        catalog = self.read_json(".agent/validation_catalog.json")
        catalog["project_regression_fail"] = {
            "cmd": "{python} -c \"import sys; sys.exit(1)\"",
            "description": "Deterministic failing final regression fixture.",
            "timeout_sec": 8,
        }
        self.write_json(".agent/validation_catalog.json", catalog)

        result = self.json_run(
            "convergence", "--certify-goal",
            "--final-validation-id", "project_regression_fail",
            check=False,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["goal_completion"]["status"], "FINAL_REGRESSION_FAILED")
        self.assertEqual(result["goal_completion"]["validation"]["status"], "FAIL")
        self.assertEqual(self.json_run("status")["convergence"]["goal_completion"], "FINAL_REGRESSION_FAILED")

    def test_local_validation_cannot_certify_goal_with_empty_global_success_contract(self) -> None:
        self.certifiable_goal()
        north = self.read_json(".agent/north_star_goal.json")
        north["goal_definition"]["success_criteria"] = []
        north["goal_definition"]["final_acceptance"] = []
        self.write_json(".agent/north_star_goal.json", north)

        result = self.json_run(
            "convergence", "--certify-goal",
            "--final-validation-id", "mock_video_pipeline_test",
            check=False,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["goal_completion"]["status"], "INCOMPLETE_GOAL_CONTRACT")
        self.assertEqual(result["goal_completion"]["required_action"], "repair_goal_contract")
        self.assertIn("local validation cannot certify", result["goal_completion"]["failure_reasons"][0])
        self.assertNotEqual(self.json_run("status")["status"], "GOAL_CERTIFIED_COMPLETE")

    def test_passing_final_regression_certifies_goal_and_completes_phase(self) -> None:
        self.certifiable_goal()
        self.cli("phase-set", "--id", "FINAL", "--goal", "Run final regression", "--exit-criterion", "project regression passes")

        result = self.json_run(
            "convergence", "--certify-goal",
            "--final-validation-id", "mock_video_pipeline_test",
            "--completion-summary", "End-to-end project regression passed.",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["goal_completion"]["status"], "CERTIFIED_COMPLETE")
        self.assertEqual(result["goal_completion"]["validation"]["status"], "PASS")
        self.assertEqual(result["goal_completion"]["program_phase"]["status"], "COMPLETED")
        status = self.json_run("status")
        self.assertEqual(status["status"], "GOAL_CERTIFIED_COMPLETE")
        self.assertEqual(status["required_action"], "deliver_verified_result")
        self.assertEqual(status["convergence"]["goal_completion"], "CERTIFIED_COMPLETE")

    def test_goal_replacement_invalidates_final_regression_certificate(self) -> None:
        self.certifiable_goal()
        self.json_run(
            "convergence", "--certify-goal",
            "--final-validation-id", "mock_video_pipeline_test",
        )

        self.cli(
            "goal-set", "--text", "Build a traceable packaging release workflow.",
            "--replace-existing",
        )

        status = self.json_run("status")
        self.assertEqual(status["convergence"]["goal_completion"], "STALE_GOAL_CHANGED")
        self.assertNotEqual(status["status"], "GOAL_CERTIFIED_COMPLETE")

    def test_activity_does_not_claim_progress(self) -> None:
        state = empty_state()
        for index in range(20):
            state = apply_observation(state, {
                "event_id": f"write-{index}",
                "phase": "PostToolUse",
                "category": "write",
                "failed": False,
                "ts": "2026-08-03T00:00:00+00:00",
            })
        self.assertEqual(state["activity"]["writes"], 20)
        self.assertEqual(state["progress"]["evidence_count"], 0)
        self.assertIsNone(state["progress"]["last_progress_at"])

    def test_two_completed_iterations_without_evidence_trigger_judge_eligibility(self) -> None:
        state = empty_state()
        for index in range(2):
            state = record_iteration(
                state,
                hypothesis=f"attempt {index}",
                change="modify implementation",
                expected_result="test improves",
                validation="run test",
                result="no new evidence",
                decision="retry",
                evidence_ids=[],
                completed_criteria=[],
                observed_at=f"2026-08-03T00:0{index}:00+00:00",
            )
        trigger = judge_trigger(state)
        self.assertTrue(trigger["eligible"])
        self.assertIn("two_completed_iterations_without_evidence_progress", trigger["reasons"])

    def test_event_signals_alone_do_not_trigger_judge(self) -> None:
        state = empty_state()
        state["activity"]["failed_events"] = 2
        state["activity"]["writes"] = 100
        trigger = judge_trigger(state)
        self.assertFalse(trigger["eligible"])
        self.assertEqual(trigger["reasons"], [])

    def test_iteration_record_requires_evidence_to_reset_stagnation(self) -> None:
        for index in range(2):
            result = self.json_run(
                "convergence", "--record-iteration",
                "--hypothesis", f"hypothesis {index}",
                "--change", "change implementation",
                "--expected-result", "validation improves",
                "--validation", "run focused test",
                "--result", "no evidence",
                "--decision", "retry",
            )
        self.assertEqual(result["convergence"]["progress"]["no_progress_iterations"], 2)

        result = self.json_run(
            "convergence", "--record-iteration",
            "--hypothesis", "focused correction",
            "--change", "fix the failing branch",
            "--expected-result", "focused test passes",
            "--validation", "run focused test",
            "--result", "test passed",
            "--decision", "accept",
            "--evidence-id", "focused-test-pass",
            "--completed-criterion", "focused branch behaves correctly",
        )
        self.assertEqual(result["convergence"]["progress"]["no_progress_iterations"], 0)
        self.assertEqual(result["convergence"]["progress"]["evidence_count"], 1)
        persisted = self.read_json(".agent/runtime/convergence_state.json")
        self.assertEqual(persisted["evidence"][0]["evidence_id"], "focused-test-pass")
        self.assertEqual(result["convergence"]["progress"]["completed_criteria_count"], 1)

    def test_two_collaboration_rounds_without_evidence_stop_mutual_review(self) -> None:
        first = self.json_run(
            "convergence", "--record-collaboration",
            "--source-thread", "codex-main",
            "--target-thread", "gpt-review",
            "--claim", "The plan looks comprehensive and I agree.",
        )
        self.assertEqual(first["convergence"]["collaboration"]["status"], "NO_EVIDENCE_WARNING")
        second = self.json_run(
            "convergence", "--record-collaboration",
            "--source-thread", "gpt-review",
            "--target-thread", "codex-main",
            "--claim", "I agree with the assessment and the direction is excellent.",
        )
        collaboration = second["convergence"]["collaboration"]
        self.assertEqual(collaboration["status"], "CONSENSUS_WITHOUT_PROGRESS")
        self.assertEqual(
            collaboration["required_action"],
            "stop_mutual_review_and_execute_validate_or_escalate",
        )
        self.assertEqual(
            self.json_run("status")["convergence"]["collaboration"]["status"],
            "CONSENSUS_WITHOUT_PROGRESS",
        )

    def test_collaboration_evidence_resets_no_progress_rounds(self) -> None:
        state = empty_state()
        state = record_collaboration_round(
            state,
            source="codex-main",
            target="gpt-review",
            claim="Please review the plan.",
            evidence_ids=[],
            artifact_refs=[],
            state_transition=None,
            observed_at="2026-08-12T00:00:00+00:00",
        )
        state = record_collaboration_round(
            state,
            source="gpt-review",
            target="codex-main",
            claim="The focused regression passed and produced a report.",
            evidence_ids=["focused-regression-pass"],
            artifact_refs=["reports/focused-regression.json"],
            state_transition="VALIDATED",
            observed_at="2026-08-12T00:01:00+00:00",
        )
        self.assertEqual(state["collaboration"]["status"], "EVIDENCE_PROGRESS")
        self.assertEqual(state["collaboration"]["no_evidence_rounds"], 0)
        self.assertGreaterEqual(state["progress"]["evidence_count"], 2)

    def test_collaboration_praise_alone_never_counts_as_progress(self) -> None:
        state = record_collaboration_round(
            empty_state(),
            source="reviewer",
            target="executor",
            claim="Excellent work; fully agreed and approved.",
            evidence_ids=[],
            artifact_refs=[],
            state_transition="AGREED",
            observed_at="2026-08-12T00:00:00+00:00",
        )
        self.assertFalse(state["collaboration"]["last_round"]["progress_made"])
        self.assertIsNone(state["collaboration"]["last_round"]["state_transition"])

    def test_missing_artifact_reference_does_not_create_cli_progress(self) -> None:
        result = self.json_run(
            "convergence", "--record-collaboration",
            "--source-thread", "executor",
            "--target-thread", "owner",
            "--claim", "A report was produced.",
            "--artifact-ref", "reports/does-not-exist.json",
        )
        last_round = result["convergence"]["collaboration"]["last_round"]
        self.assertEqual(last_round["artifact_refs"], [])
        self.assertFalse(last_round["progress_made"])


class LlmJudgeTests(GoalCompassRepoCase):
    def setUp(self) -> None:
        super().setUp()
        self._old_judge_cmd = os.environ.get("GOAL_SUPERVISOR_JUDGE_CMD")
        self.fake = self.root / "fake_codex.py"
        self.log = self.root / "fake_judge_log.jsonl"
        os.environ["GOAL_SUPERVISOR_JUDGE_CMD"] = f"{sys.executable} {self.fake}"
        os.environ["FAKE_JUDGE_LOG"] = str(self.log)

    def tearDown(self) -> None:
        if self._old_judge_cmd is None:
            os.environ.pop("GOAL_SUPERVISOR_JUDGE_CMD", None)
        else:
            os.environ["GOAL_SUPERVISOR_JUDGE_CMD"] = self._old_judge_cmd
        os.environ.pop("FAKE_JUDGE_LOG", None)
        super().tearDown()

    def write_fake(self, verdict: str = "ALLOW_SCOPED_ACTION", confidence: str = "high", *, sleep: float = 0.0, malformed: bool = False) -> None:
        payload = "not-json" if malformed else json.dumps({
            "verdict": verdict,
            "confidence": confidence,
            "rationale": "The scoped action remains aligned with the current evidence.",
            "recommended_action": "continue_scoped_action",
            "evidence_needed": [],
        })
        self.fake.write_text(
            "import json, os, pathlib, sys, time\n"
            f"time.sleep({sleep!r})\n"
            "args=sys.argv[1:]\n"
            "prompt=sys.stdin.read()\n"
            "out=pathlib.Path(args[args.index('-o')+1])\n"
            f"out.write_text({payload!r}, encoding='utf-8')\n"
            "log=pathlib.Path(os.environ['FAKE_JUDGE_LOG'])\n"
            "with log.open('a', encoding='utf-8') as h: h.write(json.dumps({'cwd':os.getcwd(),'marker':os.environ.get('GOAL_SUPERVISOR_LLM_JUDGE'),'args':args,'prompt':prompt})+'\\n')\n",
            encoding="utf-8",
        )

    def packet(self) -> dict:
        return {
            "trigger": "pending_targeted_rail",
            "north_star_goal": "Build a private package registry.",
            "success_criteria": ["private upload works"],
            "current_stage": "upload validation",
            "current_action": "write under src/registry",
            "expected_evidence": "focused validation",
            "observed_evidence": [],
            "policy_boundary": "public marketplace",
            "alignment_layer": "GOAL_CONTRACT",
            "goal_contract": {
                "objective": "Validate and store private Agent packages.",
                "modules": [{
                    "node_id": "N2",
                    "name": "Package validation",
                    "objective": "Validate package structure before storage.",
                    "dependencies": ["N1"],
                    "outputs": ["validated package"],
                    "exit_criteria": ["manifest and README pass"],
                    "contribution_to_goal": "Prevents invalid shared packages.",
                }],
                "final_acceptance": [{"criterion": "valid package can be downloaded"}],
                "constraints": ["private LAN only"],
                "non_goals": ["public marketplace"],
            },
            "affected_paths": ["src/registry"],
            "consequence": "possible expensive rework",
            "source_code": "must never be sent",
            "credentials": "must never be sent",
        }

    def test_judge_is_neutral_read_only_structured_and_cached(self) -> None:
        self.write_fake()
        schema = self.root / ".agent/protocols/llm_judge.schema.json"
        cache = self.root / ".agent/runtime/test_judge_cache.json"
        first = invoke(self.packet(), schema_path=schema, cache_path=cache, timeout_seconds=2)
        second = invoke(self.packet(), schema_path=schema, cache_path=cache, timeout_seconds=2)

        self.assertEqual(first["status"], "COMPLETED")
        self.assertEqual(second["status"], "CACHED")
        rows = self.log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(rows), 1)
        log = json.loads(rows[0])
        self.assertNotEqual(Path(log["cwd"]), self.root)
        self.assertEqual(log["marker"], "1")
        self.assertIn("--ephemeral", log["args"])
        self.assertIn("read-only", log["args"])
        self.assertNotIn("must never be sent", log["prompt"])
        self.assertIn("Package validation", log["prompt"])
        self.assertIn("Goal contract", log["prompt"])

    def test_judge_timeout_fails_open(self) -> None:
        self.write_fake(sleep=1.0)
        result = invoke(
            self.packet(),
            schema_path=self.root / ".agent/protocols/llm_judge.schema.json",
            cache_path=self.root / ".agent/runtime/timeout_cache.json",
            timeout_seconds=0.05,
            force=True,
        )
        self.assertEqual(result["status"], "TIMEOUT")
        self.assertEqual(result["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_judge_process_start_failure_fails_open(self) -> None:
        os.environ["GOAL_SUPERVISOR_JUDGE_CMD"] = str(self.root / "missing-codex")
        result = invoke(
            self.packet(),
            schema_path=self.root / ".agent/protocols/llm_judge.schema.json",
            cache_path=self.root / ".agent/runtime/start_failure_cache.json",
            timeout_seconds=2,
            force=True,
        )
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result["recommended_action"], "continue_with_scripted_advisory_only")

    def test_malformed_judge_output_fails_open(self) -> None:
        self.write_fake(malformed=True)
        result = invoke(
            self.packet(),
            schema_path=self.root / ".agent/protocols/llm_judge.schema.json",
            cache_path=self.root / ".agent/runtime/malformed_cache.json",
            timeout_seconds=2,
            force=True,
        )
        self.assertEqual(result["status"], "MALFORMED")
        self.assertEqual(result["verdict"], "INSUFFICIENT_EVIDENCE")

    def test_second_completed_no_progress_iteration_invokes_judge_once(self) -> None:
        self.write_fake(verdict="WARN_AND_RECHECK", confidence="medium")
        os.environ.pop("GOAL_SUPERVISOR_DISABLE_LLM_JUDGE", None)
        common = [
            "--record-iteration",
            "--change", "adjust the same implementation path",
            "--expected-result", "produce new machine evidence",
            "--validation", "run the focused validation",
            "--result", "no new evidence",
            "--decision", "reassess",
        ]
        first = self.json_run("convergence", *common, "--hypothesis", "first attempt")
        second = self.json_run("convergence", *common, "--hypothesis", "second attempt")

        self.assertIsNone(first["judge_result"])
        self.assertEqual(second["judge_result"]["verdict"], "WARN_AND_RECHECK")
        self.assertEqual(len(self.log.read_text(encoding="utf-8").splitlines()), 1)

    def hook_output(self, event: dict) -> str:
        output = io.StringIO()
        with pushd(self.root), contextlib.redirect_stdout(output):
            GOAL_COMPASS.hook_pre(event)
        return output.getvalue()

    def test_third_semantic_deviation_requires_judge_confirmation(self) -> None:
        self.write_fake(verdict="ALLOW_SCOPED_ACTION", confidence="high")
        os.environ.pop("GOAL_SUPERVISOR_DISABLE_LLM_JUDGE", None)
        north = self.read_json(".agent/north_star_goal.json")
        north.update({
            "confirmed": True,
            "goal": "Build a private internal Agent Registry.",
            "anti_goals": ["provider marketplace"],
        })
        self.write_json(".agent/north_star_goal.json", north)
        outputs = []
        for index in range(3):
            outputs.append(self.hook_output({
                "tool_name": "apply_patch",
                "tool_input": {
                    "patch": (
                        "*** Begin Patch\n"
                        f"*** Add File: src/providers/marketplace/{index}.py\n"
                        "+provider marketplace\n"
                        "*** End Patch"
                    ),
                },
                "tool_use_id": f"judge-release-{index}",
            }))
        self.assertIn("LLM Judge did not confirm", outputs[-1])
        self.assertNotIn("permissionDecision", outputs[-1])
        self.assertEqual(len(self.log.read_text(encoding="utf-8").splitlines()), 1)

    def test_high_confidence_judge_can_confirm_targeted_rail(self) -> None:
        self.write_fake(verdict="CONFIRM_TARGETED_RAIL", confidence="high")
        os.environ.pop("GOAL_SUPERVISOR_DISABLE_LLM_JUDGE", None)
        north = self.read_json(".agent/north_star_goal.json")
        north.update({
            "confirmed": True,
            "goal": "Build a private internal Agent Registry.",
            "anti_goals": ["provider marketplace"],
        })
        self.write_json(".agent/north_star_goal.json", north)
        output = ""
        for index in range(3):
            output = self.hook_output({
                "tool_name": "apply_patch",
                "tool_input": {
                    "patch": (
                        "*** Begin Patch\n"
                        f"*** Add File: src/providers/marketplace/{index}.py\n"
                        "+provider marketplace\n"
                        "*** End Patch"
                    ),
                },
                "tool_use_id": f"judge-confirm-{index}",
            })
        self.assertIn("permissionDecision", output)
        self.assertIn("Sparse LLM Judge confirmed", output)


class ExplicitActivationContractTests(GoalCompassRepoCase):
    def test_skill_requires_north_star_and_client_goal_mode_after_explicit_activation(self) -> None:
        text = (PLUGIN_ROOT / "skills/goal-supervisor/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Explicit plugin activation starts the General Profile", text)
        self.assertIn("does not by itself require a North Star", text)
        self.assertIn("The Goal Profile inherits every General requirement", text)
        self.assertIn("establishing the project North Star and starting", text)
        self.assertIn("Never claim activation is complete when only one of these two states exists", text)
        self.assertLess(text.index("goal-set --require-detailed"), text.index("thread/goal/set"))
        self.assertIn("verifies byte equality", text)
        self.assertIn("Do not call `update_goal(status=\"complete\")` for replacement", text)

    def test_real_blackbox_contract_requires_exact_native_goal_sync(self) -> None:
        text = (PLUGIN_ROOT / "skills/goal-supervisor/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("official app-server `thread/goal/set`", text)
        self.assertIn("thread/goal/get", text)
        self.assertNotIn("first action must call", text.lower())


if __name__ == "__main__":
    import unittest

    unittest.main()
