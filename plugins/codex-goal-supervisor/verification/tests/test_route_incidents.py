from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
from unittest import mock

try:
    from .helpers import GOAL_COMPASS, GoalCompassRepoCase, pushd, run_cmd
except ImportError:
    from helpers import GOAL_COMPASS, GoalCompassRepoCase, pushd, run_cmd

from goal_compass_runtime.observer import empty_state
from goal_compass_runtime.route_incidents import build_context, process_observation


def convergence_fixture(*, domain: str = "software", action: str = "Run the current route") -> dict:
    return {
        "goal_stack": {
            "l2_current_stage": f"Deliver the {domain} outcome",
            "l3_current_action": action,
            "goal_contract": {
                "source_requirements": [f"The {domain} result must work in the user's required operating scenario."],
                "first_principles": [{
                    "principle": "The technical route must satisfy the real user scenario.",
                    "rationale": "A locally convenient route is not useful if it cannot deliver the required outcome.",
                    "implications": ["Prefer the smallest route that reaches product acceptance."],
                }],
                "modules": [{
                    "node_id": "N1",
                    "name": f"{domain.title()} delivery route",
                    "objective": f"Produce the accepted {domain} result.",
                    "dependencies": [],
                }],
                "final_acceptance": [{
                    "criterion": f"The {domain} route passes end-to-end validation.",
                    "evidence": "registered validation",
                    "validation_method": "validation_catalog",
                }],
            },
        },
        "segments": {"active": {"N1": {"status": "ACTIVE"}}},
        "progress": {"evidence_count": 0},
    }


def route_observation(
    state: dict,
    *,
    domain: str,
    observed_at: str,
    command: str,
    failure_text: str,
) -> tuple[dict, list[dict]]:
    event = {
        "tool_name": "exec_command",
        "tool_input": {"cmd": command},
        "tool_response": {"exit_code": 1, "stderr": failure_text},
    }
    context = build_context(
        north_star={"goal": f"Deliver the {domain} product", "confirmed": True},
        convergence=convergence_fixture(domain=domain),
        event=event,
        paths=[f"src/{domain}/route.py"],
        failed=True,
    )
    assert context is not None
    return process_observation(state, {
        "event_id": f"{domain}:{observed_at}:{command}",
        "phase": "PostToolUse",
        "ts": observed_at,
        "failed": True,
        "route_context": context,
    })


class RouteIncidentPolicyTests(unittest.TestCase):
    def test_first_failure_is_silent_across_unrelated_domains(self) -> None:
        for domain, failure in (
            ("cad", "License server access denied"),
            ("data", "Connection refused by warehouse endpoint"),
            ("mobile", "Build failed with SyntaxError"),
        ):
            with self.subTest(domain=domain):
                state, signals = route_observation(
                    empty_state(),
                    domain=domain,
                    observed_at="2026-08-17T00:00:00+00:00",
                    command=f"run-{domain}-route --attempt 1",
                    failure_text=failure,
                )
                self.assertEqual(signals, [])
                self.assertEqual(len(state["route_incidents"]), 1)

    def test_three_immediate_failures_require_generic_route_reassessment(self) -> None:
        state = empty_state()
        signals: list[dict] = []
        for index in range(3):
            state, signals = route_observation(
                state,
                domain="packaging",
                observed_at=f"2026-08-17T00:0{index}:00+00:00",
                command="run-packaging-export --same-route",
                failure_text="Build failed while exporting the packaging artifact",
            )
        self.assertEqual(signals[0]["signal"], "ROUTE_REASSESSMENT_REQUIRED")
        self.assertEqual(signals[0]["intervention"], "STRONG_WARNING")
        self.assertFalse(signals[0]["deny"])
        self.assertFalse(signals[0]["needs_judge"])
        self.assertIn("source requirements", signals[0]["reason"])
        self.assertIn("first principles", signals[0]["reason"])
        self.assertIn("compare at least two materially different routes", signals[0]["reason"])

    def test_two_failures_thirty_minutes_apart_require_reassessment(self) -> None:
        state, first = route_observation(
            empty_state(),
            domain="robotics",
            observed_at="2026-08-17T00:00:00+00:00",
            command="run-device-route",
            failure_text="Connection refused",
        )
        state, second = route_observation(
            state,
            domain="robotics",
            observed_at="2026-08-17T00:30:00+00:00",
            command="run-device-route",
            failure_text="Connection refused",
        )
        self.assertEqual(first, [])
        self.assertEqual(second[0]["signal"], "ROUTE_REASSESSMENT_REQUIRED")

    def test_command_parameter_changes_do_not_disguise_the_same_route_retry(self) -> None:
        first_event = {
            "tool_name": "exec_command",
            "tool_input": {"cmd": "run-route --port 8000"},
            "tool_response": {"exit_code": 1, "stderr": "Connection refused"},
        }
        second_event = {
            "tool_name": "exec_command",
            "tool_input": {"cmd": "run-route --port 9000"},
            "tool_response": {"exit_code": 1, "stderr": "Connection refused"},
        }
        first = build_context(
            north_star={"goal": "Deliver the service"},
            convergence=convergence_fixture(domain="service", action="Try port 8000"),
            event=first_event,
            paths=["src/service.py"],
            failed=True,
        )
        second = build_context(
            north_star={"goal": "Deliver the service"},
            convergence=convergence_fixture(domain="service", action="Try port 9000"),
            event=second_event,
            paths=["src/service.py"],
            failed=True,
        )
        self.assertEqual(first["route_id"], second["route_id"])
        self.assertEqual(first["action_fingerprint"], second["action_fingerprint"])

    def test_targeted_rail_applies_only_to_the_repeated_failed_action(self) -> None:
        state = empty_state()
        for index in range(4):
            state, _ = route_observation(
                state,
                domain="simulation",
                observed_at=f"2026-08-17T00:0{index}:00+00:00",
                command="run-local-simulator --retry",
                failure_text="Security policy blocked the simulator",
            )
        base_event = {
            "tool_name": "exec_command",
            "tool_input": {"cmd": "run-local-simulator --retry"},
        }
        repeated = build_context(
            north_star={"goal": "Deliver the simulation product"},
            convergence=convergence_fixture(domain="simulation"),
            event=base_event,
            paths=["src/simulation/route.py"],
            failed=False,
        )
        state, rail = process_observation(state, {
            "event_id": "pre-repeat",
            "phase": "PreToolUse",
            "ts": "2026-08-17T00:04:00+00:00",
            "failed": False,
            "route_context": repeated,
        })
        self.assertTrue(rail[0]["deny"])
        self.assertEqual(rail[0]["intervention"], "TARGETED_RAIL")

        alternative = build_context(
            north_star={"goal": "Deliver the simulation product"},
            convergence=convergence_fixture(domain="simulation"),
            event={"tool_name": "exec_command", "tool_input": {"cmd": "use-remote-renderer --smoke"}},
            paths=["src/simulation/route.py"],
            failed=False,
        )
        state, allowed = process_observation(state, {
            "event_id": "pre-alternative",
            "phase": "PreToolUse",
            "ts": "2026-08-17T00:05:00+00:00",
            "failed": False,
            "route_context": alternative,
        })
        self.assertEqual(allowed, [])
        incident = next(iter(state["route_incidents"].values()))
        self.assertEqual(incident["status"], "ALTERNATIVE_TRIAL")

    def test_persisted_route_incident_contains_no_raw_command_or_error_text(self) -> None:
        state, _ = route_observation(
            empty_state(),
            domain="finance",
            observed_at="2026-08-17T00:00:00+00:00",
            command="run-private-route --token secret-value",
            failure_text="Permission denied for /private/customer/account.csv",
        )
        serialized = json.dumps(state, ensure_ascii=False)
        self.assertNotIn("secret-value", serialized)
        self.assertNotIn("customer/account.csv", serialized)
        self.assertNotIn("run-private-route", serialized)


class RouteIncidentHookTests(GoalCompassRepoCase):
    def setUp(self) -> None:
        super().setUp()
        self.write_json(".agent/tool_mode.json", {
            "version": "2.0",
            "enabled": True,
            "mode": "BACKGROUND_ADVISORY",
            "visible_ticket_required": False,
        })
        north = self.read_json(".agent/north_star_goal.json")
        north.update({
            "confirmed": True,
            "goal": "Deliver a portable industrial inspection product.",
            "goal_definition": {
                "quality": "STRUCTURED_DETAILED",
                "precise_goal": "Deliver an inspection product that works at the required field locations.",
                "source_requirements": ["Operators must use the result away from the development workstation."],
                "first_principles": [{
                    "principle": "Field availability is part of the product, not an optional deployment detail.",
                    "rationale": "A workstation-only route cannot satisfy field use.",
                    "implications": ["The selected route must remain reachable in the field."],
                }],
                "success_criteria": ["A field client completes the accepted end-to-end flow."],
                "process": {"nodes": [{
                    "node_id": "N1",
                    "name": "Field delivery route",
                    "objective": "Connect the field client to the inspection service.",
                    "dependencies": [],
                    "inputs": ["Inspection request"],
                    "actions": [{"action_id": "A1", "name": "Exercise the selected delivery route"}],
                    "outputs": ["Reachable inspection response"],
                    "consumers": ["Field operator"],
                    "contribution_to_goal": "Makes the product usable at the required field location.",
                    "exit_criteria": ["Field client receives a valid response."],
                    "timebox_hours": 2,
                }]},
                "final_acceptance": [{
                    "criterion": "A field client completes the end-to-end inspection flow.",
                    "evidence": "field_route_test",
                    "validation_method": "validation_catalog",
                }],
            },
        })
        self.write_json(".agent/north_star_goal.json", north)
        self.json_run("convergence", "--start-segment", "N1")

    def hook_post(self, event: dict) -> str:
        output = io.StringIO()
        with pushd(self.root), contextlib.redirect_stdout(output):
            GOAL_COMPASS.hook_post(event)
        return output.getvalue()

    def test_real_hook_surfaces_route_reassessment_without_domain_special_case(self) -> None:
        output = ""
        for index in range(3):
            output = self.hook_post({
                "tool_name": "exec_command",
                "tool_input": {"cmd": "run-field-route --retry"},
                "tool_response": {"exit_code": 1, "stderr": "Endpoint protection blocked this operation"},
                "tool_use_id": f"route-hook-{index}",
            })
        self.assertIn("Technical route reassessment required", output)
        self.assertIn("source requirements", output)
        self.assertIn("research current external tools", output)
        self.assertNotIn("permissionDecision", output)

    def test_project_hook_infers_post_event_and_accepts_common_result_wrappers(self) -> None:
        outputs: list[str] = []
        wrappers = ("tool_output", "tool_result", "result")
        for index, wrapper in enumerate(wrappers):
            event = {
                "tool_name": "exec_command",
                "tool_input": {"cmd": "run-field-route --retry"},
                wrapper: {"exit-code": 127, "stderr": "missing required platform tool"},
                "tool_use_id": f"route-project-hook-{index}",
            }
            completed = run_cmd(
                [sys.executable, ".agent/goal_compass_runtime/project_hook.py"],
                cwd=self.root,
                input_text=json.dumps(event),
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            outputs.append(completed.stdout)
        self.assertEqual(outputs[0].strip(), "")
        self.assertIn("Technical route reassessment required", outputs[-1])
        state = self.read_json(".agent/runtime/observer_state.json")
        incident = next(iter(state["route_incidents"].values()))
        self.assertEqual(incident["cause_family"], "DEPENDENCY_OR_TOOL_MISSING")

    def test_route_warning_does_not_invoke_llm_judge(self) -> None:
        old = os.environ.pop("GOAL_SUPERVISOR_DISABLE_LLM_JUDGE", None)
        try:
            output = ""
            for index in range(3):
                output = self.hook_post({
                    "tool_name": "exec_command",
                    "tool_input": {"cmd": "run-field-route --retry"},
                    "tool_response": {"exit_code": 1, "stderr": "Connection refused"},
                    "tool_use_id": f"cheap-route-hook-{index}",
                })
            self.assertIn("Technical route reassessment required", output)
            state = self.read_json(".agent/runtime/convergence_state.json")
            self.assertIsNone(state.get("judge", {}).get("last_result"))
        finally:
            if old is not None:
                os.environ["GOAL_SUPERVISOR_DISABLE_LLM_JUDGE"] = old

    def test_convergence_projection_keeps_first_principle_route_anchors(self) -> None:
        state = self.read_json(".agent/runtime/convergence_state.json")
        contract = state["goal_stack"]["goal_contract"]
        self.assertIn("away from the development workstation", contract["source_requirements"][0])
        self.assertIn("Field availability", contract["first_principles"][0]["principle"])
        self.assertEqual(contract["final_acceptance"][0]["evidence"], "field_route_test")

    def test_route_rail_requires_high_confidence_judge_confirmation(self) -> None:
        signal = {
            "signal": "ROUTE_STAGNATION",
            "status": "RAIL_ENFORCED",
            "strike_count": 4,
            "intervention": "TARGETED_RAIL",
            "deny": True,
            "reason": "Repeated blocked technical route.",
            "route_label": "Field delivery route",
            "cause_family": "ENVIRONMENT_POLICY_BLOCK",
        }
        old = os.environ.pop("GOAL_SUPERVISOR_DISABLE_LLM_JUDGE", None)
        try:
            with mock.patch.object(GOAL_COMPASS, "invoke_llm_judge", return_value={
                "status": "OK",
                "verdict": "WARN_AND_RECHECK",
                "confidence": "medium",
                "rationale": "The evidence does not justify a rail.",
                "recommended_action": "compare_routes",
                "evidence_needed": [],
                "fingerprint": "route-low-confidence",
            }):
                reviewed = GOAL_COMPASS.review_semantic_signal(signal)
            self.assertFalse(reviewed["deny"])
            self.assertEqual(reviewed["intervention"], "STRONG_WARNING")

            with mock.patch.object(GOAL_COMPASS, "invoke_llm_judge", return_value={
                "status": "OK",
                "verdict": "CONFIRM_TARGETED_RAIL",
                "confidence": "high",
                "rationale": "The same failed route is being repeated without evidence.",
                "recommended_action": "research_compare_and_switch_route",
                "evidence_needed": [],
                "fingerprint": "route-high-confidence",
            }):
                confirmed = GOAL_COMPASS.review_semantic_signal(signal)
            self.assertTrue(confirmed["deny"])
            self.assertIn("confirmed the scoped rail", confirmed["reason"])
        finally:
            if old is not None:
                os.environ["GOAL_SUPERVISOR_DISABLE_LLM_JUDGE"] = old


if __name__ == "__main__":
    unittest.main()
