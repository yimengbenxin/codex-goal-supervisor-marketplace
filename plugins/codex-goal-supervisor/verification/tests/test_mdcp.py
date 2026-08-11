from __future__ import annotations

import contextlib
import importlib.util
import io
import json

try:
    from .helpers import GOAL_COMPASS, GoalCompassRepoCase, MinimalPluginFixtureCase
except ImportError:
    from helpers import GOAL_COMPASS, GoalCompassRepoCase, MinimalPluginFixtureCase


def run_installer_no_subprocess(installer_path, repo, force=True):
    spec = importlib.util.spec_from_file_location("installer_under_test_mdcp", installer_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load installer: {installer_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with contextlib.redirect_stdout(io.StringIO()):
        return module.install(repo, force)


class MDCPTests(GoalCompassRepoCase):
    @staticmethod
    def confirm_expansion(template: dict) -> dict:
        confirmed = dict(template)
        confirmed.update({
            "status": "CONFIRMED",
            "decision": "EXPAND",
            "reason": "These independent workstreams cannot be covered by the current four departments.",
            "why_current_team_is_insufficient": "The current roster lacks distinct owners for the added deliverables and their evidence.",
            "expected_execution_gain": "Parallel independent outputs remove handoff ambiguity and reduce implementation rework.",
            "coordination_cost_control": "Each department returns one structured deliverable in one wave and exits immediately.",
        })
        return confirmed

    @staticmethod
    def custom_department(index: int) -> dict:
        name = f"department_{index}"
        return {
            "name": name,
            "responsibility": f"Own bounded workstream {index} without widening the ticket.",
            "decision_authority": f"Choose only the local method for workstream {index}.",
            "required_inputs": ["confirmed North Star", "frozen ticket"],
            "deliverables": [f"structured workstream {index} result"],
            "acceptance_criteria": [f"workstream {index} result is machine-checkable"],
            "consumers": ["main_thread_ceo"],
            "forbidden_scope": ["acceptance changes", "unrelated workstreams"],
            "dependencies": ["current ticket"],
            "stop_condition": "Return one structured result, hand it off, then exit.",
            "model_range": {
                "minimum": {"model": "gpt-5.6-terra", "effort": "high"},
                "recommended": {"model": "gpt-5.6-terra", "effort": "max"},
                "maximum": {"model": "gpt-5.6-sol", "effort": "max"},
            },
            "effort_range": {"minimum": "high", "recommended": "max", "maximum": "max"},
            "workspace_access": "read_only",
            "phase": "planning",
            "join_reason": f"Workstream {index} has a distinct deliverable and downstream consumer.",
        }

    def test_init_writes_mdcp_protocol_files_and_scan_ignores_them(self) -> None:
        self.assertTrue((self.root / ".agent" / "protocols" / "mdcp.md").exists())
        self.assertTrue((self.root / ".agent" / "protocols" / "mdcp.schema.json").exists())

        self.goal_video()
        scan = self.json_run("onboard-scan", "--verbose", check=False)
        artifacts = {item["artifact"] for item in scan["inventory"]}

        self.assertFalse(any(path.startswith(".agent/protocols/") for path in artifacts))

    def test_compile_outputs_mdcp_contract(self) -> None:
        (self.root / "rough_task.md").write_text(
            "# Mock video artifact pipeline\nPrompt to mock video artifact path.\n",
            encoding="utf-8",
        )

        self.json_run("compile", "rough_task.md", "--out", ".agent/tickets/pending/MDCP.json")
        ticket = self.read_json(".agent/tickets/pending/MDCP.json")
        mdcp = ticket["mdcp"]

        self.assertEqual(mdcp["protocol"], "MDCP")
        self.assertEqual(mdcp["role"], "cross_layer_rule_library")
        self.assertIn("layer_1_fields", mdcp)
        self.assertIn("scope_anchor", mdcp["layer_1_fields"])
        self.assertIn("pass_criteria", mdcp)
        self.assertTrue(mdcp["layer_3_audit_checks"]["same_axis_loop_check"])

    def test_compile_outputs_three_layer_mdcp_contract(self) -> None:
        (self.root / "rough_task.md").write_text(
            "# Build mock video artifact pipeline\nBuild mock video artifact pipeline from prompt to artifact path.\n",
            encoding="utf-8",
        )

        self.json_run("compile", "rough_task.md", "--out", ".agent/tickets/pending/THREE-LAYER.json")
        ticket = self.read_json(".agent/tickets/pending/THREE-LAYER.json")
        mdcp = ticket["mdcp"]

        self.assertIn("layer_1_structured_expression", mdcp)
        self.assertIn("layer_2_company_roles", mdcp)
        self.assertIn("layer_1_pass_criteria", mdcp)
        self.assertIn("layer_2_pass_criteria", mdcp)
        roles = mdcp["layer_2_company_roles"]
        self.assertIn("mock video artifact pipeline", roles["product"]["why_now"].lower())
        self.assertIn("mock video artifact pipeline", roles["engineering"]["smallest_path"].lower())
        self.assertRegex(json.dumps(roles["qa"]["machine_acceptance_candidates"], ensure_ascii=False), r"artifact path|validation|outcome")
        self.assertTrue(roles["scope_cost"]["scope_sink_risks"])
        self.assertTrue(roles["janitor"]["likely_shit_mountain"])
        self.assertFalse(self.has_gate_language(mdcp))

    def test_compile_skips_company_for_one_narrow_assertion(self) -> None:
        (self.root / "rough_task.md").write_text(
            "# Add one parser assertion\nAdd one machine-checkable parser assertion in the existing module.\n",
            encoding="utf-8",
        )

        self.json_run("compile", "rough_task.md", "--out", ".agent/tickets/pending/COMPANY.json")
        policy = self.read_json(".agent/tickets/pending/COMPANY.json")["mdcp"]["layer_2_company_subagents"]

        self.assertFalse(policy["mandatory"])
        self.assertEqual(policy["min_subagents"], 0)
        self.assertFalse(policy["subagent_spawn_required_before_product_edits"])
        self.assertEqual(policy["runtime_binding"], "not_required")
        self.assertTrue(policy["runtime_execution_verified"])
        self.assertFalse(policy["nested_company_mode"])
        self.assertEqual(policy["max_subagents"], 0)
        self.assertLessEqual(policy["max_subagents"], 4)
        self.assertEqual(policy["department_selection_source"], "task_driven_auto")
        self.assertEqual(policy["department_capacity"], "unbounded_by_protocol")
        self.assertEqual(policy["ceo_confirmation"]["status"], "NOT_REQUIRED")
        self.assertEqual(policy["required_subagents"], [])
        supervision = self.read_json(".agent/tickets/pending/COMPANY.json")["supervision"]
        self.assertEqual(supervision["level"], "NONE")
        self.assertFalse(supervision["ticket_required"])
        self.assertEqual(supervision["controls"], [])
        self.assertEqual(supervision["net_benefit"]["decision"], "SKIP")

    def test_standard_janitor_runs_only_when_cleanup_or_breadth_justifies_it(self) -> None:
        (self.root / "rough_task.md").write_text(
            "# Adapter integration\nImplement one bounded adapter integration in the existing routing workflow.\n",
            encoding="utf-8",
        )
        normal_path = ".agent/tickets/pending/STANDARD-NORMAL.json"
        self.json_run("compile", "rough_task.md", "--out", normal_path)
        normal = self.read_json(normal_path)["supervision"]

        self.assertEqual(normal["level"], "STANDARD")
        self.assertEqual(normal["janitor_mode"], "not_required")
        self.assertNotIn("current_ticket_janitor", normal["controls"])

        (self.root / "rough_task.md").write_text(
            "# Adapter cleanup\nClean up dead code in one bounded adapter integration without widening the routing workflow.\n",
            encoding="utf-8",
        )
        cleanup_path = ".agent/tickets/pending/STANDARD-CLEANUP.json"
        self.json_run("compile", "rough_task.md", "--out", cleanup_path)
        cleanup = self.read_json(cleanup_path)["supervision"]

        self.assertEqual(cleanup["level"], "STANDARD")
        self.assertEqual(cleanup["janitor_mode"], "on_artifact_sprawl")
        self.assertIn("janitor_on_sprawl", cleanup["controls"])

    def test_small_execution_ticket_avoids_receipt_ceremony(self) -> None:
        self.goal_video()
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = "SMALL-COMPANY"
        ticket["title"] = "Add exact mock assertion"
        ticket["task_goal"] = "Add one exact assertion to the existing mock test."
        ticket["must_do"] = ["Add one exact assertion"]
        ticket["allowed_paths"] = ["tests/video/mock-video-pipeline.test.ts"]
        ticket["budget"] = {"max_minutes": 15, "max_tool_calls": 20, "max_changed_files": 2, "max_diff_lines": 100}
        self.write_json(".agent/tickets/pending/SMALL-COMPANY.json", ticket)

        result = self.json_run("start", ".agent/tickets/pending/SMALL-COMPANY.json")
        policy = self.read_json(".agent/current_ticket.json")["mdcp"]["layer_2_company_subagents"]

        self.assertFalse(result["company_subagents"]["required"])
        self.assertEqual(policy["complexity_tier"], "T0_EXECUTION")
        self.assertEqual(policy["min_subagents"], 0)
        self.assertEqual(policy["activated_departments"], [])
        self.assertEqual(policy["delegation_decision"]["signal"], "MAIN_THREAD_ONLY_BOUNDED_ACTION")
        self.assertEqual(self.read_json(".agent/current_ticket.json")["supervision"]["janitor_mode"], "not_required")
        prune = self.json_run("prune-check")
        self.assertEqual(prune["status"], "NOT_REQUIRED")
        self.assertEqual(prune["files_scanned"], 0)

    def test_one_mechanical_workstream_does_not_force_a_department(self) -> None:
        (self.root / "rough_task.md").write_text(
            "# Rename one parser variable\nRename one local parser variable inside the existing implementation.\n",
            encoding="utf-8",
        )

        self.json_run("compile", "rough_task.md", "--out", ".agent/tickets/pending/ONE.json")
        policy = self.read_json(".agent/tickets/pending/ONE.json")["mdcp"]["layer_2_company_subagents"]

        self.assertEqual(policy["activated_departments"], [])
        self.assertEqual(policy["automatic_department_limit"], 4)

    def test_zero_departments_are_valid_for_read_only_main_thread_task(self) -> None:
        (self.root / "rough_task.md").write_text(
            "# Status only\nReport current status only. No product edits and no implementation.\n",
            encoding="utf-8",
        )

        self.json_run("compile", "rough_task.md", "--out", ".agent/tickets/pending/ZERO.json")
        policy = self.read_json(".agent/tickets/pending/ZERO.json")["mdcp"]["layer_2_company_subagents"]

        self.assertFalse(policy["mandatory"])
        self.assertEqual(policy["plan_status"], "NO_SUBAGENT_NEEDED")
        self.assertEqual(policy["activated_departments"], [])
        self.assertEqual(policy["min_subagents"], 0)
        self.assertEqual(policy["runtime_binding"], "not_required")
        self.assertFalse(policy["subagent_spawn_required_before_product_edits"])
        self.assertEqual(policy["expansion_policy"]["automatic_range"], "0-4 task-driven departments")
        self.assertEqual(self.read_json(".agent/tickets/pending/ZERO.json")["supervision"]["level"], "NONE")

    def test_high_consequence_ticket_selects_deep_supervision(self) -> None:
        self.goal_video()
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket.update({
            "ticket_id": "DEEP-SUPERVISION",
            "title": "Migrate a production permission boundary",
            "task_goal": "Perform a production migration across a public API permission boundary.",
            "must_do": ["Migrate the bounded permission contract and validate rollback behavior."],
            "budget": {"max_minutes": 120, "max_tool_calls": 120, "max_changed_files": 15, "max_diff_lines": 1800},
            "quality_gates": [{"id": "migration_product_check", "dimension": "product", "evidence_types": ["browser"]}],
        })
        path = ".agent/tickets/pending/DEEP-SUPERVISION.json"
        self.write_json(path, ticket)

        ready = self.json_run("ready", path, check=False)

        self.assertEqual(ready["supervision"]["level"], "DEEP")
        self.assertIn("company_roles_on_decision", ready["supervision"]["controls"])
        self.assertEqual(ready["supervision"]["janitor_mode"], "on_artifact_sprawl")

    def test_zero_department_micro_ticket_can_start(self) -> None:
        self.goal_video()
        (self.root / "src").mkdir(exist_ok=True)
        (self.root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket.update({
            "ticket_id": "MICRO-DIRECT",
            "title": "Update one literal",
            "task_goal": "Update one literal in the existing file.",
            "must_do": ["Update one literal"],
            "allowed_paths": ["src/app.py"],
            "validation_ids": [],
            "budget": {"max_minutes": 8, "max_tool_calls": 10, "max_changed_files": 1, "max_diff_lines": 20},
        })
        ticket["acceptance"] = {
            "commands_pass": [],
            "files_exist": ["src/app.py"],
            "contains": [],
            "assertions": [],
            "files_not_changed": [],
            "max_changed_files": 1,
            "max_diff_lines": 20,
        }
        path = ".agent/tickets/pending/MICRO-DIRECT.json"
        self.write_json(path, ticket)

        result = self.json_run("start", path)

        self.assertFalse(result["company_subagents"]["required"])
        self.assertEqual(result["company_subagents"]["plan_status"], "NO_SUBAGENT_NEEDED")
        self.assertEqual(result["company_subagents"]["department_count"], 0)
        self.assertEqual(result["company_subagents"]["runtime_binding"], "not_required")

    def test_explicit_department_roster_overrides_zero_department_auto_choice(self) -> None:
        (self.root / "rough_task.md").write_text(
            "# Status only\nReport current status only. No product edits.\n",
            encoding="utf-8",
        )
        path = ".agent/tickets/pending/ZERO-OVERRIDE.json"
        self.json_run("compile", "rough_task.md", "--out", path)
        ticket = self.read_json(path)
        ticket["requested_company_departments"] = ["auditor"]
        self.write_json(path, ticket)

        policy = self.json_run("ready", path, check=False)["company_subagents"]

        self.assertFalse(policy["required"])
        self.assertTrue(policy["recommended"])
        self.assertEqual(policy["required_roles"], ["auditor"])
        self.assertEqual(policy["runtime_binding"], "optional_external_runtime")

    def test_commercial_ticket_selects_business_not_fixed_default_roster(self) -> None:
        (self.root / "rough_task.md").write_text(
            "# Commercial opportunity\nEvaluate one pricing and revenue opportunity for market entry.\n",
            encoding="utf-8",
        )

        self.json_run("compile", "rough_task.md", "--out", ".agent/tickets/pending/COMMERCIAL.json")
        policy = self.read_json(".agent/tickets/pending/COMMERCIAL.json")["mdcp"]["layer_2_company_subagents"]

        self.assertEqual(policy["activated_departments"], ["strategy", "business", "product", "finance"])

    def test_algorithm_ticket_selects_algorithm_company(self) -> None:
        (self.root / "rough_task.md").write_text(
            "# Ranking algorithm\nBuild and test one bounded ranking algorithm with a measurable metric.\n",
            encoding="utf-8",
        )

        self.json_run("compile", "rough_task.md", "--out", ".agent/tickets/pending/ALGORITHM.json")
        policy = self.read_json(".agent/tickets/pending/ALGORITHM.json")["mdcp"]["layer_2_company_subagents"]

        self.assertEqual(policy["activated_departments"], ["product", "algorithm", "engineering", "qa"])

    def test_strategic_ticket_routes_strategy_to_sol_max(self) -> None:
        (self.root / "rough_task.md").write_text(
            "# Cross-system architecture tradeoff\nChoose the smaller architecture path for a cross-system adapter boundary.\n",
            encoding="utf-8",
        )

        self.json_run("compile", "rough_task.md", "--out", ".agent/tickets/pending/STRATEGY.json")
        policy = self.read_json(".agent/tickets/pending/STRATEGY.json")["mdcp"]["layer_2_company_subagents"]
        strategy = next(row for row in policy["required_subagents"] if row["role"] == "strategy")

        self.assertEqual(policy["complexity_tier"], "T2_STRATEGIC")
        self.assertEqual(strategy["preferred_model"], "gpt-5.6-sol")
        self.assertEqual(strategy["reasoning_effort"], "max")
        self.assertEqual(strategy["ui_effort_label"], "Max")

    def test_company_routes_use_only_approved_high_or_max_profiles(self) -> None:
        (self.root / "rough_task.md").write_text(
            "# Cross-functional release\nBuild and validate a product API workflow with a strategic architecture tradeoff.\n",
            encoding="utf-8",
        )
        self.json_run("compile", "rough_task.md", "--out", ".agent/tickets/pending/MODELS.json")
        policy = self.read_json(".agent/tickets/pending/MODELS.json")["mdcp"]["layer_2_company_subagents"]
        allowed = {
            ("gpt-5.6-sol", "max"),
            ("gpt-5.6-terra", "high"),
            ("gpt-5.6-terra", "max"),
            ("gpt-5.6-luna", "high"),
            ("gpt-5.6-luna", "max"),
        }

        self.assertTrue(policy["required_subagents"])
        for role in policy["required_subagents"]:
            self.assertIn((role["preferred_model"], role["reasoning_effort"]), allowed)
            for endpoint in role["model_range"].values():
                self.assertIn((endpoint["model"], endpoint["effort"]), allowed)

    def test_company_rejects_medium_effort_department_override(self) -> None:
        (self.root / "rough_task.md").write_text(
            "# Architecture boundary\nChoose and implement one bounded architecture boundary.\n",
            encoding="utf-8",
        )
        path = ".agent/tickets/pending/NO-MEDIUM.json"
        self.json_run("compile", "rough_task.md", "--out", path)
        ticket = self.read_json(path)
        ticket["requested_company_departments"] = [{
            "name": "engineering",
            "preferred_model": "gpt-5.6-luna",
            "reasoning_effort": "medium",
        }]
        self.write_json(path, ticket)

        result = self.json_run("ready", path, check=False)

        self.assertFalse(result["ok"])
        self.assertIn("unsupported reasoning_effort: medium", " ".join(result["errors"]))

    def test_confirmed_batch_annotation_has_unbounded_luna_high_workforce(self) -> None:
        self.goal_video()
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket.update({
            "ticket_id": "BATCH-ANNOTATION-400",
            "title": "Annotate 400 independent training samples",
            "task_goal": "Batch annotate 400 independent samples for LLR training.",
            "allowed_paths": ["labels/**", "tests/video/mock-video-pipeline.test.ts"],
            "writable_paths": ["labels/**", "tests/video/mock-video-pipeline.test.ts"],
        })
        batch = {
            "enabled": True,
            "kind": "independent_annotation",
            "item_count": 400,
            "requested_workers": 400,
            "expected_output_files": 400,
            "output_paths": ["labels/**"],
            "validation_ids": ["mock_video_pipeline_test"],
            "independence_evidence": "Each sample has one isolated label file and no worker writes another sample output.",
            "merge_strategy": "Sort labels by sample id, reject duplicate ids, then run the catalog validation once.",
            "ceo_confirmation": {},
        }
        fingerprint = GOAL_COMPASS.batch_execution_fingerprint(batch)
        batch["ceo_confirmation"] = {
            "status": "CONFIRMED",
            "decision": "EXPAND_BATCH_WORKFORCE",
            "confirmed_by": "main_thread_ceo",
            "worker_count": 400,
            "reason": "The 400 items are independent and parallel execution saves material elapsed time without merge ambiguity.",
            "contract_fingerprint": fingerprint,
        }
        ticket["batch_execution"] = batch
        path = ".agent/tickets/pending/BATCH-ANNOTATION-400.json"
        self.write_json(path, ticket)

        ready = self.json_run("ready", path)
        stored = self.read_json(path)
        workforce = stored["mdcp"]["layer_2_company_subagents"]["batch_workforce"]
        dispatch = stored["mdcp"]["layer_2_company_subagents"]["dispatch"]

        self.assertTrue(ready["ok"])
        self.assertEqual(workforce["status"], "CONFIRMED")
        self.assertTrue(workforce["no_protocol_worker_cap"])
        self.assertEqual(workforce["worker_count"], 400)
        self.assertEqual(workforce["worker_profile"], {"model": "gpt-5.6-luna", "effort": "high"})
        self.assertEqual(workforce["worker_fallback_profile"], {"model": "gpt-5.6-terra", "effort": "high"})
        self.assertFalse(workforce["per_worker_company_receipt_required"])
        self.assertEqual(dispatch["batch_max_parallel_per_wave"], 400)
        self.assertGreaterEqual(stored["budget"]["max_changed_files"], 420)
        self.assertGreaterEqual(stored["acceptance"]["max_changed_files"], 420)

    def test_batch_annotation_requires_exact_ceo_confirmation(self) -> None:
        self.goal_video()
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = "BATCH-UNCONFIRMED"
        ticket["allowed_paths"] = ["labels/**", "tests/video/mock-video-pipeline.test.ts"]
        ticket["writable_paths"] = list(ticket["allowed_paths"])
        ticket["batch_execution"] = {
            "enabled": True,
            "kind": "independent_annotation",
            "item_count": 300,
            "requested_workers": 300,
            "expected_output_files": 300,
            "output_paths": ["labels/**"],
            "validation_ids": ["mock_video_pipeline_test"],
            "independence_evidence": "Each label shard has exactly one owner and an isolated output file.",
            "merge_strategy": "Merge by stable sample id and reject duplicate outputs before validation.",
            "ceo_confirmation": {},
        }
        path = ".agent/tickets/pending/BATCH-UNCONFIRMED.json"
        self.write_json(path, ticket)

        result = self.json_run("ready", path, check=False)

        self.assertFalse(result["ok"])
        self.assertIn("batch workforce requires main_thread_ceo confirmation", " ".join(result["errors"]))

    def test_ultra_is_root_ceo_only_after_high_consequence_and_insufficiency(self) -> None:
        self.goal_video()
        (self.root / "rough_task.md").write_text(
            "# Strategic irreversible data migration\nChoose the strategic architecture tradeoff for an irreversible data migration.\n",
            encoding="utf-8",
        )
        path = ".agent/tickets/pending/ULTRA.json"
        self.json_run("compile", "rough_task.md", "--out", path)
        ticket = self.read_json(path)
        initial = ticket["mdcp"]["layer_2_company_subagents"]
        initial_strategy = next(row for row in initial["required_subagents"] if row["role"] == "strategy")
        self.assertEqual(initial_strategy["reasoning_effort"], "max")
        self.assertFalse(initial["model_routing"]["ultra"]["eligible"])

        ticket["company_escalation_evidence"] = ["max insufficient after two prior failures"]
        ticket["acceptance"]["files_exist"] = ["src/migration.py"]
        ticket["allowed_paths"] = ["src/migration.py"]
        ticket["forbidden_paths"] = [".agent/**", ".codex/**", ".git/**"]
        ticket["drift_signals"] = ["Expands beyond the frozen migration boundary"]
        self.write_json(path, ticket)

        self.json_run("ready", path)
        updated = self.read_json(path)["mdcp"]["layer_2_company_subagents"]
        strategy = next(row for row in updated["required_subagents"] if row["role"] == "strategy")

        self.assertEqual(updated["complexity_tier"], "T3_CRITICAL")
        self.assertEqual(strategy["preferred_model"], "gpt-5.6-sol")
        self.assertEqual(strategy["reasoning_effort"], "max")
        self.assertTrue(updated["model_routing"]["ultra"]["eligible"])
        self.assertTrue(updated["model_routing"]["ultra"]["root_ceo_only"])
        self.assertTrue(all(row["reasoning_effort"] != "ultra" for row in updated["required_subagents"]))
        self.assertLessEqual(updated["max_subagents"], 4)
        self.assertEqual(updated["ceo_confirmation"]["status"], "NOT_REQUIRED")

    def test_domain_high_consequence_signal_can_make_root_ultra_eligible(self) -> None:
        self.cli(
            "goal-set",
            "--text",
            "Build an aviation maintenance planning system with auditable airworthiness work packages.",
        )
        (self.root / "rough_task.md").write_text(
            "# Airworthiness release authorization\nDefine one bounded airworthiness release authorization path.\n",
            encoding="utf-8",
        )
        path = ".agent/tickets/pending/AIRWORTHINESS.json"
        self.json_run("compile", "rough_task.md", "--out", path)
        ticket = self.read_json(path)
        initial = ticket["mdcp"]["layer_2_company_subagents"]
        self.assertIn("high_consequence:airworthiness release", initial["complexity"]["signals"])
        self.assertFalse(initial["model_routing"]["ultra"]["eligible"])

        ticket["company_escalation_evidence"] = ["max insufficient after two prior failures"]
        ticket["acceptance"]["files_exist"] = ["src/aviation/release.py"]
        ticket["allowed_paths"] = ["src/aviation/release.py"]
        ticket["forbidden_paths"] = [".agent/**", ".codex/**", ".git/**"]
        ticket["drift_signals"] = ["Expands beyond the release authorization boundary"]
        self.write_json(path, ticket)

        self.json_run("ready", path)
        updated = self.read_json(path)["mdcp"]["layer_2_company_subagents"]

        self.assertEqual(updated["complexity_tier"], "T3_CRITICAL")
        self.assertTrue(updated["model_routing"]["ultra"]["eligible"])
        self.assertTrue(all(row["reasoning_effort"] != "ultra" for row in updated["required_subagents"]))

    def test_packaging_high_consequence_can_make_root_ultra_eligible(self) -> None:
        self.cli(
            "goal-set",
            "--text",
            "Build a food and medical packaging manufacturing system with auditable lot release.",
        )
        (self.root / "rough_task.md").write_text(
            "# Sterile barrier release\nDefine one bounded sterile barrier seal integrity release.\n",
            encoding="utf-8",
        )
        path = ".agent/tickets/pending/PACKAGING-CRITICAL.json"
        self.json_run("compile", "rough_task.md", "--out", path)
        ticket = self.read_json(path)
        initial = ticket["mdcp"]["layer_2_company_subagents"]
        self.assertIn("high_consequence:sterile barrier", initial["complexity"]["signals"])
        self.assertFalse(initial["model_routing"]["ultra"]["eligible"])

        ticket["company_escalation_evidence"] = ["max insufficient after two prior failures"]
        ticket["acceptance"]["files_exist"] = ["src/packaging/sterile_barrier_release.py"]
        ticket["allowed_paths"] = ["src/packaging/sterile_barrier_release.py"]
        ticket["forbidden_paths"] = [".agent/**", ".codex/**", ".git/**"]
        ticket["drift_signals"] = ["Expands beyond the sterile barrier release boundary"]
        self.write_json(path, ticket)

        self.json_run("ready", path)
        policy = self.read_json(path)["mdcp"]["layer_2_company_subagents"]

        self.assertEqual(policy["complexity_tier"], "T3_CRITICAL")
        self.assertTrue(policy["model_routing"]["ultra"]["eligible"])
        self.assertTrue(all(row["reasoning_effort"] != "ultra" for row in policy["required_subagents"]))

    def test_packaging_native_hazard_phrases_are_high_consequence(self) -> None:
        self.cli("goal-set", "--text", "Build a packaging manufacturing system with accountable lot release.")
        phrases = [
            "burst pressure below specification can rupture a filled aerosol can",
            "glass delamination flakes can enter an injectable medicine",
            "glass thermal shock and closure integrity can fail during hot fill",
            "azo-dye residue can transfer to food-contact surfaces",
            "allergen cross-contact can harm consumers",
            "laminate pinholes can admit pathogens into aseptically packed nutrition",
            "tamper-evident bridge failure can leave product interference undetected",
            "internal coating pinholes can corrode the can and cause sudden leakage",
            "sterilization-dose nonuniformity can leave viable organisms in sealed pouches",
        ]
        for index, phrase in enumerate(phrases):
            with self.subTest(phrase=phrase):
                (self.root / "rough_task.md").write_text(
                    f"# Packaging hazard control\nAdd one control because {phrase}.\n",
                    encoding="utf-8",
                )
                path = f".agent/tickets/pending/PACKAGING-HAZARD-{index}.json"
                self.json_run("compile", "rough_task.md", "--out", path)
                policy = self.read_json(path)["mdcp"]["layer_2_company_subagents"]

                self.assertEqual(policy["complexity_tier"], "T2_STRATEGIC")
                self.assertTrue(any(signal.startswith("high_consequence:") for signal in policy["complexity"]["signals"]))

    def test_north_star_consequence_does_not_promote_unrelated_child_ticket(self) -> None:
        self.cli(
            "goal-set",
            "--text",
            "Build child-resistant closure packaging with accountable safety release.",
        )
        (self.root / "rough_task.md").write_text(
            "# Color calibration sample\nAdd one bounded color calibration sample assertion.\n",
            encoding="utf-8",
        )
        path = ".agent/tickets/pending/COLOR-CALIBRATION.json"
        self.json_run("compile", "rough_task.md", "--out", path)
        policy = self.read_json(path)["mdcp"]["layer_2_company_subagents"]

        self.assertNotIn(policy["complexity_tier"], {"T2_STRATEGIC", "T3_CRITICAL"})
        self.assertFalse(any(signal.startswith("high_consequence:") for signal in policy["complexity"]["signals"]))

    def test_only_more_than_four_subagents_require_ceo_confirmation(self) -> None:
        self.goal_video()
        (self.root / "rough_task.md").write_text(
            "# Architecture tradeoff\nChoose a cross-system architecture boundary.\n",
            encoding="utf-8",
        )
        path = ".agent/tickets/pending/CEO-GATE.json"
        self.json_run("compile", "rough_task.md", "--out", path)
        ticket = self.read_json(path)
        ticket["acceptance"]["files_exist"] = ["src/boundary.py"]
        ticket["allowed_paths"] = ["src/boundary.py"]
        ticket["requested_company_departments"] = ["strategy", "product", "engineering", "qa"]
        self.write_json(path, ticket)

        four = self.json_run("ready", path)
        self.assertTrue(four["ok"])

        ticket = self.read_json(path)
        ticket["status"] = "DRAFT"
        ticket["acceptance_ready"] = False
        ticket["requested_company_departments"].append("auditor")
        self.write_json(path, ticket)
        result = self.json_run("ready", path, check=False)

        self.assertFalse(result["ok"])
        company = result["company_subagents"]
        self.assertEqual(company["min_subagents"], 5)
        self.assertEqual(company["ceo_confirmation"]["status"], "KEEP_CURRENT")
        self.assertEqual(company["ceo_confirmation"]["decision"], "KEEP_CURRENT")
        self.assertTrue(any("CEO expansion confirmation required" in error for error in result["errors"]))

    def test_ceo_can_confirm_ten_department_company(self) -> None:
        self.goal_video()
        (self.root / "rough_task.md").write_text(
            "# Cross-system architecture\nChoose and implement a cross-system architecture boundary.\n",
            encoding="utf-8",
        )
        path = ".agent/tickets/pending/TEN-DEPARTMENTS.json"
        self.json_run("compile", "rough_task.md", "--out", path)
        ticket = self.read_json(path)
        ticket["acceptance"]["files_exist"] = ["src/boundary.py"]
        ticket["allowed_paths"] = ["src/boundary.py"]
        ticket["requested_company_departments"] = [
            "strategy", "business", "product", "engineering", "architecture",
            "qa", "scope_cost", "custodian", "janitor", "auditor",
        ]
        self.write_json(path, ticket)

        blocked = self.json_run("ready", path, check=False)
        template = blocked["company_subagents"]["ceo_confirmation"]["confirmation_template"]
        ticket = self.read_json(path)
        ticket["company_ceo_confirmation"] = self.confirm_expansion(template)
        self.write_json(path, ticket)
        result = self.json_run("ready", path)
        policy = self.read_json(path)["mdcp"]["layer_2_company_subagents"]

        self.assertTrue(result["ok"])
        self.assertEqual(policy["max_subagents"], 10)
        self.assertEqual(len(policy["required_subagents"]), 10)
        self.assertEqual(policy["department_capacity"], "unbounded_by_protocol")
        self.assertEqual(policy["ceo_confirmation"]["status"], "CONFIRMED")

    def test_ceo_can_confirm_large_structured_department_company_without_protocol_cap(self) -> None:
        self.goal_video()
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = "LARGE-DEPARTMENTS"
        ticket["requested_company_departments"] = [self.custom_department(index) for index in range(24)]
        path = ".agent/tickets/pending/LARGE-DEPARTMENTS.json"
        self.write_json(path, ticket)

        blocked = self.json_run("ready", path, check=False)
        template = blocked["company_subagents"]["ceo_confirmation"]["confirmation_template"]
        ticket = self.read_json(path)
        ticket["company_ceo_confirmation"] = self.confirm_expansion(template)
        self.write_json(path, ticket)
        result = self.json_run("ready", path)
        policy = self.read_json(path)["mdcp"]["layer_2_company_subagents"]

        self.assertTrue(result["ok"])
        self.assertEqual(len(policy["required_subagents"]), 24)
        self.assertEqual(policy["dispatch"]["total_subagents"], 24)
        self.assertEqual(policy["dispatch"]["wave_count"], 6)
        self.assertEqual(policy["department_capacity"], "unbounded_by_protocol")
        self.assertTrue(policy["expansion_policy"]["no_protocol_department_cap"])

    def test_custom_department_without_complete_contract_cannot_join(self) -> None:
        self.goal_video()
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = "INCOMPLETE-DEPARTMENT"
        ticket["requested_company_departments"] = ["engineering", {"name": "field_liaison"}]
        path = ".agent/tickets/pending/INCOMPLETE-DEPARTMENT.json"
        self.write_json(path, ticket)

        result = self.json_run("ready", path, check=False)

        self.assertFalse(result["ok"])
        self.assertTrue(any("structured department contract" in error or "missing contract fields" in error for error in result["errors"]))

    def test_ceo_confirmation_is_bound_to_exact_roster(self) -> None:
        self.goal_video()
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = "ROSTER-FINGERPRINT"
        ticket["requested_company_departments"] = ["strategy", "product", "engineering", "qa", "business"]
        path = ".agent/tickets/pending/ROSTER-FINGERPRINT.json"
        self.write_json(path, ticket)

        blocked = self.json_run("ready", path, check=False)
        ticket = self.read_json(path)
        ticket["company_ceo_confirmation"] = self.confirm_expansion(blocked["company_subagents"]["ceo_confirmation"]["confirmation_template"])
        ticket["requested_company_departments"].append("auditor")
        self.write_json(path, ticket)

        changed = self.json_run("ready", path, check=False)

        self.assertFalse(changed["ok"])
        self.assertEqual(changed["company_subagents"]["ceo_confirmation"]["status"], "PENDING")

    def test_ceo_confirmation_is_bound_to_department_access_and_objective(self) -> None:
        self.goal_video()
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = "ROSTER-CAPABILITIES"
        ticket["requested_company_departments"] = [
            "strategy",
            "product",
            "engineering",
            "qa",
            {
                "name": "operations",
                "responsibility": "Inspect one bounded operational handoff.",
                "workspace_access": "read_only",
            },
        ]
        path = ".agent/tickets/pending/ROSTER-CAPABILITIES.json"
        self.write_json(path, ticket)

        blocked = self.json_run("ready", path, check=False)
        ticket = self.read_json(path)
        ticket["company_ceo_confirmation"] = self.confirm_expansion(blocked["company_subagents"]["ceo_confirmation"]["confirmation_template"])
        ticket["requested_company_departments"][-1]["responsibility"] = "Implement the bounded operational handoff."
        ticket["requested_company_departments"][-1]["workspace_access"] = "allowed_paths_writer"
        self.write_json(path, ticket)

        changed = self.json_run("ready", path, check=False)

        self.assertFalse(changed["ok"])
        self.assertEqual(changed["company_subagents"]["ceo_confirmation"]["status"], "PENDING")

    def test_ready_adds_mdcp_contract_to_legacy_ticket(self) -> None:
        self.goal_video()
        self.install_validation("ok_validation", "import sys; sys.exit(0)")
        ticket = self.make_validation_ticket("ok_validation")
        ticket["status"] = "DRAFT"
        ticket["acceptance_ready"] = False
        ticket.pop("mdcp", None)
        self.write_json(".agent/tickets/pending/LEGACY-MDCP.json", ticket)

        result = self.json_run("ready", ".agent/tickets/pending/LEGACY-MDCP.json", "--verbose")
        updated = self.read_json(".agent/tickets/pending/LEGACY-MDCP.json")

        self.assertTrue(result["ok"])
        self.assertIn("mdcp", updated)
        self.assertEqual(updated["mdcp"]["protocol"], "MDCP")
        self.assertIn("mdcp_audit", result)

    def test_request_outputs_mdcp_signal_without_changing_verdict(self) -> None:
        self.start_video()

        result = self.json_run("request", "--text", "只补一个 returned mock artifact path 验收断言，其他不要改")

        self.assertEqual(result["verdict"], "ACCEPT_AS_IS")
        self.assertEqual(result["mdcp"]["precision_level"], "high")
        self.assertIn(result["mdcp"]["conversation_plane"], {"spec", "execution"})
        self.assertTrue(result["mdcp"]["scope_anchor"])

    def test_request_outputs_mdcp_scope_signals(self) -> None:
        self.start_permission()

        result = self.json_run("request", "--text", "Add full RBAC platform", check=False)

        self.assertNotEqual(result["verdict"], "ACCEPT_AS_IS")
        self.assertIn("layer_1_structured_expression", result["mdcp"])
        self.assertIn(result["mdcp"]["layer_1_structured_expression"]["scope_sink_risk"], {"weak", "strong"})
        self.assertTrue(result.get("rejected_scope") or result["mdcp"]["layer_2_company_roles"]["custodian"]["rejected_scope"])

    def test_check_includes_mdcp_audit(self) -> None:
        self.start_video()

        result = self.json_run("check", "--verbose")

        self.assertIn("mdcp_audit", result)
        self.assertIn(result["mdcp_audit"]["status"], {"OK", "WARNING", "BLOCK"})
        self.assertIn("same_axis_loop_check", result["mdcp_audit"]["checks"])
        self.assertIn("acceptance_consumer_check", result["mdcp_audit"]["checks"])

    def test_check_outputs_mdcp_auditor_status(self) -> None:
        self.start_video()

        result = self.json_run("check", "--verbose")

        self.assertEqual(result["status"], "NEEDS_VALIDATION")
        self.assertEqual(result["mdcp"]["layer_3_janitor_auditor"]["auditor"]["status"], "NEEDS_VALIDATION")
        self.assertEqual(result["mdcp"]["layer_3_janitor_auditor"]["auditor"]["required_action"], "run_validation")

    def test_close_requires_mdcp_layer_3_pass(self) -> None:
        self.install_validation("fail_validation", "import sys; sys.exit(1)")
        ticket = self.make_validation_ticket("fail_validation")
        ticket["ticket_id"] = "MDCP-CLOSE-FAIL"
        self.write_json(".agent/tickets/pending/MDCP-CLOSE-FAIL.json", ticket)
        self.goal_video()
        self.json_run("start", ".agent/tickets/pending/MDCP-CLOSE-FAIL.json")
        self.complete_company_runtime()

        result = self.json_run("close", check=False)

        self.assertEqual(result["status"], "NOT_CERTIFIED")
        self.assertEqual(result["ticket_status"], "ACTIVE")
        auditor_status = result["mdcp"]["layer_3_janitor_auditor"]["auditor"]["status"]
        self.assertIn(auditor_status, {"VALIDATION_FAILED", "FAIL"})
        self.assertFalse(result["mdcp"]["layer_3_pass_criteria"]["validation_not_failed"])

    def test_status_includes_mdcp_without_new_flow(self) -> None:
        self.start_video()

        result = self.json_run("status")

        self.assertEqual(result["mdcp"]["acceptance_consumer"], "validation_catalog")
        self.assertTrue(result["mdcp"]["scope_anchor"])

    def test_ready_refreshes_mdcp_acceptance_consumer(self) -> None:
        self.goal_video()
        (self.root / "rough_task.md").write_text(
            "# Mock video artifact pipeline\nPrompt to mock video artifact path.\n",
            encoding="utf-8",
        )
        self.json_run("compile", "rough_task.md", "--out", ".agent/tickets/pending/STALE-MDCP.json")
        ticket = self.read_json(".agent/tickets/pending/STALE-MDCP.json")
        self.assertEqual(ticket["mdcp"]["layer_1_fields"]["acceptance_consumer"], "draft ticket reviewer")

        ticket["global_goal"] = "Build an AI automatic video generation system"
        ticket["why_now"] = "This proves the smallest prompt to mock artifact path."
        ticket["validation_ids"] = ["mock_video_pipeline_test"]
        ticket["acceptance"]["commands_pass"] = ["mock_video_pipeline_test"]
        ticket["acceptance"]["files_exist"] = []
        ticket["allowed_paths"] = ["src/video/mock/**", "tests/video/**"]
        ticket["forbidden_paths"] = [".env", ".agent/**", "src/security/**"]
        ticket["budget"] = {"max_minutes": 30, "max_tool_calls": 40, "max_changed_files": 5, "max_diff_lines": 300}
        ticket["drift_signals"] = ["Starts building provider marketplace"]
        self.write_json(".agent/tickets/pending/STALE-MDCP.json", ticket)

        self.json_run("ready", ".agent/tickets/pending/STALE-MDCP.json")
        updated = self.read_json(".agent/tickets/pending/STALE-MDCP.json")

        self.assertEqual(updated["mdcp"]["layer_1_fields"]["acceptance_consumer"], "validation_catalog")
        self.assertIn("Prompt to mock video artifact path", json.dumps(updated["mdcp"]["layer_1_fields"]["scope_anchor"]))

    def test_status_reports_refreshed_mdcp_consumer(self) -> None:
        self.goal_video()
        (self.root / "rough_task.md").write_text(
            "# Mock video artifact pipeline\nPrompt to mock video artifact path.\n",
            encoding="utf-8",
        )
        self.json_run("compile", "rough_task.md", "--out", ".agent/tickets/pending/STATUS-MDCP.json")
        ticket = self.read_json(".agent/tickets/pending/STATUS-MDCP.json")
        ticket["global_goal"] = "Build an AI automatic video generation system"
        ticket["why_now"] = "This proves the smallest prompt to mock artifact path."
        ticket["validation_ids"] = ["mock_video_pipeline_test"]
        ticket["acceptance"]["commands_pass"] = ["mock_video_pipeline_test"]
        ticket["allowed_paths"] = ["src/video/mock/**", "tests/video/**"]
        ticket["forbidden_paths"] = [".env", ".agent/**", "src/security/**"]
        ticket["budget"] = {"max_minutes": 30, "max_tool_calls": 40, "max_changed_files": 5, "max_diff_lines": 300}
        ticket["drift_signals"] = ["Starts building provider marketplace"]
        self.write_json(".agent/tickets/pending/STATUS-MDCP.json", ticket)
        self.json_run("ready", ".agent/tickets/pending/STATUS-MDCP.json")
        self.json_run("start", ".agent/tickets/pending/STATUS-MDCP.json")

        result = self.json_run("status")

        self.assertEqual(result["mdcp"]["acceptance_consumer"], "validation_catalog")

    def test_onboard_scan_ignores_mdcp_protocol_files(self) -> None:
        (self.root / "README.md").write_text(
            "AI Automatic Video Generator. This project turns prompts into video artifacts.\n",
            encoding="utf-8",
        )
        self.goal_video()

        result = self.json_run("onboard-scan", "--verbose", check=False)
        artifacts = json.dumps(result.get("inventory", []), ensure_ascii=False)
        evidence = json.dumps(result.get("supporting_evidence", []), ensure_ascii=False)

        self.assertNotIn(".agent/protocols/mdcp.md", artifacts)
        self.assertNotIn(".agent/protocols/mdcp.md", evidence)
        self.assertIn("mdcp", result)

    def test_mdcp_never_uses_gate_language(self) -> None:
        (self.root / "rough_task.md").write_text("# Mock video artifact\nPrompt to mock artifact path.\n", encoding="utf-8")
        self.json_run("compile", "rough_task.md", "--out", ".agent/tickets/pending/GATE-LANG.json")
        self.start_video()
        outputs = [
            self.read_json(".agent/tickets/pending/GATE-LANG.json")["mdcp"],
            self.json_run("status")["mdcp"],
            self.json_run("check")["mdcp"],
            self.json_run("request", "--text", "Build video provider marketplace now")["mdcp"],
            self.json_run("onboard-scan", "--verbose", check=False)["mdcp"],
        ]

        for output in outputs:
            self.assertFalse(self.has_gate_language(output), json.dumps(output, ensure_ascii=False))

    def has_gate_language(self, value) -> bool:
        text = json.dumps(value, ensure_ascii=False).lower()
        blocked = [
            r"\bapprove\b",
            r"\bsign\b",
            r"role approval",
            r"board passed",
            r"decision approved",
        ]
        return any(__import__("re").search(pattern, text) for pattern in blocked)


class MDCPInstallTests(MinimalPluginFixtureCase):
    def test_installer_allows_mdcp_protocols_without_root_pollution(self) -> None:
        writes, _, _ = run_installer_no_subprocess(
            self.plugin / "scripts" / "install_governor.py",
            self.repo,
            force=True,
        )

        self.assertGreater(writes, 0)
        self.assertTrue((self.repo / ".agent" / "protocols" / "mdcp.md").exists())
        self.assertTrue((self.repo / ".agent" / "protocols" / "mdcp.schema.json").exists())
        self.assertFalse((self.repo / "mdcp.md").exists())
        self.assertEqual((self.repo / "README.md").read_text(encoding="utf-8"), "User README\n")
