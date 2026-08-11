from __future__ import annotations

import contextlib
import io
import json

try:
    from .helpers import GOAL_COMPASS, GoalCompassRepoCase, pushd
except ImportError:
    from helpers import GOAL_COMPASS, GoalCompassRepoCase, pushd

from goal_compass_runtime.deviation_incidents import (
    CLEARED_AFTER_7D,
    CORRECTED_MONITORING,
    CORRECTION_REQUIRED,
    DEVIATION_DETECTED,
    RAIL_ENFORCED,
    incident_id,
    matching_policies,
    mark_corrected,
    open_correction,
    process_write,
)
from goal_compass_runtime.observer import empty_state


GOAL = "Build a private internal Agent Registry."
POLICY = "provider marketplace"
ROOT = "src/providers/marketplace"


def patch(path: str, text: str) -> dict[str, str]:
    return {"patch": f"*** Begin Patch\n*** Add File: {path}\n+{text}\n*** End Patch"}


class DeviationIncidentStateTests(GoalCompassRepoCase):
    def test_goal_set_non_goal_is_used_by_background_rail_without_rewriting_file(self) -> None:
        self.cli(
            "goal-set", "--text", GOAL,
            "--non-goal", "Do not build a provider marketplace before MVP",
        )
        stored = self.read_json(".agent/north_star_goal.json")
        self.assertEqual(stored.get("anti_goals"), [])
        event = {
            "tool_name": "apply_patch",
            "tool_input": patch("src/providers/marketplace/index.py", "provider marketplace"),
            "tool_use_id": "structured-non-goal",
        }
        output = io.StringIO()
        with pushd(self.root), contextlib.redirect_stdout(output):
            GOAL_COMPASS.hook_pre(event)

        payload = json.loads(output.getvalue())["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", payload)
        self.assertIn("DEV-", payload["additionalContext"])
        self.assertIn("Goal contract deviation", payload["additionalContext"])
        state = self.read_json(".agent/runtime/observer_state.json")
        incident = next(iter(state["deviation_incidents"].values()))
        self.assertEqual(incident["alignment_layer"], "GOAL_CONTRACT")

    def test_north_star_antigoal_remains_a_north_star_deviation(self) -> None:
        north = self.read_json(".agent/north_star_goal.json")
        north.update({"confirmed": True, "goal": GOAL, "anti_goals": [POLICY]})
        self.write_json(".agent/north_star_goal.json", north)
        output = io.StringIO()
        with pushd(self.root), contextlib.redirect_stdout(output):
            GOAL_COMPASS.hook_pre({
                "tool_name": "apply_patch",
                "tool_input": patch(f"{ROOT}/index.py", POLICY),
                "tool_use_id": "north-star-antigoal",
            })

        payload = json.loads(output.getvalue())["hookSpecificOutput"]
        self.assertIn("North Star deviation", payload["additionalContext"])
        self.assertNotIn("Goal contract deviation", payload["additionalContext"])

    def test_goal_text_without_explicit_boundary_never_creates_a_rail(self) -> None:
        north = self.read_json(".agent/north_star_goal.json")
        north.update({
            "confirmed": True,
            "goal": "Build a private registry with a package catalog and download flow.",
            "anti_goals": [],
            "goal_definition": {
                "precise_goal": "Build a private registry with a package catalog and download flow.",
                "non_goals": [],
            },
        })
        self.write_json(".agent/north_star_goal.json", north)
        output = io.StringIO()
        with pushd(self.root), contextlib.redirect_stdout(output):
            GOAL_COMPASS.hook_pre({
                "tool_name": "apply_patch",
                "tool_input": patch("src/catalog/index.py", "package catalog download flow"),
                "tool_use_id": "positive-goal-words",
            })

        self.assertEqual(output.getvalue(), "")
        state = self.read_json(".agent/runtime/observer_state.json")
        self.assertEqual(state.get("deviation_incidents"), {})

    def test_policy_signature_matches_declarative_antigoal_variants(self) -> None:
        cases = (
            ("provider marketplace before MVP", "provider marketplace"),
            ("Do not build a provider marketplace before MVP", "provider marketplace"),
            ("enterprise RBAC platform", "RBAC platform"),
            ("Do not connect real video models", "real video model adapter"),
            ("不要建设供应商市场", "provider_marketplace"),
        )
        for policy, actual in cases:
            with self.subTest(policy=policy, actual=actual):
                self.assertEqual(matching_policies(actual, [], [policy]), [policy])

    def test_policy_signature_matches_cross_language_antigoals(self) -> None:
        cases = (
            ("enterprise RBAC platform", "企业级权限平台"),
            ("Do not connect real video models", "连接真实视频模型"),
            ("generic plugin platform", "通用插件平台"),
        )
        for policy, actual in cases:
            with self.subTest(policy=policy, actual=actual):
                self.assertEqual(matching_policies(actual, [], [policy]), [policy])

    def test_policy_signature_rejects_weak_or_partial_overlap(self) -> None:
        cases = (
            ("Do not connect real video models", "mock video model adapter"),
            ("enterprise RBAC platform", "enterprise video platform"),
            ("generic plugin marketplace", "plugin adapter"),
            ("Do not use video", "video generator"),
        )
        for policy, actual in cases:
            with self.subTest(policy=policy, actual=actual):
                self.assertEqual(matching_policies(actual, [], [policy]), [])

    def advance(
        self,
        state: dict,
        when: str,
        path: str,
        text: str,
    ) -> tuple[dict, list[dict]]:
        return process_write(
            state,
            north_star_goal=GOAL,
            policies=[POLICY],
            tool_input=patch(path, text),
            paths=[path],
            observed_at=when,
        )

    def enforced_state(self) -> tuple[dict, str]:
        state, first = self.advance(
            empty_state(), "2026-08-01T00:00:00+00:00",
            f"{ROOT}/index.py", "provider marketplace",
        )
        self.assertEqual(first[0]["status"], DEVIATION_DETECTED)
        state, second = self.advance(
            state, "2026-08-01T00:01:00+00:00",
            f"{ROOT}/routes.py", "provider marketplace",
        )
        self.assertEqual(second[0]["status"], CORRECTION_REQUIRED)
        state, third = self.advance(
            state, "2026-08-01T00:02:00+00:00",
            f"{ROOT}/service.py", "provider marketplace",
        )
        self.assertEqual(third[0]["status"], RAIL_ENFORCED)
        self.assertTrue(third[0]["deny"])
        return state, incident_id(GOAL, POLICY)

    def test_unrelated_success_never_clears_same_deviation(self) -> None:
        state, _ = self.advance(
            empty_state(), "2026-08-01T00:00:00+00:00",
            f"{ROOT}/index.py", "provider marketplace",
        )
        identifier = incident_id(GOAL, POLICY)
        state, outcomes = self.advance(
            state, "2026-08-01T00:05:00+00:00",
            "src/core/registry.py", "valid private registry work",
        )

        self.assertEqual(outcomes, [])
        self.assertEqual(state["deviation_incidents"][identifier]["strike_count"], 1)
        self.assertEqual(state["deviation_incidents"][identifier]["status"], DEVIATION_DETECTED)

    def test_legacy_goal_boundary_incident_migrates_without_duplicate_counter(self) -> None:
        state, _ = self.advance(
            empty_state(), "2026-08-01T00:00:00+00:00",
            f"{ROOT}/index.py", "provider marketplace",
        )
        state, outcomes = process_write(
            state,
            north_star_goal=GOAL,
            policies=[POLICY],
            tool_input=patch(f"{ROOT}/routes.py", "provider marketplace"),
            paths=[f"{ROOT}/routes.py"],
            observed_at="2026-08-01T00:01:00+00:00",
            policy_sources={POLICY: "GOAL_CONTRACT"},
        )

        self.assertEqual(len(state["deviation_incidents"]), 1)
        incident = next(iter(state["deviation_incidents"].values()))
        self.assertEqual(incident["alignment_layer"], "GOAL_CONTRACT")
        self.assertEqual(outcomes[0]["signal"], "GOAL_CONTRACT_DEVIATION")
        self.assertEqual(outcomes[0]["strike_count"], 2)

    def test_thirty_minute_recheck_escalates_continued_wrong_direction(self) -> None:
        state, _ = self.advance(
            empty_state(), "2026-08-01T00:00:00+00:00",
            f"{ROOT}/index.py", "provider marketplace",
        )
        state, outcomes = self.advance(
            state, "2026-08-01T00:30:01+00:00",
            f"{ROOT}/catalog.py", "add another catalog endpoint",
        )

        self.assertEqual(outcomes[0]["status"], CORRECTION_REQUIRED)
        self.assertEqual(outcomes[0]["strike_count"], 2)
        state, outcomes = self.advance(
            state, "2026-08-01T01:00:02+00:00",
            f"{ROOT}/download.py", "continue the same catalog branch",
        )
        self.assertEqual(outcomes[0]["status"], RAIL_ENFORCED)
        self.assertTrue(outcomes[0]["deny"])

    def test_third_confirmation_enforces_only_the_wrong_direction(self) -> None:
        state, identifier = self.enforced_state()
        state, unrelated = self.advance(
            state, "2026-08-01T00:03:00+00:00",
            "src/core/registry.py", "continue private registry implementation",
        )

        self.assertEqual(unrelated, [])
        self.assertEqual(state["deviation_incidents"][identifier]["status"], RAIL_ENFORCED)

    def test_scoped_correction_lane_and_corrected_monitoring(self) -> None:
        state, identifier = self.enforced_state()
        state, opened = open_correction(
            state,
            identifier=identifier,
            reason="remove the rejected marketplace branch",
            allowed_paths=[ROOT],
            observed_at="2026-08-01T00:03:00+00:00",
        )
        state, correction = self.advance(
            state, "2026-08-01T00:04:00+00:00",
            f"{ROOT}/service.py", "replace with internal registry route",
        )
        state, corrected = mark_corrected(
            state,
            identifier=identifier,
            evidence="marketplace route removed and private registry tests pass",
            observed_at="2026-08-01T00:05:00+00:00",
        )

        self.assertEqual(opened["status"], "CORRECTION_IN_PROGRESS")
        self.assertEqual(correction, [])
        self.assertEqual(corrected["status"], CORRECTED_MONITORING)
        self.assertEqual(corrected["strike_count"], 3)

    def test_recurrence_during_seven_day_window_immediately_reenforces_rail(self) -> None:
        state, identifier = self.enforced_state()
        state, _ = open_correction(
            state,
            identifier=identifier,
            reason="remove rejected scope",
            allowed_paths=[ROOT],
            observed_at="2026-08-01T00:03:00+00:00",
        )
        state, _ = mark_corrected(
            state,
            identifier=identifier,
            evidence="rejected scope removed",
            observed_at="2026-08-01T00:04:00+00:00",
        )
        state, outcomes = self.advance(
            state, "2026-08-06T00:00:00+00:00",
            f"{ROOT}/return.py", "provider marketplace",
        )

        self.assertTrue(outcomes[0]["deny"])
        self.assertEqual(outcomes[0]["status"], RAIL_ENFORCED)
        self.assertEqual(state["deviation_incidents"][identifier]["clean_window"], None)

    def test_idle_time_does_not_clear_but_active_clean_week_does(self) -> None:
        state, identifier = self.enforced_state()
        state, _ = open_correction(
            state,
            identifier=identifier,
            reason="remove rejected scope",
            allowed_paths=[ROOT],
            observed_at="2026-08-01T00:03:00+00:00",
        )
        state, _ = mark_corrected(
            state,
            identifier=identifier,
            evidence="rejected scope removed",
            observed_at="2026-08-01T00:04:00+00:00",
        )
        state, _ = self.advance(
            state, "2026-08-09T00:00:00+00:00",
            "src/core/day_one.py", "aligned work",
        )
        self.assertEqual(state["deviation_incidents"][identifier]["status"], CORRECTED_MONITORING)
        state, _ = self.advance(
            state, "2026-08-10T00:00:00+00:00",
            "src/core/day_two.py", "aligned work",
        )
        state, _ = self.advance(
            state, "2026-08-11T00:00:00+00:00",
            "src/core/day_three.py", "aligned work",
        )

        incident = state["deviation_incidents"][identifier]
        self.assertEqual(incident["status"], CLEARED_AFTER_7D)
        self.assertEqual(incident["strike_count"], 0)
        self.assertTrue(any(row["action"] == "CLEARED_AFTER_7D" for row in incident["history"]))

    def test_full_hook_and_cli_expose_persistent_incident_state(self) -> None:
        north = self.read_json(".agent/north_star_goal.json")
        north.update({"confirmed": True, "goal": GOAL, "anti_goals": [POLICY]})
        self.write_json(".agent/north_star_goal.json", north)

        outputs: list[str] = []
        for index in range(3):
            event = {
                "tool_name": "apply_patch",
                "tool_input": patch(f"{ROOT}/{index}.py", POLICY),
                "tool_use_id": f"deviation-{index}",
            }
            output = io.StringIO()
            with pushd(self.root), contextlib.redirect_stdout(output):
                GOAL_COMPASS.hook_pre(event)
            outputs.append(output.getvalue())

        third = json.loads(outputs[-1])["hookSpecificOutput"]
        self.assertEqual(third["permissionDecision"], "deny")
        status = self.json_run("status")
        summary = status["observer"]["deviations"]
        self.assertEqual(summary["rail_enforced_count"], 1)
        identifier = summary["incidents"][0]["incident_id"]

        opened = self.json_run(
            "deviation-correct", "--incident", identifier,
            "--reason", "remove the rejected marketplace implementation",
        )
        correction_output = io.StringIO()
        with pushd(self.root), contextlib.redirect_stdout(correction_output):
            GOAL_COMPASS.hook_pre({
                "tool_name": "apply_patch",
                "tool_input": patch(f"{ROOT}/2.py", "restore private registry behavior"),
                "tool_use_id": "deviation-correction-write",
            })
        corrected = self.json_run(
            "deviation-corrected", "--incident", identifier,
            "--evidence", "private registry implementation restored",
        )
        self.assertEqual(opened["status"], "CORRECTION_IN_PROGRESS")
        self.assertEqual(correction_output.getvalue(), "")
        self.assertEqual(corrected["status"], CORRECTED_MONITORING)


if __name__ == "__main__":
    import unittest

    unittest.main()
