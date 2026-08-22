from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from .helpers import GOAL_COMPASS, HARNESS_ROOT, GoalCompassRepoCase, pushd
except ImportError:
    from helpers import GOAL_COMPASS, HARNESS_ROOT, GoalCompassRepoCase, pushd

from goal_compass_runtime.capability_profiles import (
    CapabilityProfileError,
    explain_capability,
    resolve_profile,
)


class CapabilityProfileBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        contracts = HARNESS_ROOT / ".agent" / "contracts"
        cls.catalog = json.loads((contracts / "capability_catalog.v1.json").read_text(encoding="utf-8"))
        cls.profile = json.loads((contracts / "goal_profile_2_8_10.v1.json").read_text(encoding="utf-8"))

    def test_catalog_freezes_all_capabilities_with_unique_owners(self) -> None:
        rows = self.catalog["capabilities"]
        self.assertEqual(len(rows), 57)
        self.assertEqual([row["number"] for row in rows], list(range(1, 58)))
        self.assertEqual(len({row["id"] for row in rows}), 57)
        self.assertTrue(all(row["owner"] for row in rows))

    def test_catalog_maps_every_real_cli_command_once(self) -> None:
        parser = GOAL_COMPASS.build_parser()
        subparsers = next(action for action in parser._actions if hasattr(action, "choices") and action.choices)
        actual = set(subparsers.choices)
        owners: dict[str, list[str]] = {}
        for row in self.catalog["capabilities"]:
            for command in row["commands"]:
                owners.setdefault(command, []).append(row["id"])
        self.assertEqual(set(owners), actual)
        self.assertTrue(all(len(values) == 1 for values in owners.values()))
        self.assertEqual(len(actual), 36)

    def test_goal_profile_covers_every_capability_with_valid_compound_policy(self) -> None:
        ids = {row["id"] for row in self.catalog["capabilities"]}
        policies = self.profile["policies"]
        self.assertEqual(set(policies), ids)
        dimensions = self.profile["policy_dimensions"]
        defaults = self.profile["defaults"]
        for policy in policies.values():
            merged = {**defaults, **policy}
            for key in ("availability", "obligation", "invocation", "enforcement"):
                self.assertIn(merged[key], dimensions[key])
            self.assertIsInstance(merged["preconditions"], list)

    def test_goal_profile_preserves_required_optional_and_targeted_boundaries(self) -> None:
        policies = self.profile["policies"]
        self.assertEqual(policies["goal.north_star"]["obligation"], "required")
        self.assertEqual(policies["goal.native_sync"]["enforcement"], "targeted_block")
        self.assertEqual(policies["goal.final_certification"]["obligation"], "required")
        self.assertEqual(policies["observer.low_noise"]["invocation"], "background")
        self.assertEqual(policies["ticket.lifecycle"]["obligation"], "optional")
        self.assertEqual(policies["company.roles"]["obligation"], "optional")
        self.assertEqual(policies["goal.hierarchical_workstreams"]["obligation"], "conditional")
        self.assertEqual(policies["goal.hierarchical_workstreams"]["enforcement"], "targeted_block")
        self.assertEqual(policies["janitor.classification"]["obligation"], "optional")
        self.assertEqual(policies["janitor.quarantine_manifest"]["preconditions"][-1], "mark_only")

    def test_profile_contains_no_approval_workflow_language(self) -> None:
        text = json.dumps(self.profile, ensure_ascii=False).lower()
        for forbidden in ("board approval", "role approval", "decision approved", "final signoff"):
            self.assertNotIn(forbidden, text)

    def test_general_profile_resolves_every_capability(self) -> None:
        resolved = resolve_profile("general-initial")
        self.assertEqual(resolved["capability_count"], 57)
        self.assertEqual(len(resolved["policies"]), 57)
        self.assertEqual(resolved["policies"]["goal.north_star"]["obligation"], "optional")
        self.assertEqual(resolved["policies"]["observer.low_noise"]["obligation"], "required")
        self.assertEqual(resolved["policies"]["instruction.correction_canonicalization"]["obligation"], "required")
        self.assertEqual(resolved["policies"]["instruction.compaction_return"]["obligation"], "required")
        self.assertEqual(resolved["policies"]["goal.hierarchical_workstreams"]["obligation"], "optional")

    def test_goal_profile_inherits_general_and_promotes_goal_contract(self) -> None:
        resolved = resolve_profile("goal-2.8.10-compatibility")
        self.assertEqual(resolved["policies"]["goal.north_star"]["obligation"], "required")
        self.assertEqual(resolved["policies"]["state.atomic_store"]["obligation"], "required")
        self.assertEqual(resolved["policies"]["state.atomic_store"]["enforcement"], "targeted_block")
        explained = explain_capability("goal-2.8.10-compatibility", "observer.low_noise")
        self.assertEqual(explained["sources"], ["general-initial:defaults", "general-initial", "goal-2.8.10-compatibility"])

    def test_goal_profile_cannot_weaken_general_required_policy(self) -> None:
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            for source in (HARNESS_ROOT / ".agent" / "contracts").glob("*.json"):
                (root / source.name).write_bytes(source.read_bytes())
            path = root / "goal_profile_2_8_10.v1.json"
            profile = json.loads(path.read_text(encoding="utf-8"))
            profile["policies"]["state.atomic_store"] = {
                "obligation": "optional",
                "enforcement": "none",
            }
            path.write_text(json.dumps(profile), encoding="utf-8")
            with self.assertRaisesRegex(CapabilityProfileError, "cannot weaken inherited obligation"):
                resolve_profile("goal-2.8.10-compatibility", root)


class CapabilityProfileRuntimeTests(GoalCompassRepoCase):
    def test_non_goal_project_uses_general_profile_without_requesting_north_star(self) -> None:
        status = self.json_run("status")

        self.assertEqual(status["status"], "IDLE")
        self.assertEqual(status["required_action"], "continue_normal_execution")
        self.assertEqual(status["profile"], "general-initial")
        self.assertIn("no native Goal", status["reason"])
        with pushd(self.root):
            self.assertTrue(GOAL_COMPASS.observer_enabled())

    def test_confirmed_goal_project_uses_goal_compatibility_profile(self) -> None:
        self.goal_video()
        status = self.json_run("status", "--verbose")

        self.assertEqual(status["capability_profile"]["profile_id"], "goal-2.8.10-compatibility")
        self.assertTrue(status["north_star"]["confirmed"])

    def test_profile_load_failure_keeps_ordinary_execution_fail_open(self) -> None:
        with mock.patch.object(
            GOAL_COMPASS,
            "resolve_capability_profile",
            side_effect=GOAL_COMPASS.CapabilityProfileError("missing profile fixture"),
        ), pushd(self.root):
            summary = GOAL_COMPASS.capability_profile_summary()
            enabled = GOAL_COMPASS.observer_enabled()

        self.assertEqual(summary["status"], "LEGACY_FAIL_OPEN")
        self.assertFalse(summary["ordinary_execution_blocked"])
        self.assertTrue(enabled)


if __name__ == "__main__":
    unittest.main()
