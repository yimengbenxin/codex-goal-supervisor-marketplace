from __future__ import annotations

import json
from unittest import mock

try:
    from .helpers import GOAL_COMPASS, GoalCompassRepoCase, pushd
except ImportError:
    from helpers import GOAL_COMPASS, GoalCompassRepoCase, pushd

from goal_compass_runtime import validation_catalog


class ValidationStatusTests(GoalCompassRepoCase):
    def test_validation_catalog_is_parsed_once_until_it_changes(self) -> None:
        validation_catalog.invalidate()
        original_loads = json.loads
        with pushd(self.root), mock.patch.object(validation_catalog.json, "loads", wraps=original_loads) as loads:
            for _ in range(50):
                GOAL_COMPASS.catalog()
            self.assertEqual(loads.call_count, 1)

            data = dict(GOAL_COMPASS.catalog())
            data["new_validation"] = {"argv": ["{python}", "-c", "pass"]}
            GOAL_COMPASS.write_json(GOAL_COMPASS.VALIDATION_CATALOG, data)
            GOAL_COMPASS.catalog()
            self.assertEqual(loads.call_count, 2)

    def test_check_returns_needs_validation_when_commands_required(self) -> None:
        self.goal_video()
        self.install_validation("ok_validation", "import sys; sys.exit(0)")
        self.write_json(".agent/tickets/pending/VALIDATION.json", self.make_validation_ticket("ok_validation"))
        self.cli("start", ".agent/tickets/pending/VALIDATION.json")
        result = self.json_run("check")
        self.assertEqual(result["status"], "NEEDS_VALIDATION")
        self.assertEqual(result["suggested_action"], "run close or check --run-validation")

    def test_needs_validation_surfaces_janitor_noise_as_advisory(self) -> None:
        self.goal_video()
        self.install_validation("ok_validation", "import sys; sys.exit(0)")
        ticket = self.make_validation_ticket("ok_validation")
        ticket["allowed_paths"] = ["src/video/mock/**"]
        self.write_json(".agent/tickets/pending/VALIDATION-NOISE.json", ticket)
        self.cli("start", ".agent/tickets/pending/VALIDATION-NOISE.json")
        noise = self.root / "src" / "video" / "mock" / "stale-provider-marketplace.tmp"
        noise.parent.mkdir(parents=True, exist_ok=True)
        noise.write_text("full enterprise provider marketplace scaffold\n", encoding="utf-8")

        proc = self.cli("check", check=False)
        result = json.loads(proc.stdout)

        self.assertEqual(proc.returncode, 0)
        self.assertEqual(result["status"], "NEEDS_VALIDATION")
        self.assertEqual(result["prune_check"]["status"], "NOISE_RISK")
        self.assertEqual(result["suggested_action"], "run close or check --run-validation")
        self.assertEqual(result["cleanup_advisory"], "prune_plan")
        self.assertEqual(
            result["mdcp"]["layer_3_janitor_auditor"]["auditor"]["required_action"],
            "run_validation",
        )

    def test_check_run_validation_can_return_pass_ready(self) -> None:
        self.goal_video()
        self.install_validation("ok_validation", "import sys; sys.exit(0)")
        self.write_json(".agent/tickets/pending/VALIDATION.json", self.make_validation_ticket("ok_validation"))
        self.cli("start", ".agent/tickets/pending/VALIDATION.json")
        result = self.json_run("check", "--run-validation")
        self.assertEqual(result["status"], "PASS_READY")

    def test_check_run_validation_failure_is_not_on_track(self) -> None:
        self.goal_video()
        self.install_validation("missing_test", "import sys; sys.exit(1)")
        self.write_json(".agent/tickets/pending/MISSING.json", self.make_validation_ticket("missing_test"))
        self.cli("start", ".agent/tickets/pending/MISSING.json")
        proc = self.cli("check", "--run-validation", check=False)
        result = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 0)
        self.assertIn(result["status"], {"VALIDATION_FAILED", "FAIL"})
        self.assertNotEqual(result["status"], "ON_TRACK")
        self.assertNotEqual(result["status"], "PASS_READY")
        self.assertNotEqual(result["suggested_action"], "continue")

    def test_close_validation_failure_cannot_pass(self) -> None:
        self.goal_video()
        self.install_validation("bad_validation", "import sys; sys.exit(1)")
        self.write_json(".agent/tickets/pending/BAD.json", self.make_validation_ticket("bad_validation"))
        self.cli("start", ".agent/tickets/pending/BAD.json")
        self.complete_company_runtime()
        result = self.json_run("close", check=False)
        self.assertEqual(result["status"], "NOT_CERTIFIED")
        self.assertEqual(result["ticket_status"], "ACTIVE")
        self.assertIn("bad_validation", json.dumps(result))

    def test_validation_pipeline_stops_after_first_failed_node(self) -> None:
        self.goal_video()
        self.install_validation("01_build", "import sys; sys.exit(1)")
        self.install_validation(
            "02_contracts",
            "from pathlib import Path; Path('contracts-ran.txt').write_text('unexpected')",
        )
        self.install_validation(
            "03_validate",
            "from pathlib import Path; Path('validate-ran.txt').write_text('unexpected')",
        )
        ticket = self.make_validation_ticket("01_build")
        ticket["ticket_id"] = "FAIL-FAST-VALIDATION"
        ticket["validation_ids"] = ["01_build", "02_contracts", "03_validate"]
        ticket["acceptance"]["commands_pass"] = ["01_build", "02_contracts", "03_validate"]
        self.write_json(".agent/tickets/pending/FAIL-FAST-VALIDATION.json", ticket)
        self.cli("start", ".agent/tickets/pending/FAIL-FAST-VALIDATION.json")

        result = self.json_run("check", "--run-validation", check=False)

        self.assertEqual(result["status"], "VALIDATION_FAILED")
        self.assertEqual(result["failure_class"], "EXECUTION_FAILED")
        self.assertFalse((self.root / "contracts-ran.txt").exists())
        self.assertFalse((self.root / "validate-ran.txt").exists())
        self.assertEqual(result["validation"]["root_cause"]["command_id"], "01_build")
        self.assertEqual(result["validation"]["skipped_ids"], ["02_contracts", "03_validate"])
        self.assertEqual(result["validation"]["suppressed_cascade_count"], 2)

    def test_validation_failure_is_not_overwritten_by_janitor_sprawl(self) -> None:
        self.goal_video()
        self.install_validation("build_failure", "import sys; sys.exit(1)")
        ticket = self.make_validation_ticket("build_failure")
        ticket["ticket_id"] = "ROOT-CAUSE-PRIORITY"
        ticket["allowed_paths"] = ["src/video/mock/**"]
        self.write_json(".agent/tickets/pending/ROOT-CAUSE-PRIORITY.json", ticket)
        self.cli("start", ".agent/tickets/pending/ROOT-CAUSE-PRIORITY.json")
        noise = self.root / "src" / "video" / "mock"
        noise.mkdir(parents=True, exist_ok=True)
        for index in range(2):
            (noise / f"stale-{index}.txt").write_text(
                "autogenerated stale keyword experiment; no author; unreferenced\n",
                encoding="utf-8",
            )

        result = self.json_run("check", "--run-validation", check=False)

        self.assertEqual(result["status"], "VALIDATION_FAILED")
        self.assertEqual(result["failure_class"], "EXECUTION_FAILED")
        self.assertNotEqual(result["suggested_action"], "prune_plan")
        self.assertEqual(result["prune_check"]["status"], "ARTIFACT_SPRAWL")
        self.assertGreaterEqual(result["suppressed_secondary_findings"], 1)
