from __future__ import annotations

try:
    from .helpers import GoalCompassRepoCase
except ImportError:
    from helpers import GoalCompassRepoCase


class RequestGateTests(GoalCompassRepoCase):
    def start_claim_intake(self) -> None:
        goal = "Build an insurance claims workflow that assembles evidence and supports explainable adjuster decisions."
        self.cli("goal-set", "--text", goal)
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket.update({
            "ticket_id": "CLAIM-INTAKE-001",
            "title": "Claim intake evidence",
            "global_goal": goal,
            "task_goal": "Capture claimant identity, incident details, and photo evidence in the current claim intake.",
            "must_do": ["Capture claimant photo evidence in claim intake", "Return an intake evidence reference"],
            "must_not_do": ["Do not build enterprise assignment orchestration"],
            "anti_patterns": ["enterprise assignment platform", "full RBAC"],
            "allowed_paths": ["src/claims/intake/**", "tests/claims/intake/**"],
            "forbidden_paths": [".agent/**", ".codex/**", ".git/**", "src/platform/**"],
            "acceptance": {
                "commands_pass": [],
                "files_exist": ["src/claims/intake/photo_evidence.py"],
                "contains": [],
                "assertions": [],
                "files_not_changed": [],
                "max_changed_files": 4,
                "max_diff_lines": 240,
            },
            "validation_ids": [],
            "budget": {"max_minutes": 30, "max_tool_calls": 40, "max_changed_files": 4, "max_diff_lines": 240},
            "drift_signals": ["Starts building an enterprise claims platform"],
            "backlog_only": ["Add catastrophe surge assignment rules after claim intake"],
            "status": "PENDING",
            "acceptance_ready": True,
        })
        self.write_json(".agent/tickets/pending/CLAIM-INTAKE-001.json", ticket)
        self.cli("start", ".agent/tickets/pending/CLAIM-INTAKE-001.json")

    def test_request_rejects_video_rbac_platform(self) -> None:
        self.start_video()
        result = self.json_run("request", "--text", "Add video RBAC platform support", check=False)
        self.assertNotEqual(result["verdict"], "ACCEPT_AS_IS")
        self.assertIn(result["verdict"], {"REJECT", "BACKLOG", "SPLIT"})

    def test_request_backlogs_provider_marketplace(self) -> None:
        self.start_video()
        request = "Build video provider marketplace now"
        result = self.json_run("request", "--text", request)
        self.assertNotEqual(result["verdict"], "ACCEPT_AS_IS")
        self.assertIn(result["verdict"], {"BACKLOG", "SPLIT"})
        backlog = (self.root / ".agent" / "backlog.jsonl").read_text(encoding="utf-8")
        self.assertIn(request, backlog)

    def test_request_rejects_enterprise_permission_platform(self) -> None:
        self.start_video()
        result = self.json_run("request", "--text", "Add enterprise permission platform for video", check=False)
        self.assertNotEqual(result["verdict"], "ACCEPT_AS_IS")
        self.assertIn(result["verdict"], {"REJECT", "BACKLOG"})

    def test_request_accepts_small_acceptance_assertion(self) -> None:
        self.start_video()
        result = self.json_run("request", "--text", "Add assertion for returned mock artifact path")
        self.assertEqual(result["verdict"], "ACCEPT_AS_IS")

    def test_request_accepts_noise_reduction(self) -> None:
        self.start_video()
        result = self.json_run("request", "--text", "Remove useless over-abstracted provider registry")
        self.assertEqual(result["verdict"], "ACCEPT_AS_IS")

    def test_permission_request_simplifies_full_rbac(self) -> None:
        self.start_permission()
        result = self.json_run("request", "--text", "Add full RBAC system")
        self.assertEqual(result["verdict"], "ACCEPT_SIMPLIFIED")
        self.assertIn("current ticket", result["minimal_action"])
        self.assertIn("permission check", result["minimal_action"])

    def test_future_backlog_word_overlap_does_not_reject_current_claim_intake(self) -> None:
        self.start_claim_intake()

        result = self.json_run("request", "--text", "Add claimant photo evidence capture to current claim intake")

        self.assertEqual(result["verdict"], "ACCEPT_AS_IS")
        self.assertTrue(result["allowed_current_change"])

    def test_broad_ticket_does_not_allow_enterprise_rbac_scope(self) -> None:
        self.start_claim_intake()

        result = self.json_run("request", "--text", "Add full enterprise RBAC platform for insurance claims", check=False)

        self.assertNotEqual(result["verdict"], "ACCEPT_AS_IS")
        self.assertFalse(result["allowed_current_change"])

    def test_domain_name_overlap_alone_does_not_simplify_marketplace_scope(self) -> None:
        goal = "Build a property asset operations system for real estate inspections and maintenance."
        self.cli("goal-set", "--text", goal)
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket.update({
            "ticket_id": "REAL-ESTATE-001",
            "global_goal": goal,
            "task_goal": "Implement one bounded real_estate inspection result.",
            "must_do": ["Return one inspection result"],
            "must_not_do": ["Do not build an enterprise marketplace"],
            "anti_patterns": ["enterprise marketplace"],
            "allowed_paths": ["src/real_estate/**"],
            "forbidden_paths": [".agent/**", ".codex/**", ".git/**"],
            "acceptance": {
                "commands_pass": [],
                "files_exist": ["src/real_estate/result.py"],
                "contains": [],
                "assertions": [],
                "files_not_changed": [],
                "max_changed_files": 3,
                "max_diff_lines": 180,
            },
            "validation_ids": [],
            "drift_signals": ["Starts building an enterprise marketplace"],
            "backlog_only": ["Enterprise marketplace"],
            "status": "PENDING",
            "acceptance_ready": True,
        })
        self.write_json(".agent/tickets/pending/REAL-ESTATE-001.json", ticket)
        self.cli("start", ".agent/tickets/pending/REAL-ESTATE-001.json")

        result = self.json_run(
            "request",
            "--text",
            "Build a full enterprise marketplace platform for real_estate now",
        )

        self.assertIn(result["verdict"], {"BACKLOG", "REJECT", "SPLIT"})
        self.assertFalse(result["allowed_current_change"])

    def test_split_request_is_persisted_as_original_backlog_text(self) -> None:
        self.start_claim_intake()
        request = "Add adjuster decision analytics for future insurance claims"

        result = self.json_run("request", "--text", request)

        self.assertEqual(result["verdict"], "SPLIT")
        backlog_rows = [
            __import__("json").loads(line)
            for line in (self.root / ".agent" / "backlog.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(backlog_rows[-1]["text"], request)

    def test_unrelated_validation_wording_is_not_automatically_accepted(self) -> None:
        self.start_claim_intake()

        result = self.json_run("request", "--text", "Add validation for a future finance export", check=False)

        self.assertNotEqual(result["verdict"], "ACCEPT_AS_IS")

    def test_packaging_completion_verb_is_current_but_erp_platform_is_not(self) -> None:
        goal = "Build a corrugated packaging workflow with compression testing and traceable release evidence."
        self.cli("goal-set", "--text", goal)
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket.update({
            "ticket_id": "CARTON-COMPRESSION-001",
            "global_goal": goal,
            "task_goal": "Add the carton compression test assertion and record its result.",
            "must_do": ["Run carton compression test", "Record compression result"],
            "must_not_do": ["Do not build a complete packaging ERP platform"],
            "anti_patterns": ["packaging ERP platform"],
            "allowed_paths": ["src/carton/**", "tests/carton/**"],
            "forbidden_paths": [".agent/**", ".codex/**", ".git/**"],
            "acceptance": {
                "commands_pass": [],
                "files_exist": ["tests/carton/test_compression.py"],
                "contains": [],
                "assertions": [],
                "files_not_changed": [],
                "max_changed_files": 4,
                "max_diff_lines": 240,
            },
            "validation_ids": [],
            "drift_signals": ["Starts building packaging ERP"],
            "backlog_only": ["Packaging ERP"],
            "status": "PENDING",
            "acceptance_ready": True,
        })
        self.write_json(".agent/tickets/pending/CARTON-COMPRESSION-001.json", ticket)
        self.cli("start", ".agent/tickets/pending/CARTON-COMPRESSION-001.json")

        current = self.json_run("request", "--text", "Complete the carton compression test assertion")
        oversized = self.json_run(
            "request",
            "--text",
            "Build a complete packaging ERP platform for carton compression testing",
            check=False,
        )

        self.assertEqual(current["verdict"], "ACCEPT_AS_IS")
        self.assertTrue(current["allowed_current_change"])
        self.assertNotEqual(oversized["verdict"], "ACCEPT_AS_IS")
        self.assertFalse(oversized["allowed_current_change"])

    def test_heavy_packaging_scope_cannot_be_washed_by_current_process_words(self) -> None:
        goal = "Build a flexible packaging workflow with seal-window inspection and traceable lot evidence."
        self.cli("goal-set", "--text", goal)
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket.update({
            "ticket_id": "POUCH-SEAL-001",
            "global_goal": goal,
            "task_goal": "Implement one bounded PE pouch seal-window inspection result.",
            "must_do": ["Record PE pouch seal temperature window", "Record leak-test result"],
            "must_not_do": ["Do not build a full ERP platform"],
            "anti_patterns": ["full ERP platform", "supplier marketplace", "enterprise RBAC"],
            "allowed_paths": ["src/flexible_packaging/**", "tests/flexible_packaging/**"],
            "forbidden_paths": [".agent/**", ".codex/**", ".git/**"],
            "acceptance": {
                "commands_pass": [],
                "files_exist": ["src/flexible_packaging/seal_window.py"],
                "contains": [],
                "assertions": [],
                "files_not_changed": [],
                "max_changed_files": 4,
                "max_diff_lines": 240,
            },
            "validation_ids": [],
            "drift_signals": ["Starts building enterprise systems"],
            "backlog_only": ["ERP", "supplier marketplace", "enterprise RBAC"],
            "status": "PENDING",
            "acceptance_ready": True,
        })
        self.write_json(".agent/tickets/pending/POUCH-SEAL-001.json", ticket)
        self.cli("start", ".agent/tickets/pending/POUCH-SEAL-001.json")

        requests = [
            "Build a full ERP platform now for PE pouch seal-window inspection",
            "Build a packaging supplier marketplace now for PE pouch seal-window inspection",
            "Add enterprise RBAC platform now for PE pouch seal-window inspection",
        ]
        for request in requests:
            with self.subTest(request=request):
                result = self.json_run("request", "--text", request, check=False)
                self.assertNotEqual(result["verdict"], "ACCEPT_AS_IS")
                self.assertFalse(result["allowed_current_change"])

    def test_chinese_packaging_core_request_maps_to_current_ticket(self) -> None:
        goal = "为瓦楞纸箱制造提供可追溯的 ECT 与 BCT 测试记录。"
        self.cli("goal-set", "--text", goal)
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket.update({
            "ticket_id": "BCT-CHINESE-001",
            "global_goal": goal,
            "task_goal": "仅新增一份 BCT 测试记录的最小 JSON 样例。",
            "must_do": ["记录 BCT 测试 sample_id", "输出当前 BCT 合格判定"],
            "must_not_do": ["不得扩展 ERP、RBAC、供应商市场或生产排程"],
            "anti_patterns": ["ERP", "RBAC", "供应商市场"],
            "allowed_paths": ["work/current_record.json", "tests/corrugated/**"],
            "forbidden_paths": [".agent/**", ".codex/**", ".git/**"],
            "acceptance": {
                "commands_pass": [],
                "files_exist": ["work/current_record.json"],
                "contains": [],
                "assertions": [],
                "files_not_changed": [],
                "max_changed_files": 3,
                "max_diff_lines": 160,
            },
            "validation_ids": [],
            "drift_signals": ["开始建设 ERP 或供应商市场"],
            "backlog_only": ["ERP", "RBAC", "供应商市场"],
            "status": "PENDING",
            "acceptance_ready": True,
        })
        self.write_json(".agent/tickets/pending/BCT-CHINESE-001.json", ticket)
        self.cli("start", ".agent/tickets/pending/BCT-CHINESE-001.json")

        result = self.json_run("request", "--text", "为当前 BCT 记录补齐 sample_id 字段")

        self.assertEqual(result["verdict"], "ACCEPT_AS_IS")
        self.assertTrue(result["allowed_current_change"])

    def test_unmatched_read_only_audit_is_allowed_without_product_edit(self) -> None:
        self.goal_video()

        result = self.json_run("request", "--text", "Audit repository dependency status only")

        self.assertEqual(result["verdict"], "ACCEPT_READ_ONLY")
        self.assertTrue(result["read_only_allowed"])
        self.assertFalse(result["product_edit_allowed"])

    def test_code_fix_is_not_read_only_when_inputs_are_read_only(self) -> None:
        self.start_video()

        result = self.json_run(
            "request",
            "--text",
            "修改 mock video pipeline 代码，只读取现有 artifact metadata；增加 returned mock artifact path assertion。",
        )

        self.assertEqual(result["operation_class"], "product_edit")
        self.assertNotEqual(result["verdict"], "ACCEPT_READ_ONLY")
        self.assertFalse(result["read_only_allowed"])

    def test_forbidden_stop_clause_does_not_turn_fix_into_correction(self) -> None:
        self.start_video()

        result = self.json_run(
            "request",
            "--text",
            "修复 mock video artifact path 回归；不得停止现有 mock job，不执行真实 provider 发布。",
        )

        self.assertEqual(result["operation_class"], "product_edit")
        self.assertNotEqual(result["verdict"], "ACCEPT_READ_ONLY")
        self.assertNotEqual(result.get("goal_mapping"), ["scope_reduction"])

    def test_negated_stop_with_status_check_remains_read_only(self) -> None:
        self.goal_video()

        result = self.json_run(
            "request",
            "--text",
            "不得停止生产进程，只检查当前状态。",
        )

        self.assertEqual(result["operation_class"], "read_only")
        self.assertEqual(result["verdict"], "ACCEPT_READ_ONLY")

    def test_product_edit_can_route_from_active_program_phase(self) -> None:
        self.goal_video()
        self.write_json(".agent/program_phase.json", {
            "status": "ACTIVE",
            "phase_id": "VIDEO-ROUTING-MVP",
            "goal": "Route a prompt through the mock video adapter and return the artifact path.",
            "exit_criteria": ["Mock adapter routing and artifact path regression pass."],
        })

        result = self.json_run(
            "request",
            "--text",
            "Implement the mock adapter routing and artifact path regression.",
        )

        self.assertEqual(result["verdict"], "PROPOSE_NEW_TICKET")
        self.assertEqual(result["operation_class"], "product_edit")
        self.assertEqual(result["program_phase_alignment"], "MAPPED")

    def test_fix_can_route_from_latest_failed_ticket(self) -> None:
        self.goal_video()
        self.write_json(".agent/last_ticket.json", {
            "ticket_id": "VIDEO-IDLE-WAIT-FAILED",
            "status": "FAIL",
            "task_goal": "Repair acquired to idle waiting in the mock video adapter.",
        })

        result = self.json_run(
            "request",
            "--text",
            "Fix acquired to idle waiting in the mock video adapter and add a regression.",
        )

        self.assertEqual(result["verdict"], "PROPOSE_NEW_TICKET")
        self.assertEqual(result["operation_class"], "product_edit")
        self.assertTrue(any(value.startswith("failed_ticket:") for value in result["goal_mapping"]))

    def test_stop_request_is_not_misread_as_positive_scope(self) -> None:
        self.start_video()

        result = self.json_run("request", "--text", "Do not continue building provider marketplace; stop that scope")

        self.assertEqual(result["verdict"], "ACCEPT_AS_IS")
        self.assertFalse(result["allowed_current_change"])
        self.assertIn("scope-reduction", result["reason"])

    def test_severe_drift_rewrite_is_rejected_not_always_backlogged(self) -> None:
        self.goal_video()
        ticket = self.read_json(".agent/tickets/examples/VIDEO-MOCK-001.json")
        ticket["ticket_id"] = "DRIFT-ROUTE-001"
        ticket["drift_signals"] = ["Rewrite the whole current routing implementation"]
        self.write_json(".agent/tickets/pending/DRIFT-ROUTE-001.json", ticket)
        self.json_run("start", ".agent/tickets/pending/DRIFT-ROUTE-001.json")

        result = self.json_run("request", "--text", "Rewrite the whole current routing implementation", check=False)

        self.assertEqual(result["verdict"], "REJECT")
        self.assertFalse(result["allowed_current_change"])
