from __future__ import annotations

import json

try:
    from .helpers import GoalCompassRepoCase, PLUGIN_ROOT, SCRIPT
except ImportError:
    from helpers import GoalCompassRepoCase, PLUGIN_ROOT, SCRIPT


class AcceptanceTests(GoalCompassRepoCase):
    def test_skill_is_explicit_opt_in_and_preserves_existing_goal(self) -> None:
        skill = (PLUGIN_ROOT / "skills" / "goal-supervisor" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("explicit opt-in", skill)
        self.assertIn("Do not auto-activate", skill)
        self.assertNotIn("may be activated automatically", skill)
        self.assertIn("first_principles", skill)
        self.assertIn("concrete modules and actions", skill.lower())
        self.assertIn("module inputs, dependencies, outputs", skill)
        self.assertIn("deliverables", skill)
        self.assertIn("--require-detailed", skill)
        self.assertIn("2,000-3,500 character executable contract", skill)
        self.assertIn("project-relative Markdown/README plan longer than 4,000 characters", skill)
        self.assertIn("ask the user visibly in conversation", skill)
        self.assertIn("Ask whether the project is commercial only when", skill)
        self.assertIn("must not be blocked merely because commercial status was not collected", skill)
        self.assertIn("do not paste the research log", skill)
        self.assertIn("Only after the required user answer", skill)
        self.assertNotIn("compress the relevant user conversation", skill)
        self.assertIn("If `.agent/north_star_goal.json` already contains a confirmed goal, reuse it", skill)
        self.assertIn("Do not call `goal-set`", skill)
        self.assertIn("privacy_choice_required", skill)
        self.assertIn("ask one concise question in the user's language", skill)
        self.assertIn("Do not ask the user to run a command", skill)
        self.assertIn("This is a one-time project choice", skill)
        self.assertIn("answer the upload part clearly", skill)
        self.assertIn("choose no upload", skill)
        self.assertIn("Record this plugin problem", skill)
        self.assertIn("upload/sync these plugin problems", skill)
        self.assertIn("feedback-config --context <personal|enterprise> --allow-upload --confirm-upload --flush", skill)
        self.assertIn("Stop uploading", skill)
        self.assertIn("Never infer upload permission", skill)

    def test_runtime_core_contains_no_product_fixture_defaults(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8").lower()
        for marker in [
            "video-mock-001",
            "routing-mvp-001",
            "permission-guard-001",
            "build a lan agent registry / skill hub mvp",
            "allowadaptercall",
        ]:
            self.assertNotIn(marker, source)

    def test_compile_outputs_draft(self) -> None:
        (self.root / "rough_task.md").write_text("# Tiny task\nDo a bounded thing.\n", encoding="utf-8")
        result = self.json_run("compile", "rough_task.md", "--out", ".agent/tickets/pending/TEST.json")
        ticket = self.read_json(".agent/tickets/pending/TEST.json")
        self.assertEqual(result["status"], "DRAFT")
        self.assertEqual(ticket["status"], "DRAFT")
        self.assertFalse(ticket["acceptance_ready"])
        self.assertEqual(ticket["execution_relationship"]["mode"], "STANDALONE")
        self.assertEqual(ticket["coordination_contract"], {})

    def test_compile_adapter_draft_uses_integration_budget(self) -> None:
        (self.root / "rough_task.md").write_text(
            "# Provider adapter scaffold\nBuild a new model adapter interface, implementation, config path, and focused tests.\n",
            encoding="utf-8",
        )

        self.json_run("compile", "rough_task.md", "--out", ".agent/tickets/pending/ADAPTER.json")
        ticket = self.read_json(".agent/tickets/pending/ADAPTER.json")

        self.assertEqual(ticket["budget_basis"]["tier"], "INTEGRATION_BOUNDED")
        self.assertGreaterEqual(ticket["budget"]["max_diff_lines"], 800)
        self.assertEqual(ticket["acceptance"]["max_diff_lines"], ticket["budget"]["max_diff_lines"])

    def test_compile_small_single_file_fix_keeps_small_budget(self) -> None:
        (self.root / "rough_task.md").write_text(
            "# Small fix\nFix one assertion in a single file.\n",
            encoding="utf-8",
        )

        self.json_run("compile", "rough_task.md", "--out", ".agent/tickets/pending/SMALL.json")
        ticket = self.read_json(".agent/tickets/pending/SMALL.json")

        self.assertEqual(ticket["budget_basis"]["tier"], "MICRO_BOUNDED")
        self.assertLess(ticket["budget"]["max_diff_lines"], 500)

    def test_compile_does_not_claim_generated_state_as_acceptance_protection(self) -> None:
        (self.root / "rough_task.md").write_text("# Tiny task\nDo one machine-checkable bounded thing.\n", encoding="utf-8")

        self.json_run("compile", "rough_task.md", "--out", ".agent/tickets/pending/NO-GENERATED-ACCEPTANCE.json")
        ticket = self.read_json(".agent/tickets/pending/NO-GENERATED-ACCEPTANCE.json")

        self.assertNotIn(".agent/**", ticket["acceptance"]["files_not_changed"])
        self.assertNotIn(".codex/**", ticket["acceptance"]["files_not_changed"])

    def test_ready_flips_valid_draft_to_pending(self) -> None:
        self.goal_video()
        self.install_validation("ok_validation", "import sys; sys.exit(0)")
        ticket = self.make_validation_ticket("ok_validation")
        ticket["status"] = "DRAFT"
        ticket["acceptance_ready"] = False
        self.write_json(".agent/tickets/pending/READY-OK.json", ticket)

        result = self.json_run("ready", ".agent/tickets/pending/READY-OK.json")
        updated = self.read_json(".agent/tickets/pending/READY-OK.json")

        self.assertTrue(result["ok"])
        self.assertEqual(updated["status"], "PENDING")
        self.assertTrue(updated["acceptance_ready"])
        self.assertEqual(result["acceptance_quality"]["level"], "BEHAVIORAL")

    def test_ready_labels_file_only_acceptance_as_syntactic(self) -> None:
        self.goal_video()
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = "SYNTACTIC-ONLY"
        ticket["status"] = "DRAFT"
        ticket["acceptance_ready"] = False
        ticket["validation_ids"] = []
        ticket["acceptance"]["commands_pass"] = []
        ticket["acceptance"]["files_exist"] = ["src/video/mock/result.ts"]
        self.write_json(".agent/tickets/pending/SYNTACTIC-ONLY.json", ticket)

        result = self.json_run("ready", ".agent/tickets/pending/SYNTACTIC-ONLY.json")

        self.assertEqual(result["acceptance_quality"]["level"], "SYNTACTIC_ONLY")
        self.assertTrue(result["acceptance_quality"]["warning"])

    def test_ready_rejects_raw_commands_pass(self) -> None:
        self.goal_video()
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = "RAW-COMMAND"
        ticket["status"] = "DRAFT"
        ticket["acceptance_ready"] = False
        ticket["validation_ids"] = []
        ticket["acceptance"]["commands_pass"] = ['python -c "import sys; sys.exit(0)"']
        ticket["acceptance"]["files_exist"] = []
        self.write_json(".agent/tickets/pending/RAW-COMMAND.json", ticket)

        result = self.json_run("ready", ".agent/tickets/pending/RAW-COMMAND.json", check=False)

        self.assertFalse(result["ok"])
        self.assertIn("raw shell commands", json.dumps(result))

    def test_start_rejects_raw_commands_pass_before_active(self) -> None:
        self.goal_video()
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = "RAW-START"
        ticket["status"] = "PENDING"
        ticket["acceptance_ready"] = True
        ticket["validation_ids"] = []
        ticket["acceptance"]["commands_pass"] = ['python -c "import sys; sys.exit(0)"']
        ticket["acceptance"]["files_exist"] = []
        self.write_json(".agent/tickets/pending/RAW-START.json", ticket)

        result = self.json_run("start", ".agent/tickets/pending/RAW-START.json", check=False)

        self.assertFalse(result["ok"])
        self.assertIn("raw shell commands", json.dumps(result))

    def test_start_rejects_allowed_path_fully_blocked_by_forbidden_path(self) -> None:
        self.goal_video()
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = "CONTRADICTORY-PATHS"
        ticket["status"] = "PENDING"
        ticket["acceptance_ready"] = True
        ticket["allowed_paths"] = ["scripts/**"]
        ticket["forbidden_paths"] = ["scripts/**", ".agent/**"]
        ticket["acceptance"]["files_exist"] = ["scripts/task.py"]
        self.write_json(".agent/tickets/pending/CONTRADICTORY-PATHS.json", ticket)

        result = self.json_run("start", ".agent/tickets/pending/CONTRADICTORY-PATHS.json", check=False)

        self.assertFalse(result["ok"])
        self.assertIn("allowed path is fully blocked", json.dumps(result))

    def test_start_rejects_forbidden_positive_acceptance_paths(self) -> None:
        self.goal_video()
        cases = [
            ("files_exist", {"files_exist": ["src/providers/marketplace.py"]}),
            ("contains_string", {"contains": ["src/providers/marketplace.py::required"]}),
            ("contains_object", {"contains": [{"file": "src/providers/marketplace.py", "text": "required"}]}),
            ("assert_file_exists", {"assertions": [{"type": "file_exists", "path": "src/providers/marketplace.py"}]}),
            ("assert_file_contains", {"assertions": [{"type": "file_contains", "file": "src/providers/marketplace.py", "text": "required"}]}),
            ("assert_json", {"assertions": [{"type": "json_field_equals", "file": "src/providers/marketplace.py", "path": "x", "equals": 1}]}),
        ]
        for label, update in cases:
            with self.subTest(shape=label):
                ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
                ticket["ticket_id"] = f"FORBIDDEN-{label.upper()}"
                ticket["status"] = "PENDING"
                ticket["acceptance_ready"] = True
                ticket["allowed_paths"] = ["src/**", "tests/**"]
                ticket["forbidden_paths"] = ["src/providers/**", ".agent/**"]
                ticket["validation_ids"] = []
                ticket["acceptance"] = {
                    "commands_pass": [],
                    "files_exist": [],
                    "contains": [],
                    "assertions": [],
                    "files_not_changed": [".agent/**"],
                    "max_changed_files": 5,
                    "max_diff_lines": 300,
                    **update,
                }
                path = f".agent/tickets/pending/{ticket['ticket_id']}.json"
                self.write_json(path, ticket)

                result = self.json_run("start", path, check=False)

                self.assertFalse(result["ok"])
                self.assertIn("acceptance path is forbidden", json.dumps(result))

    def test_ready_rejects_unsupported_acceptance_shapes(self) -> None:
        self.goal_video()
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = "BAD-SHAPE"
        ticket["status"] = "DRAFT"
        ticket["acceptance_ready"] = False
        ticket["acceptance"]["commands_pass"] = []
        ticket["validation_ids"] = []
        ticket["acceptance"]["files_exist"] = []
        ticket["acceptance"]["contains"] = ["docs/out.md"]
        ticket["acceptance"]["assertions"] = [{"type": "json_field_equals", "file": "out.json", "path": "a"}]
        self.write_json(".agent/tickets/pending/BAD-SHAPE.json", ticket)

        result = self.json_run("ready", ".agent/tickets/pending/BAD-SHAPE.json", check=False)

        self.assertFalse(result["ok"])
        self.assertIn("path::required text", json.dumps(result))
        self.assertIn("json_field_equals", json.dumps(result))

    def test_empty_acceptance_cannot_start(self) -> None:
        self.goal_video()
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = "EMPTY-START"
        ticket["status"] = "PENDING"
        ticket["acceptance_ready"] = True
        ticket["acceptance"] = {"commands_pass": [], "files_exist": [], "contains": [], "assertions": []}
        ticket["validation_ids"] = []
        self.write_json(".agent/tickets/pending/EMPTY-START.json", ticket)
        result = self.json_run("start", ".agent/tickets/pending/EMPTY-START.json", check=False)
        self.assertFalse(result["ok"])
        self.assertIn("missing machine-checkable acceptance", json.dumps(result))

    def test_glb_ticket_categories_do_not_trigger_all_categories_antigoal(self) -> None:
        self.cli(
            "goal-set",
            "--text",
            "Build an AI Agent driven automatic GLB product modeling system with route decisions and automatic QA reports.",
        )
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket.update(
            {
                "ticket_id": "QA-CHECK-CATALOG-001",
                "title": "Static QA check ID catalog",
                "global_goal": "Build an AI automatic GLB product modeling system with stable automatic QA report check IDs.",
                "why_now": "Existing QA report scaffolds need stable check IDs before future implementation.",
                "task_goal": "Create a static QA check catalog with stable ids, categories, descriptions, and implemented=false.",
                "status": "READY",
                "acceptance_ready": True,
                "must_do": ["Create src/qa_check_catalog.py with QA_CHECK_CATALOG"],
                "must_not_do": ["Do not execute QA checks"],
                "anti_patterns": ["all product categories at once", "executable QA engine"],
                "allowed_paths": ["src/**", "tests/**"],
                "forbidden_paths": [".env", ".agent/**", ".git/**"],
                "acceptance": {
                    "commands_pass": [],
                    "files_exist": ["src/qa_check_catalog.py"],
                    "contains": [],
                    "assertions": [],
                    "files_not_changed": [".agent/**"],
                    "max_changed_files": 2,
                    "max_diff_lines": 300,
                },
                "validation_ids": [],
                "drift_signals": ["Starts implementing executable QA checks"],
                "backlog_only": ["Executable GLB checks", "All product category modeling"],
            }
        )
        self.write_json(".agent/tickets/pending/QA-CHECK-CATALOG-001.json", ticket)
        result = self.json_run("start", ".agent/tickets/pending/QA-CHECK-CATALOG-001.json", check=False)
        self.assertTrue(result["ok"], result)

    def test_empty_acceptance_cannot_pass(self) -> None:
        self.goal_video()
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["status"] = "ACTIVE"
        ticket["acceptance_ready"] = True
        ticket["acceptance"] = {"commands_pass": [], "files_exist": [], "contains": [], "assertions": []}
        ticket["validation_ids"] = []
        ticket["budget_used"] = {
            "tool_calls": 0,
            "changed_files": [],
            "diff_lines": 0,
            "started_at": "2026-07-03T00:00:00+00:00",
        }
        self.write_json(".agent/current_ticket.json", ticket)
        check = self.json_run("check", check=False)
        self.assertEqual(check["status"], "FAIL")
        self.assertNotEqual(check["status"], "PASS_READY")
        close = self.json_run("close", check=False)
        self.assertEqual(close["status"], "NOT_CERTIFIED")
        self.assertEqual(close["ticket_status"], "ACTIVE")
        self.assertIn("No machine-checkable acceptance. Refusing PASS.", json.dumps(close))

    def test_compile_outputs_lens_notes(self) -> None:
        (self.root / "rough_task.md").write_text(
            "# Mock artifact\nReturn a mock video artifact path and add validation.\n",
            encoding="utf-8",
        )
        self.json_run("compile", "rough_task.md", "--out", ".agent/tickets/pending/LENS.json")
        ticket = self.read_json(".agent/tickets/pending/LENS.json")
        notes = ticket["lens_notes"]
        self.assertTrue(notes["product"]["why_now"] or notes["product"]["non_goal_warning"])
        self.assertTrue(notes["engineering"]["smallest_path"])
        self.assertTrue(notes["qa"]["machine_acceptance_candidates"])
        self.assertTrue(notes["scope"]["drift_signals"])
        self.assertTrue(notes["janitor"]["likely_shit_mountain"])

    def test_lens_notes_do_not_contain_approval_language(self) -> None:
        (self.root / "rough_task.md").write_text(
            "# Mock artifact\nReturn a mock video artifact path.\n",
            encoding="utf-8",
        )
        self.json_run("compile", "rough_task.md", "--out", ".agent/tickets/pending/LENS.json")
        text = json.dumps(self.read_json(".agent/tickets/pending/LENS.json")["lens_notes"], ensure_ascii=False).lower()
        for word in ["approve", "approval", "sign", "decision", "review"]:
            self.assertNotRegex(text, rf"\b{word}\b")

    def test_compile_lens_notes_are_task_specific_or_marked_template(self) -> None:
        (self.root / "rough_task.md").write_text(
            "# Mock video artifact pipeline\nPrompt to mock artifact path.\n",
            encoding="utf-8",
        )
        self.json_run("compile", "rough_task.md", "--out", ".agent/tickets/pending/LENS.json")
        ticket = self.read_json(".agent/tickets/pending/LENS.json")
        notes_text = json.dumps(ticket.get("lens_notes", {}), ensure_ascii=False).lower()
        task_terms = {"mock", "video", "artifact", "prompt"}
        task_specific = sum(1 for term in task_terms if term in notes_text) >= 2
        self.assertTrue(task_specific or ticket.get("lens_notes_status") == "TEMPLATE_ONLY")

    def test_compile_complete_test_does_not_trigger_heavy_scope(self) -> None:
        self.goal_video()
        (self.root / "rough.md").write_text(
            "Complete the missing unit test assertion for parser output. "
            "Do not build a platform or framework.\n",
            encoding="utf-8",
        )
        path = ".agent/tickets/pending/COMPLETE-TEST-001.json"

        self.json_run("compile", "rough.md", "--out", path)
        ticket = self.read_json(path)

        warnings = ticket["lens_notes"]["product"]["non_goal_warning"]
        self.assertNotIn("complete", [str(value).lower() for value in warnings])
        self.assertNotEqual(
            ticket["mdcp"]["layer_1_structured_expression"]["scope_sink_risk"],
            "strong",
        )

    def test_generic_prompt_artifact_task_does_not_trigger_video_template(self) -> None:
        (self.root / "rough_task.md").write_text(
            "# Medical report artifact\nGenerate a machine-checkable report artifact from a clinician prompt.\n",
            encoding="utf-8",
        )

        self.json_run("compile", "rough_task.md", "--out", ".agent/tickets/pending/MEDICAL.json")
        ticket = self.read_json(".agent/tickets/pending/MEDICAL.json")
        encoded = json.dumps({"lens_notes": ticket["lens_notes"], "mdcp": ticket["mdcp"]}, ensure_ascii=False).lower()

        self.assertEqual(ticket["lens_notes_status"], "TASK_SPECIFIC")
        self.assertIn("clinician", encoded)
        self.assertNotIn("mock video", encoded)
        self.assertNotIn("real providers", encoded)

    def test_compile_agent_registry_ticket_is_task_specific_draft(self) -> None:
        (self.root / "rough_task.md").write_text(
            "# LAN Agent Registry / Skill Hub MVP\n"
            "Upload zip Agent packages, validate agent.yaml and README.md, scan secrets, sanitize_mode=force, "
            "store accepted packages in SQLite, search/filter/detail/download, and maintain semver SHA256 hash-chain ledger.\n",
            encoding="utf-8",
        )
        self.json_run("compile", "rough_task.md", "--out", ".agent/tickets/pending/AGENT-REGISTRY-MVP.json")
        ticket = self.read_json(".agent/tickets/pending/AGENT-REGISTRY-MVP.json")
        self.assertEqual(ticket["status"], "DRAFT")
        self.assertFalse(ticket["acceptance_ready"])
        self.assertEqual(ticket["lens_notes_status"], "TASK_SPECIFIC")
        self.assertEqual(ticket["acceptance"]["files_exist"], [])
        self.assertEqual(ticket["validation_ids"], [])
        self.assertNotIn("app/main.py", json.dumps(ticket, ensure_ascii=False))
        self.assertNotIn("Agent Runner", json.dumps(ticket, ensure_ascii=False))
        notes = json.dumps(ticket["lens_notes"], ensure_ascii=False).lower()
        self.assertIn("upload", notes)
        self.assertIn("sanitize", notes)
