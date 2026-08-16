from __future__ import annotations

import json

try:
    from .helpers import GoalCompassRepoCase
except ImportError:
    from helpers import GoalCompassRepoCase


class OnboardScanTests(GoalCompassRepoCase):
    def test_onboard_scan_ignores_goal_compass_example_tickets(self) -> None:
        self.goal_video()
        scan = self.json_run("onboard-scan", "--verbose", check=False)
        artifacts = {item["artifact"] for item in scan["inventory"]}

        self.assertFalse(any(path.startswith(".agent/tickets/examples/") for path in artifacts))

    def test_onboard_scan_ignores_empty_backlog(self) -> None:
        self.goal_video()
        self.assertEqual((self.root / ".agent" / "backlog.jsonl").read_text(encoding="utf-8"), "")

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        artifacts = {item["artifact"] for item in scan["inventory"]}

        self.assertNotIn(".agent/backlog.jsonl", artifacts)

    def test_onboard_scan_can_use_done_tickets_as_low_weight_history(self) -> None:
        self.goal_video()
        done = self.root / ".agent" / "tickets" / "done"
        done.mkdir(parents=True, exist_ok=True)
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = "DONE-HISTORY-001"
        ticket["status"] = "PASS"
        self.write_json(".agent/tickets/done/DONE-HISTORY-001.json", ticket)

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        artifacts = {item["artifact"] for item in scan["inventory"]}

        self.assertIn(".agent/tickets/done/DONE-HISTORY-001.json", artifacts)

    def test_onboard_scan_finds_committed_rbac_noise(self) -> None:
        rbac = self.root / "src" / "security" / "rbac" / "roles.ts"
        rbac.parent.mkdir(parents=True)
        rbac.write_text("// AI video generation RBAC roles\nexport const roles = [];\n", encoding="utf-8")
        self.commit_paths("src/security/rbac/roles.ts")
        self.goal_video()
        scan = self.json_run("onboard-scan", "--verbose", check=False)
        row = {item["artifact"]: item for item in scan["inventory"]}["src/security/rbac/roles.ts"]
        self.assertIn(row["classification"], {"QUARANTINE_CANDIDATE", "REVIEW_REQUIRED"})

    def test_onboard_scan_finds_committed_marketplace_noise(self) -> None:
        market = self.root / "src" / "providers" / "marketplace" / "index.ts"
        market.parent.mkdir(parents=True)
        market.write_text("// provider marketplace for AI video generation\nexport const x = [];\n", encoding="utf-8")
        self.commit_paths("src/providers/marketplace/index.ts")
        self.goal_video()
        scan = self.json_run("onboard-scan", "--verbose", check=False)
        row = {item["artifact"]: item for item in scan["inventory"]}["src/providers/marketplace/index.ts"]
        self.assertIn(row["classification"], {"QUARANTINE_CANDIDATE", "REVIEW_REQUIRED"})

    def test_onboard_scan_is_not_changed_files_only(self) -> None:
        doc = self.root / "docs" / "security-roadmap.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("# Security roadmap\nFuture RBAC and provider marketplace for AI video generation.\n", encoding="utf-8")
        self.commit_paths("docs/security-roadmap.md")
        self.goal_video()
        scan = self.json_run("onboard-scan", "--verbose", check=False)
        row = {item["artifact"]: item for item in scan["inventory"]}["docs/security-roadmap.md"]
        self.assertIn(row["classification"], {"QUARANTINE_CANDIDATE", "REVIEW_REQUIRED"})

    def test_backlog_candidate_does_not_claim_strong_north_star_mapping(self) -> None:
        rbac = self.root / "src" / "security" / "rbac" / "full.ts"
        rbac.parent.mkdir(parents=True)
        rbac.write_text("// RBAC provider marketplace for AI automatic video generation\nexport const roles = [];\n", encoding="utf-8")
        self.goal_video()
        scan = self.json_run("onboard-scan", "--verbose", check=False)
        row = {item["artifact"]: item for item in scan["inventory"]}["src/security/rbac/full.ts"]
        self.assertIn(row["classification"], {"QUARANTINE_CANDIDATE", "REVIEW_REQUIRED"})
        self.assertNotEqual(row.get("north_star_mapping"), "Build an AI automatic video generation system.")
        self.assertRegex(row["reason"], r"future scope|backlog|anti_patterns|Heavy-scope|Negative-scope|RBAC|provider marketplace")

    def test_onboard_scan_no_destructive_apply_without_north_star(self) -> None:
        rbac = self.root / "src" / "security" / "rbac" / "roles.ts"
        rbac.parent.mkdir(parents=True)
        rbac.write_text("export const roles = [];\n", encoding="utf-8")
        proc = self.cli("onboard-scan", check=False)
        scan = json.loads(proc.stdout)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(scan["status"], "NEEDS_CONFIRMATION")
        self.assertEqual(scan["alignment_status"], "UNKNOWN")
        self.assertEqual(scan["required_action"], "confirm_north_star")
        proc = self.cli("prune-apply", "--confirm", "--delete", check=False)
        self.assertNotEqual(proc.returncode, 0)

    def test_onboard_scan_unknown_does_not_force_mismatch_with_confirmed_north_star(self) -> None:
        self.cli(
            "goal-set",
            "--text",
            "Deliver a deterministic packaging artwork release station with reproducible evidence.",
        )
        (self.root / "README.md").write_text(
            "Packaging artwork release station with deterministic print evidence.\n",
            encoding="utf-8",
        )

        scan = self.json_run("onboard-scan", check=False)

        self.assertEqual(scan["detected_project_goal"], "Unknown project goal.")
        self.assertEqual(scan["alignment_status"], "UNKNOWN")
        self.assertEqual(scan["status"], "NEEDS_PROJECT_EVIDENCE")
        self.assertEqual(scan["required_action"], "add_project_goal_evidence")
        self.assertFalse(scan["requires_user_confirmation"])
        self.assertEqual(scan["evidence_summary"]["contradicting"], 0)

    def test_onboard_scan_defaults_to_summary_and_verbose_keeps_inventory(self) -> None:
        self.goal_video()

        compact = self.cli("onboard-scan", check=False)
        detailed = self.cli("onboard-scan", "--verbose", check=False)
        summary = json.loads(compact.stdout)
        report = json.loads(detailed.stdout)

        self.assertLess(len(compact.stdout.encode("utf-8")), 5000)
        self.assertNotIn("inventory", summary)
        self.assertIn("inventory_summary", summary)
        self.assertIn("report_paths", summary)
        self.assertIn("inventory", report)
        stored = self.read_json(".agent/goal_alignment_report.json")
        self.assertIn("inventory", stored)

    def test_onboard_scan_large_aux_tree_does_not_crowd_out_core_roots(self) -> None:
        bulk = self.root / "aaa_bulk"
        bulk.mkdir()
        for index in range(1610):
            (bulk / f"cache_{index:04d}.txt").write_text("cached research output\n", encoding="utf-8")
        core = self.root / "src" / "video" / "mock" / "generator.ts"
        core.parent.mkdir(parents=True)
        core.write_text("export const promptToVideoArtifact = () => 'mock.mp4';\n", encoding="utf-8")
        self.goal_video()

        scan = self.json_run("onboard-scan", "--verbose", check=False, timeout=10)
        artifacts = {item["artifact"] for item in scan["inventory"]}

        self.assertIn("src/video/mock/generator.ts", artifacts)
        self.assertTrue(scan["scan_summary"]["incomplete"])

    def test_binary_tree_does_not_consume_text_scan_quota(self) -> None:
        bulk = self.root / "aaa_assets"
        bulk.mkdir()
        for index in range(1650):
            (bulk / f"asset_{index:04d}.png").write_bytes(b"\x89PNG\r\n")
        sentinel = self.root / "zzz" / "core.py"
        sentinel.parent.mkdir()
        sentinel.write_text("print('core')\n", encoding="utf-8")
        self.goal_video()

        scan = self.json_run("onboard-scan", "--verbose", check=False, timeout=10)
        artifacts = {item["artifact"] for item in scan["inventory"]}

        self.assertIn("zzz/core.py", artifacts)
        self.assertGreaterEqual(scan["scan_summary"]["skipped_non_text"], 1650)

    def test_binary_cache_is_inventory_metadata_and_marked_only_candidate(self) -> None:
        cache = self.root / "models" / ".cache" / "feature_matrix.bin"
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b"\x00\x01fixture-cache")
        self.cli("goal-set", "--text", "Build a bounded forecasting workflow.")

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        row = {item["artifact"]: item for item in scan["inventory"]}["models/.cache/feature_matrix.bin"]

        self.assertEqual(row["classification"], "QUARANTINE_CANDIDATE")
        self.assertEqual(row["janitor_action_limit"], "MARK_ONLY")
        self.assertFalse(row["delete_safe"])
        self.assertGreaterEqual(scan["scan_summary"]["metadata_only_artifacts"], 1)
