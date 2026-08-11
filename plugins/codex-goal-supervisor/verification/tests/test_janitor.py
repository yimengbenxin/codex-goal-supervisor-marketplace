from __future__ import annotations

import json
from unittest import mock

try:
    from .helpers import GOAL_COMPASS, GoalCompassRepoCase
except ImportError:
    from helpers import GOAL_COMPASS, GoalCompassRepoCase


class JanitorTests(GoalCompassRepoCase):
    def test_current_ticket_prune_check_does_not_scan_full_repository(self) -> None:
        self.start_video()

        with mock.patch.object(GOAL_COMPASS, "scan_artifacts", side_effect=AssertionError("full scan is not allowed")):
            result = self.json_run("prune-check", check=False)

        self.assertIn(result["status"], {"CLEAN", "REVIEW_REQUIRED", "NOT_REQUIRED"})
        self.assertEqual(result["scope"], "current-ticket")

    def test_janitor_keeps_core_mock_generator(self) -> None:
        self.goal_video()
        generator = self.root / "src" / "video" / "mock" / "generator.ts"
        generator.parent.mkdir(parents=True)
        generator.write_text("export function generateMockVideoArtifact(){ return 'mock.mp4'; }\n", encoding="utf-8")
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = "CORE-MOCK-GENERATOR"
        ticket["acceptance"]["files_exist"].append("src/video/mock/generator.ts")
        self.write_json(".agent/tickets/pending/CORE-MOCK-GENERATOR.json", ticket)
        self.cli("start", ".agent/tickets/pending/CORE-MOCK-GENERATOR.json")
        scan = self.json_run("onboard-scan", "--verbose", check=False)
        row = {item["artifact"]: item for item in scan["inventory"]}["src/video/mock/generator.ts"]
        self.assertIn(row["classification"], {"KEEP", "PROTECTED"})
        self.assertNotEqual(row["classification"], "NOISE_RISK")

    def test_janitor_protects_validation_test(self) -> None:
        self.start_video()
        test = self.root / "tests" / "video" / "mock-video-pipeline.test.ts"
        test.parent.mkdir(parents=True)
        test.write_text("test('mock artifact path', () => {});\n", encoding="utf-8")
        plan = self.json_run("prune-plan")
        row = {item["target"]: item for item in plan["items"]}["tests/video/mock-video-pipeline.test.ts"]
        self.assertEqual(row["classification"], "PROTECTED")

    def test_janitor_does_not_protect_rbac_with_video_words(self) -> None:
        self.start_video()
        rbac = self.root / "src" / "security" / "rbac" / "full.ts"
        rbac.parent.mkdir(parents=True)
        rbac.write_text("// prompt routing video artifact AI video generation\nexport const roles = [];\n", encoding="utf-8")
        plan = self.json_run("prune-plan")
        row = {item["target"]: item for item in plan["items"]}["src/security/rbac/full.ts"]
        self.assertNotEqual(row["classification"], "PROTECTED")
        self.assertIn(row["classification"], {"QUARANTINE_CANDIDATE", "BACKLOG_CANDIDATE", "REVIEW_REQUIRED", "SIMPLIFY"})

    def test_janitor_does_not_protect_rbac_even_if_it_mentions_acceptance(self) -> None:
        self.start_video()
        rbac = self.root / "src" / "security" / "rbac" / "mock_ref.ts"
        rbac.parent.mkdir(parents=True)
        rbac.write_text(
            "RBAC provider marketplace for mock video pipeline test and returned mock artifact path.\n",
            encoding="utf-8",
        )
        plan = self.json_run("prune-plan")
        row = {item["target"]: item for item in plan["items"]}["src/security/rbac/mock_ref.ts"]
        self.assertNotEqual(row["classification"], "PROTECTED")
        self.assertIn(row["classification"], {"QUARANTINE_CANDIDATE", "BACKLOG_CANDIDATE", "REVIEW_REQUIRED"})
        reason = json.dumps({"reason": row.get("reason"), "signals": row.get("signals", [])}, ensure_ascii=False)
        self.assertRegex(reason, r"RBAC|provider marketplace|anti_pattern|files_not_changed")

    def test_janitor_does_not_protect_marketplace_with_video_words(self) -> None:
        self.start_video()
        market = self.root / "src" / "providers" / "marketplace" / "index.ts"
        market.parent.mkdir(parents=True)
        market.write_text("// for AI video generation prompt to video artifact\nexport const x = [];\n", encoding="utf-8")
        plan = self.json_run("prune-plan")
        row = {item["target"]: item for item in plan["items"]}["src/providers/marketplace/index.ts"]
        self.assertNotEqual(row["classification"], "PROTECTED")
        self.assertIn(row["classification"], {"QUARANTINE_CANDIDATE", "REVIEW_REQUIRED", "SIMPLIFY"})

    def test_files_not_changed_is_not_protected_mapping(self) -> None:
        self.start_video()
        ui = self.root / "src" / "ui" / "panel.ts"
        ui.parent.mkdir(parents=True)
        ui.write_text("// prompt to video artifact UI\n", encoding="utf-8")
        plan = self.json_run("prune-plan")
        row = {item["target"]: item for item in plan["items"]}["src/ui/panel.ts"]
        self.assertNotEqual(row["classification"], "PROTECTED")
        self.assertEqual(row["classification"], "QUARANTINE_CANDIDATE")
        self.assertIn("files_not_changed_violation", row["signals"])

    def test_agent_registry_internal_marketplace_ui_is_not_noise(self) -> None:
        self.start_agent_registry()
        ui = self.root / "app" / "static" / "index.html"
        ui.parent.mkdir(parents=True)
        ui.write_text("<h1>Internal Agent Marketplace / Skill Hub</h1>\n", encoding="utf-8")
        plan = self.json_run("prune-plan")
        row = {item["target"]: item for item in plan["items"]}["app/static/index.html"]
        self.assertIn(row["classification"], {"KEEP", "PROTECTED"})
        self.assertNotIn("future_scope", row.get("signals", []))

    def test_agent_registry_dependency_manifest_is_kept(self) -> None:
        self.start_agent_registry()
        req = self.root / "requirements.txt"
        req.write_text("fastapi\nuvicorn\npytest\n", encoding="utf-8")
        plan = self.json_run("prune-plan")
        row = {item["target"]: item for item in plan["items"]}["requirements.txt"]
        self.assertIn(row["classification"], {"KEEP", "PROTECTED"})
        self.assertNotEqual(row.get("suggested_classification"), "NOISE_RISK")

    def test_agent_registry_design_qa_evidence_is_not_heavy_scope_noise(self) -> None:
        self.start_agent_registry()
        qa = self.root / "design-qa.md"
        qa.write_text("Full UI checked against generic mockup wording for Skill Hub dashboard polish.\n", encoding="utf-8")
        plan = self.json_run("prune-plan")
        row = {item["target"]: item for item in plan["items"]}["design-qa.md"]
        self.assertIn(row["classification"], {"KEEP", "PROTECTED"})
        self.assertNotIn("future_scope", row.get("signals", []))

    def test_goal_md_is_always_protected_after_confirmation(self) -> None:
        goal_file = self.root / "GOAL.md"
        goal_file.write_text("# Product goal\nBuild a specialist product geometry operating system.\n", encoding="utf-8")
        self.cli("goal-set", "--text", "Build a specialist product geometry operating system.")

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        row = {item["artifact"]: item for item in scan["inventory"]}["GOAL.md"]

        self.assertEqual(row["classification"], "PROTECTED")

    def test_content_only_north_star_copy_is_not_protected(self) -> None:
        goal = "Build a hospital bed-capacity planning tool for regional operations teams."
        self.cli("goal-set", "--text", goal)
        path = self.root / "archive" / "old-concept.md"
        path.parent.mkdir(parents=True)
        path.write_text(goal + "\n", encoding="utf-8")

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        row = {item["artifact"]: item for item in scan["inventory"]}["archive/old-concept.md"]

        self.assertEqual(row["classification"], "REVIEW_REQUIRED")
        self.assertNotEqual(row["classification"], "PROTECTED")
        self.assertIn("content_only_north_star_claim", row["signals"])

    def test_project_readme_can_be_protected_as_north_star_anchor(self) -> None:
        goal = "Build a hospital bed-capacity planning tool for regional operations teams."
        (self.root / "README.md").write_text(goal + "\n", encoding="utf-8")
        self.cli("goal-set", "--text", goal)

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        row = {item["artifact"]: item for item in scan["inventory"]}["README.md"]

        self.assertEqual(row["classification"], "PROTECTED")
        self.assertEqual(row["evidence_tier"], "PROJECT_ANCHOR")

    def test_nested_goal_filename_cannot_impersonate_root_goal(self) -> None:
        self.goal_video()
        nested = self.root / "docs" / "archive" / "GOAL.md"
        nested.parent.mkdir(parents=True)
        nested.write_text("Full RBAC provider marketplace compliance framework.\n", encoding="utf-8")

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        row = {item["artifact"]: item for item in scan["inventory"]}["docs/archive/GOAL.md"]

        self.assertNotEqual(row["classification"], "PROTECTED")

    def test_project_anchor_non_goal_language_is_review_not_quarantine(self) -> None:
        goal = "Build a hospital bed-capacity planning tool for regional operations teams."
        (self.root / "README.md").write_text(
            goal + "\nNon-goals: full RBAC, provider marketplace, and compliance framework.\n",
            encoding="utf-8",
        )
        self.cli("goal-set", "--text", goal)

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        row = {item["artifact"]: item for item in scan["inventory"]}["README.md"]

        self.assertEqual(row["classification"], "REVIEW_REQUIRED")
        self.assertIn("project_anchor_with_negative_language", row["signals"])

    def test_inactive_pass_ticket_does_not_keep_protecting_old_acceptance(self) -> None:
        self.goal_video()
        old = self.root / "src" / "providers" / "marketplace.py"
        old.parent.mkdir(parents=True)
        old.write_text("Full RBAC provider marketplace compliance framework.\n", encoding="utf-8")
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["status"] = "PASS"
        ticket["acceptance"]["files_exist"] = ["src/providers/marketplace.py"]
        self.write_json(".agent/current_ticket.json", ticket)

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        row = {item["artifact"]: item for item in scan["inventory"]}["src/providers/marketplace.py"]

        self.assertNotEqual(row["classification"], "PROTECTED")

    def test_preexisting_files_not_changed_path_is_not_a_violation(self) -> None:
        ui = self.root / "src" / "ui" / "panel.ts"
        ui.parent.mkdir(parents=True)
        ui.write_text("legacy panel\n", encoding="utf-8")
        self.start_video()

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        row = {item["artifact"]: item for item in scan["inventory"]}["src/ui/panel.ts"]

        self.assertNotEqual(row["classification"], "QUARANTINE_CANDIDATE")
        self.assertNotIn("files_not_changed_violation", row["signals"])

    def test_allowed_product_specific_directory_is_not_automatic_core_evidence(self) -> None:
        self.goal_video()
        old = self.root / "src" / "routing" / "old_registry.ts"
        old.parent.mkdir(parents=True)
        old.write_text("legacy route table\n", encoding="utf-8")
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["status"] = "ACTIVE"
        ticket["acceptance_ready"] = True
        ticket["must_do"] = ["Create tests/current-result.txt"]
        ticket["acceptance"]["files_exist"] = ["tests/current-result.txt"]
        ticket["allowed_paths"] = ["src/routing/**", "tests/**"]
        ticket["budget_used"] = {"tool_calls": 0, "changed_files": [], "diff_lines": 0}
        self.write_json(".agent/current_ticket.json", ticket)

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        row = {item["artifact"]: item for item in scan["inventory"]}["src/routing/old_registry.ts"]

        self.assertNotEqual(row["classification"], "KEEP")

    def test_contains_string_exact_file_is_protected(self) -> None:
        self.goal_video()
        doc = self.root / "docs" / "mvp.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("required text\n", encoding="utf-8")
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["status"] = "ACTIVE"
        ticket["acceptance_ready"] = True
        ticket["acceptance"] = {
            "commands_pass": [],
            "files_exist": [],
            "contains": ["docs/mvp.md::required text"],
            "assertions": [],
            "files_not_changed": [".agent/**"],
            "max_changed_files": 5,
            "max_diff_lines": 300,
        }
        ticket["validation_ids"] = []
        ticket["allowed_paths"] = ["docs/**"]
        ticket["budget_used"] = {"tool_calls": 0, "changed_files": [], "diff_lines": 0}
        self.write_json(".agent/current_ticket.json", ticket)

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        row = {item["artifact"]: item for item in scan["inventory"]}["docs/mvp.md"]

        self.assertEqual(row["classification"], "PROTECTED")

    def test_validation_command_text_does_not_protect_observed_path(self) -> None:
        self.goal_video()
        path = self.root / "src" / "providers" / "marketplace.py"
        path.parent.mkdir(parents=True)
        path.write_text("Full RBAC provider marketplace compliance framework.\n", encoding="utf-8")
        catalog = self.read_json(".agent/validation_catalog.json")
        catalog["absence_check"] = {"cmd": "test ! -e src/providers/marketplace.py", "timeout_sec": 5}
        self.write_json(".agent/validation_catalog.json", catalog)
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["status"] = "ACTIVE"
        ticket["acceptance_ready"] = True
        ticket["acceptance"]["commands_pass"] = ["absence_check"]
        ticket["acceptance"]["files_exist"] = []
        ticket["validation_ids"] = ["absence_check"]
        ticket["budget_used"] = {"tool_calls": 0, "changed_files": [], "diff_lines": 0}
        self.write_json(".agent/current_ticket.json", ticket)

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        row = {item["artifact"]: item for item in scan["inventory"]}["src/providers/marketplace.py"]

        self.assertNotEqual(row["classification"], "PROTECTED")

    def test_python_dotted_import_counts_as_one_live_reference(self) -> None:
        target = self.root / "src" / "pkg" / "worker.py"
        target.parent.mkdir(parents=True)
        target.write_text("def run(): return 1\n", encoding="utf-8")
        source = self.root / "src" / "main.py"
        source.write_text("from pkg.worker import run\nrun()\n", encoding="utf-8")
        self.cli("goal-set", "--text", "Build a generic batch processing tool.")

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        row = {item["artifact"]: item for item in scan["inventory"]}["src/pkg/worker.py"]

        self.assertEqual(row["reference_count"], 1)

    def test_ambiguous_same_basename_does_not_create_false_reference(self) -> None:
        for folder in ("a", "b"):
            target = self.root / "src" / folder / "worker.py"
            target.parent.mkdir(parents=True)
            target.write_text("def run(): return 1\n", encoding="utf-8")
        (self.root / "src" / "main.py").write_text("from worker import run\n", encoding="utf-8")
        self.cli("goal-set", "--text", "Build a generic batch processing tool.")

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        rows = {item["artifact"]: item for item in scan["inventory"]}

        self.assertEqual(rows["src/a/worker.py"]["reference_count"], 0)
        self.assertEqual(rows["src/b/worker.py"]["reference_count"], 0)

    def test_one_source_gives_at_most_one_reference_vote(self) -> None:
        target = self.root / "src" / "pkg" / "worker.py"
        target.parent.mkdir(parents=True)
        target.write_text("def run(): return 1\n", encoding="utf-8")
        (self.root / "src" / "main.py").write_text(
            "from pkg.worker import run\n# src/pkg/worker.py worker.py worker\n",
            encoding="utf-8",
        )
        self.cli("goal-set", "--text", "Build a generic batch processing tool.")

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        row = {item["artifact"]: item for item in scan["inventory"]}["src/pkg/worker.py"]

        self.assertEqual(row["reference_count"], 1)

    def test_prune_check_reports_review_required_instead_of_clean(self) -> None:
        self.start_video()
        path = self.root / "src" / "video" / "mock" / "ambiguous_notes.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ambiguous helper notes\n", encoding="utf-8")

        result = self.json_run("prune-check", check=False)

        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertTrue(result["advisories"])

    def test_single_negative_keyword_requires_review(self) -> None:
        self.start_video()
        doc = self.root / "docs" / "platform-notes.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("A platform note with no implementation commitment.\n", encoding="utf-8")

        plan = self.json_run("prune-plan")
        row = {item["target"]: item for item in plan["items"]}["docs/platform-notes.md"]

        self.assertEqual(row["classification"], "REVIEW_REQUIRED")

    def test_negative_words_without_disposability_evidence_require_review(self) -> None:
        self.start_video()
        path = self.root / "src" / "video" / "mock" / "rbac_marketplace.ts"
        path.parent.mkdir(parents=True)
        path.write_text("Full RBAC provider marketplace and compliance framework.\n", encoding="utf-8")

        plan = self.json_run("prune-plan")
        row = {item["target"]: item for item in plan["items"]}["src/video/mock/rbac_marketplace.ts"]

        self.assertIn(row["classification"], {"REVIEW_REQUIRED", "BACKLOG_CANDIDATE"})
        self.assertNotEqual(row["classification"], "QUARANTINE_CANDIDATE")

    def test_negated_future_scope_does_not_demote_packaging_core_file(self) -> None:
        goal = "Build a packaging manufacturing workflow with seal release and lot traceability."
        self.cli("goal-set", "--text", goal)
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket.update({
            "ticket_id": "PACKAGING-SEAL-CORE",
            "global_goal": goal,
            "task_goal": "Implement the bounded packaging seal release result.",
            "must_do": ["src/packaging/seal_release.py"],
            "must_not_do": ["Do not build a full compliance platform"],
            "anti_patterns": ["full compliance platform"],
            "allowed_paths": ["src/packaging/**", "tests/packaging/**"],
            "forbidden_paths": [".agent/**", ".codex/**", ".git/**"],
            "acceptance": {
                "commands_pass": [],
                "files_exist": ["tests/packaging/test_release.py"],
                "contains": [],
                "assertions": [],
                "files_not_changed": [],
                "max_changed_files": 5,
                "max_diff_lines": 300,
            },
            "validation_ids": [],
            "drift_signals": ["Starts building compliance platform"],
            "backlog_only": ["Full compliance platform"],
            "status": "PENDING",
            "acceptance_ready": True,
        })
        self.write_json(".agent/tickets/pending/PACKAGING-SEAL-CORE.json", ticket)
        self.cli("start", ".agent/tickets/pending/PACKAGING-SEAL-CORE.json")
        path = self.root / "src" / "packaging" / "seal_release.py"
        path.parent.mkdir(parents=True)
        path.write_text(
            "def release_seal_lot():\n    return 'released'\n\n# Do not build a full compliance platform here.\n",
            encoding="utf-8",
        )

        plan = self.json_run("prune-plan")
        row = {item["target"]: item for item in plan["items"]}["src/packaging/seal_release.py"]

        self.assertEqual(row["classification"], "KEEP")
        self.assertNotIn("future_scope", row.get("signals", []))

    def test_referenced_negative_named_file_requires_review(self) -> None:
        self.start_video()
        path = self.root / "src" / "video" / "mock" / "rbac_roles.ts"
        path.parent.mkdir(parents=True)
        path.write_text("export const roles = []; // RBAC provider marketplace\n", encoding="utf-8")
        consumer = self.root / "src" / "video" / "mock" / "generator.ts"
        consumer.parent.mkdir(parents=True, exist_ok=True)
        consumer.write_text("import './rbac_roles';\n", encoding="utf-8")

        plan = self.json_run("prune-plan")
        row = {item["target"]: item for item in plan["items"]}["src/video/mock/rbac_roles.ts"]

        self.assertEqual(row["classification"], "REVIEW_REQUIRED")

    def test_suspicious_filename_with_positive_body_and_live_reference_can_keep(self) -> None:
        goal = "Build a hospital bed-capacity planning tool for regional operations teams."
        (self.root / "GOAL.md").write_text(goal + "\n", encoding="utf-8")
        self.cli("goal-set", "--text", goal)
        path = self.root / "src" / "capacity" / "autonomous_diagnosis_compat.py"
        path.parent.mkdir(parents=True)
        path.write_text(goal + "\n", encoding="utf-8")
        consumer = self.root / "src" / "capacity" / "planner.py"
        consumer.write_text("from .autonomous_diagnosis_compat import plan\n", encoding="utf-8")
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket.update({
            "status": "ACTIVE",
            "global_goal": goal,
            "task_goal": "Maintain the current bed-capacity planning path.",
            "must_do": ["Keep the active capacity planner working."],
            "anti_patterns": ["autonomous diagnosis"],
            "allowed_paths": ["src/capacity/**", "tests/**"],
            "acceptance": {"commands_pass": [], "files_exist": ["src/capacity/planner.py"], "contains": [], "assertions": [], "files_not_changed": [".agent/**"], "max_changed_files": 5, "max_diff_lines": 300},
            "validation_ids": [],
            "budget_used": {"tool_calls": 0, "changed_files": [], "diff_lines": 0},
        })
        self.write_json(".agent/current_ticket.json", ticket)

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        row = {item["artifact"]: item for item in scan["inventory"]}["src/capacity/autonomous_diagnosis_compat.py"]

        self.assertEqual(row["classification"], "KEEP")
        self.assertIn("suspicious_name_but_positive_body", row["signals"])

    def test_content_only_north_star_registry_word_is_review_not_simplify(self) -> None:
        goal = "Build an enterprise knowledge registry that preserves citations and freshness evidence."
        self.cli("goal-set", "--text", goal)
        path = self.root / "archive" / "copied-registry-goal.md"
        path.parent.mkdir(parents=True)
        path.write_text(goal + "\n", encoding="utf-8")

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        row = {item["artifact"]: item for item in scan["inventory"]}["archive/copied-registry-goal.md"]

        self.assertEqual(row["classification"], "REVIEW_REQUIRED")

    def test_validation_manifest_preempts_names_and_preserves_path_identity(self) -> None:
        goal = "Build a reproducible scheduling pipeline with exact validation evidence."
        self.cli("goal-set", "--text", goal)
        (self.root / "GOAL.md").write_text(goal + "\n", encoding="utf-8")
        (self.root / "README.md").write_text("Run validation/chain.json before release.\n", encoding="utf-8")
        core = self.root / "src" / "legacy" / "provider_marketplace_guard.py"
        core.parent.mkdir(parents=True)
        core.write_text("# Reject full RBAC and provider marketplace expansion.\n", encoding="utf-8")
        golden = self.root / "validation" / "golden" / "result.json"
        golden.parent.mkdir(parents=True)
        golden.write_text('{"result":"ok"}\n', encoding="utf-8")
        duplicate = self.root / "exports" / "debug" / "result.json"
        duplicate.parent.mkdir(parents=True)
        duplicate.write_text(golden.read_text(encoding="utf-8"), encoding="utf-8")
        manifest = self.root / "validation" / "chain.json"
        manifest.write_text(json.dumps({
            "command": "python tests/smoke.py",
            "required_paths": [
                "GOAL.md",
                "README.md",
                "src/legacy/provider_marketplace_guard.py",
                "validation/golden/result.json",
            ],
            "sha256": {"validation/golden/result.json": "fixture"},
        }) + "\n", encoding="utf-8")

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        rows = {item["artifact"]: item for item in scan["inventory"]}

        self.assertEqual(rows["validation/chain.json"]["classification"], "PROTECTED")
        self.assertEqual(rows["src/legacy/provider_marketplace_guard.py"]["classification"], "KEEP")
        self.assertEqual(rows["validation/golden/result.json"]["classification"], "KEEP")
        self.assertEqual(rows["exports/debug/result.json"]["classification"], "QUARANTINE_CANDIDATE")

    def test_future_and_mixed_scope_documents_are_not_conflated(self) -> None:
        goal = "Build a reproducible scheduling pipeline with exact validation evidence."
        north = {
            "confirmed": True,
            "goal": goal,
            "source": "user_confirmed",
            "confirmed_at": "test",
            "main_path": ["Load jobs, schedule one bounded run, and write validation evidence."],
            "allowed_subgoals": ["bounded scheduling"],
            "anti_goals": ["Do not build a universal tenant administration product."],
            "backlog_domains": ["Distributed tenant billing and organization management."],
            "protected_principles": [],
            "core_path_patterns": ["GOAL.md"],
            "candidate_goals": [],
            "requires_confirmation": False,
        }
        self.write_json(".agent/north_star_goal.json", north)
        future = self.root / "docs" / "organization-notes.md"
        future.parent.mkdir(parents=True)
        future.write_text(
            "Distributed tenant billing and organization management.\n",
            encoding="utf-8",
        )
        mixed = self.root / "docs" / "platform_architecture.md"
        mixed.write_text(
            "Load jobs, schedule one bounded run, and write validation evidence.\n"
            "Distributed tenant billing and organization management.\n",
            encoding="utf-8",
        )

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        rows = {item["artifact"]: item for item in scan["inventory"]}

        self.assertEqual(rows["docs/organization-notes.md"]["classification"], "BACKLOG_CANDIDATE")
        self.assertEqual(rows["docs/platform_architecture.md"]["classification"], "SIMPLIFY_CANDIDATE")

    def test_generic_policy_config_required_by_manifest_is_keep_not_overprotected(self) -> None:
        goal = "Build a bounded payment decision service."
        self.cli("goal-set", "--text", goal)
        (self.root / "GOAL.md").write_text(goal + "\n", encoding="utf-8")
        smoke = self.root / "tests" / "smoke.py"
        smoke.parent.mkdir(parents=True)
        smoke.write_text("print('ok')\n", encoding="utf-8")
        config = self.root / "risk" / "policy" / "config.yaml"
        config.parent.mkdir(parents=True)
        config.write_text("threshold: 10\n", encoding="utf-8")
        manifest = self.root / "assurance" / "validation_chain.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({
            "authority": "GOAL.md",
            "command": "python tests/smoke.py",
            "required_paths": ["GOAL.md", "tests/smoke.py", "risk/policy/config.yaml"],
            "validation_order": ["smoke"],
        }) + "\n", encoding="utf-8")

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        row = {item["artifact"]: item for item in scan["inventory"]}["risk/policy/config.yaml"]

        self.assertEqual(row["classification"], "KEEP")

    def test_untrusted_manifest_cannot_create_protection_edges(self) -> None:
        self.cli("goal-set", "--text", "Build a bounded scheduling workflow.")
        target = self.root / "src" / "orphan.py"
        target.parent.mkdir(parents=True)
        target.write_text("ORPHAN = True\n", encoding="utf-8")
        manifest = self.root / "misc" / "claims.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({
            "authority": "missing-goal.md",
            "command": "python missing-smoke.py",
            "required_paths": ["src/orphan.py"],
            "validation_order": ["smoke"],
        }) + "\n", encoding="utf-8")

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        row = {item["artifact"]: item for item in scan["inventory"]}["src/orphan.py"]

        self.assertNotIn(row["classification"], {"PROTECTED", "KEEP"})

    def test_prune_apply_marks_manifest_without_moving_or_deleting(self) -> None:
        self.start_video()
        path = self.root / "render_cache" / "orphan-frame.bin"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"rebuildable-cache")
        self.json_run("prune-plan")

        result = self.json_run("prune-apply", "--confirm")

        self.assertFalse(result["deleted"])
        self.assertFalse(result["moved"])
        self.assertEqual(result["capability_level"], "MARK_ONLY")
        self.assertTrue(path.exists())
        manifest = (self.root / ".agent" / "quarantine_manifest.jsonl").read_text(encoding="utf-8")
        self.assertIn("render_cache/orphan-frame.bin", manifest)
        self.assertIn("MARKED_ONLY", manifest)

    def test_prune_apply_delete_is_hard_refusal(self) -> None:
        self.start_video()

        result = self.json_run("prune-apply", "--confirm", "--delete", check=False)

        self.assertFalse(result["ok"])
        self.assertIn("no delete permission", result["error"])

    def test_cad_bom_references_keep_required_binary_parts(self) -> None:
        goal = "Build a packaging assembly with a complete, traceable native CAD bill of materials."
        (self.root / "GOAL.md").write_text(goal + "\n", encoding="utf-8")
        self.cli("goal-set", "--text", goal)
        parts = []
        for index in range(58):
            relative = f"cad/parts/package_component_{index:03d}.SLDPRT"
            part = self.root / relative
            part.parent.mkdir(parents=True, exist_ok=True)
            part.write_bytes(b"SLDPRT\x00" + bytes([index]) * 32)
            parts.append(relative)
        manifest = self.root / "cad" / "assembly_manifest.json"
        manifest.write_text(
            json.dumps({"assembly": "packaging_line.SLDASM", "components": parts}, indent=2) + "\n",
            encoding="utf-8",
        )

        scan = self.json_run("onboard-scan", "--verbose", check=False)
        rows = {item["artifact"]: item for item in scan["inventory"]}

        for relative in parts:
            self.assertIn(rows[relative]["classification"], {"KEEP", "PROTECTED"})
            self.assertNotIn(rows[relative]["classification"], {"NOISE_RISK", "QUARANTINE_CANDIDATE"})
            self.assertGreater(rows[relative]["reference_count"], 0)
