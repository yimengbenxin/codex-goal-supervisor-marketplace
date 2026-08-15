from __future__ import annotations

import hashlib
import json

try:
    from .helpers import GOAL_COMPASS, GoalCompassRepoCase
except ImportError:
    from helpers import GOAL_COMPASS, GoalCompassRepoCase


def detailed_goal_definition() -> dict:
    return {
        "precise_goal": "Build a traceable packaging release evidence system for plant quality teams.",
        "problem_statement": "Plant test evidence and release decisions are fragmented and cannot be reproduced reliably.",
        "current_state": "Lot data, laboratory results, and release decisions live in separate manual records.",
        "desired_state": "One workflow links every lot to test evidence, release state, and a reproducible audit trail.",
        "stakeholders": ["plant quality engineer", "production supervisor", "release auditor"],
        "source_requirements": [
            "Support multiple packaging materials without creating separate products.",
            "Every release result must expose its supporting evidence.",
        ],
        "first_principles": [
            {
                "principle": "A release claim is valid only when its evidence is traceable.",
                "rationale": "A status without source measurements cannot be reproduced or audited.",
                "implications": ["Every result stores evidence references", "Missing evidence blocks final release"],
            },
            {
                "principle": "Material differences are bounded rules, not separate product cores.",
                "rationale": "Duplicating the workflow per material creates drift and inconsistent decisions.",
                "implications": ["Share one lot lifecycle", "Keep material rules behind explicit interfaces"],
            },
        ],
        "process": {
            "entry_conditions": ["A lot identity and required test plan exist"],
            "nodes": [
                {
                    "node_id": "N1",
                    "name": "Evidence intake",
                    "objective": "Create a complete evidence record for one packaging lot.",
                    "inputs": ["lot metadata", "required test plan", "measurement results"],
                    "actions": ["validate identifiers", "normalize measurements", "link source records"],
                    "outputs": ["validated lot evidence record"],
                    "exit_criteria": ["all required measurements are present or explicitly marked missing"],
                    "dependencies": [],
                    "execution_mode": "SERIAL",
                    "contribution_to_goal": "Creates the traceable evidence foundation required by every downstream release decision.",
                    "timebox_hours": 2,
                    "reminder_interval_hours": 0,
                },
                {
                    "node_id": "N2",
                    "name": "Release evaluation",
                    "objective": "Evaluate the lot against material-specific release rules.",
                    "inputs": ["validated lot evidence record", "versioned release rules"],
                    "actions": ["run rule checks", "record failures", "build decision evidence"],
                    "outputs": ["release result with evidence links", "machine-readable failure report"],
                    "exit_criteria": ["every rule has a deterministic result and evidence reference"],
                    "dependencies": ["N1"],
                    "execution_mode": "SERIAL",
                    "contribution_to_goal": "Turns validated evidence into the reproducible release outcome promised by the product goal.",
                    "timebox_hours": 5,
                    "reminder_interval_hours": 2,
                },
            ],
            "completion_conditions": ["The release result and evidence trail are available to downstream users"],
        },
        "deliverables": [
            {
                "name": "Packaging release workflow",
                "description": "Runnable local workflow from lot evidence intake to release result.",
                "format": "application plus machine-readable records",
                "consumer": "plant quality team",
                "acceptance": ["A fixture lot produces a deterministic release result", "Evidence links resolve"],
            }
        ],
        "final_acceptance": [
            {
                "criterion": "A representative lot completes the full workflow with a reproducible release result.",
                "evidence": "fixture input, result record, and linked rule evidence",
                "validation_method": "run the focused end-to-end validation command and inspect its machine result",
            }
        ],
        "constraints": ["Do not replace plant MES or laboratory instruments"],
        "non_goals": ["Enterprise compliance platform", "Generic workflow marketplace"],
        "assumptions": ["Test measurements can be exported in a machine-readable form"],
        "open_questions": [],
        "planning_research": {
            "completed": True,
            "researched_at": "2026-08-14T00:00:00Z",
            "tool_sources_reviewed": 3,
            "article_sources_reviewed": 2,
            "refresh_interval_hours": 24,
            "reusable_candidate_found": False,
            "no_suitable_reuse_reason": "Reviewed tools do not satisfy the packaging evidence contract and deterministic local validation boundary.",
        },
    }


def super_complex_plan_text() -> str:
    modules = [
        ("M1 需求与边界", "确认使用者、业务边界、输入来源和不可改变约束", "形成可追踪需求矩阵和非目标清单"),
        ("M2 数据与接口合同", "定义数据结构、错误语义、版本规则和跨模块接口", "让后续模块能够并行开发且不会因命名和语义不一致返工"),
        ("M3 核心处理链路", "实现从输入校验、规范化到核心结果生成的最小闭环", "交付可验证的核心用户价值"),
        ("M4 存储与追踪", "保存版本、证据、状态变化和可恢复检查点", "保证结果可复现、可查询并支持失败恢复"),
        ("M5 用户工作流", "实现主要页面、操作反馈、异常状态和恢复入口", "让真实用户能够完成端到端任务"),
        ("M6 质量与验证", "建立单元、合同、集成和端到端验证", "把完成声明转换为可重复执行的证据"),
        ("M7 安装与配置", "固化依赖、环境检查、默认配置和可回滚升级步骤", "让交付物能在目标环境稳定启动而不是只在开发机运行"),
        ("M8 运行与恢复", "定义运行状态、健康检查、失败分类、检查点和最小恢复命令", "让长任务在局部失败后从受影响节点恢复而不是整体重跑"),
        ("M9 交付与签收", "汇总真实功能证据、质量样本、已知限制和操作说明", "确保最终成品由用户价值与验收结果签收而不是由活动量签收"),
    ]
    lines = [
        "# 项目完整技术方案",
        "",
        "## 目标",
        "本方案把最终用户目标拆成可验证模块，确保每个模块都有明确输入、动作、输出、消费者和验收方式。方案正文只保留调研后形成的最终技术路线，不陈列市场调研过程或候选工具清单。",
        "",
        "## 执行步骤",
        "先冻结需求边界和接口合同，再并行推进没有写冲突的实现模块，最后串行完成集成、质量验证和交付。任何模块未满足退出标准时，不得把下游级联错误冒充新的独立问题。",
        "",
        "## 并行与串行关系",
        "M1 和 M2 必须串行完成，因为接口合同依赖已确认需求。M3、M4、M5 可在 M2 后进入同一并行组，但只能修改各自所有的路径；共享结构的变化回到 M2 统一。M6 在各实现模块产出后串行集成，也可以提前并行准备测试夹具。",
        "",
        "## 模块依赖与对总目标的贡献",
    ]
    for name, action, contribution in modules:
        lines.extend([
            f"### {name}",
            f"模块动作：{action}。执行时先核对前置输入，再完成最小实现，随后生成机器可读证据。不得以未来扩展、泛化平台或未被当前目标需要的抽象替代当前交付。",
            f"依赖关系：该模块只消费上一阶段已签收的合同和产物；若依赖失败，当前模块标记为被上游阻断，不继续制造级联错误。并行模块之间通过稳定接口交换数据，不直接修改彼此内部实现。",
            f"对总目标的助力：{contribution}。这一贡献必须能映射到最终成功标准，不能只用文件数量、代码行数或调用次数证明进展。",
            "产出与验收：产出包含实现、结构化状态和对应测试证据。验收必须说明输入、预期结果、失败语义和重复执行方法；需要人工判断的质量项要提供可查看样本，不能由文件存在性代替。",
            "异常与恢复：若验证失败，只报告第一个可行动根因，保存已通过节点和产物哈希，从受影响节点重试。若新增需求不属于当前模块，则进入后续范围，不静默改变本模块合同。",
            "",
        ])
    lines.extend([
        "## 集成与依赖检验",
        "集成时逐项验证接口名称、字段语义、错误码、版本约束、存储路径和恢复行为。并行模块必须使用同一份合同；发现冲突时先修正合同，再只重跑受影响模块。所有跨模块输入输出都要有正向、非法输入和边界条件样例。",
        "",
        "## 完成验收",
        "最终验收依次执行构建、合同验证、集成验证、端到端用户流程和交付检查。上游失败后下游标记为跳过，不输出无意义级联错误。验收内容覆盖核心功能、错误恢复、兼容性、性能边界、用户可见质量和运行说明，并保留命令、结果与产物引用。",
        "",
        "## 最终交付",
        "交付物包括可运行项目、必要配置样例、完整测试结果、已知限制、恢复方法和面向使用者的启动说明。交付前再次核对所有模块对总目标的贡献，删除或隔离没有映射且未被依赖的候选内容，确认没有用管理材料替代真实产品结果。",
    ])
    text = "\n".join(lines)
    if len(text) < 4001:
        raise AssertionError(f"complex plan fixture is too short: {len(text)}")
    return text


def super_complex_goal_definition(plan_ref: str, *, confirmed: bool = True) -> dict:
    definition = detailed_goal_definition()
    definition["complexity_level"] = "SUPER_COMPLEX"
    definition["execution_plan_ref"] = plan_ref
    consultation = {
        "asked_in_conversation": confirmed,
        "reuse_choice": "ADAPT" if confirmed else "",
        "commercial_use": "COMMERCIAL" if confirmed else "",
    }
    definition["planning_research"] = {
        "completed": True,
        "researched_at": "2026-08-04T00:00:00Z",
        "tool_sources_reviewed": 3,
        "article_sources_reviewed": 2,
        "refresh_interval_hours": 24,
        "reusable_candidate_found": True,
        "reusable_candidate_name": "ExistingTool",
        "user_consultation": consultation,
        "reuse_decisions": [{
            "module": "Evidence intake",
            "candidate": "ExistingTool",
            "decision": "ADAPT",
            "planned_use": "Reuse its parser behind the local evidence contract.",
            "reason": "The parser is useful but its result schema needs a bounded adapter.",
            "license": "MIT, commercial use confirmed",
            "validation": "Run the focused evidence-intake contract test.",
        }],
    }
    summary_source = dict(definition)
    summary_source["complexity_level"] = "STANDARD"
    summary_source["goal_mode_summary"] = None
    summary_source["execution_plan_ref"] = None
    standard = GOAL_COMPASS.goal_definition_from_payload(definition["precise_goal"], summary_source)
    definition["goal_mode_summary"] = GOAL_COMPASS.render_goal_mode_objective(standard) + "\n并行：无。"
    return definition


class GoalDetectTests(GoalCompassRepoCase):
    def test_goal_detect_prefers_quant_product_over_legacy_glb_compat_docs(self) -> None:
        (self.root / "README.md").write_text(
            "Hermes Alpha is a multi-market quantitative trading control system with market data, "
            "expert research, candidate selection, portfolio decisions, execution rules, AB tests, and backtests.\n",
            encoding="utf-8",
        )
        scripts = self.root / "scripts"
        scripts.mkdir()
        (scripts / "quant-autopilot.py").write_text(
            "# stock trading market data portfolio broker backtest\n"
            "# Guardrail: do not build a full security gateway platform here.\n",
            encoding="utf-8",
        )
        docs = self.root / "docs"
        docs.mkdir()
        (docs / "compatibility.md").write_text(
            "Legacy compatibility note for an unrelated GLB product modeling and video adapter route.\n",
            encoding="utf-8",
        )

        detected = self.json_run("goal-detect")

        self.assertIn("quantitative trading", detected["project_detected_goal"].lower())
        self.assertNotIn("glb", detected["project_detected_goal"].lower())
        first = detected["detected_candidate_goals"][0]
        self.assertIn("README.md", json.dumps(first["supporting_evidence"], ensure_ascii=False))
        self.assertIn("scripts/quant-autopilot.py", json.dumps(first["supporting_evidence"], ensure_ascii=False))
        self.assertNotIn("scripts/quant-autopilot.py", json.dumps(first["noise_evidence"], ensure_ascii=False))

    def test_financial_market_is_not_treated_as_marketplace(self) -> None:
        self.cli(
            "goal-set",
            "--text",
            "构建以 Hermes 为运行框架的多市场量化交易系统，覆盖行情、候选池、组合决策、交易执行与回测。",
        )

        north = self.read_json(".agent/north_star_goal.json")

        self.assertEqual(north["goal"], "构建以 Hermes 为运行框架的多市场量化交易系统，覆盖行情、候选池、组合决策、交易执行与回测。")
        self.assertNotIn("marketplace", json.dumps(north["main_path"], ensure_ascii=False).lower())
        self.assertNotIn("marketplace", json.dumps(north["allowed_subgoals"], ensure_ascii=False).lower())
        self.assertEqual(north["allowed_subgoals"], [])

    def test_init_preserves_existing_confirmed_goal_contract_exactly(self) -> None:
        goal = "构建以 Hermes 为运行框架的多市场量化交易系统，覆盖行情、候选池、组合决策、交易执行与回测。"
        legacy = {
            "confirmed": True,
            "goal": goal,
            "source": "user_confirmed",
            "confirmed_at": "2026-07-09T00:00:00+00:00",
            "main_path": ["hermes", "marketplace"],
            "allowed_subgoals": ["hermes", "marketplace"],
            "anti_goals": [],
            "backlog_domains": ["marketplace"],
            "protected_principles": [],
            "core_path_patterns": ["src/**"],
            "candidate_goals": [],
            "requires_confirmation": False,
        }
        self.write_json(".agent/north_star_goal.json", legacy)

        self.cli("init")
        north = self.read_json(".agent/north_star_goal.json")

        self.assertEqual(north, legacy)

    def test_goal_set_stores_first_principles_actions_and_deliverables(self) -> None:
        goal = "Build a reusable packaging manufacturing quality evidence system."

        result = self.json_run(
            "goal-set",
            "--text", goal,
            "--dialogue-summary", "The user needs one durable quality workflow across packaging plants.",
            "--problem", "Packaging teams cannot connect test evidence to release decisions consistently.",
            "--first-principle", "Every release claim must map to traceable machine-checkable evidence.",
            "--first-principle", "Material-specific edge cases must not redefine the common product core.",
            "--action", "Capture lot, test, and release evidence through one bounded workflow.",
            "--deliverable", "A runnable local quality evidence application.",
            "--success-criterion", "A sample lot can be evaluated with a reproducible evidence trail.",
            "--constraint", "Do not replace plant MES or laboratory instruments.",
            "--non-goal", "Enterprise compliance platform.",
        )
        north = self.read_json(".agent/north_star_goal.json")

        self.assertTrue(result["structured"])
        self.assertEqual(north["goal_definition"]["quality"], "STRUCTURED")
        self.assertEqual(len(north["goal_definition"]["first_principles"]), 2)
        self.assertIn("Capture lot", north["goal_definition"]["concrete_actions"][0])
        self.assertIn("runnable local", north["goal_definition"]["deliverables"][0])
        self.assertIn("reproducible evidence", north["goal_definition"]["success_criteria"][0])
        self.assertIn(north["goal_definition"]["concrete_actions"][0], north["main_path"])

    def test_goal_set_preserves_existing_goal_without_explicit_replacement(self) -> None:
        original = "Build a regional hospital bed-capacity planning tool."
        self.cli("goal-set", "--text", original)

        result = self.json_run(
            "goal-set",
            "--text", "Build an unrelated enterprise marketplace.",
            check=False,
        )
        north = self.read_json(".agent/north_star_goal.json")

        self.assertEqual(result["status"], "EXISTING_GOAL_PRESERVED")
        self.assertEqual(result["required_action"], "reuse_existing_goal")
        self.assertEqual(north["goal"], original)

    def test_goal_set_text_only_exposes_missing_structure(self) -> None:
        result = self.json_run("goal-set", "--text", "Build a bounded scheduling workflow.")

        self.assertFalse(result["structured"])
        self.assertEqual(result["goal_definition"]["quality"], "TEXT_ONLY")
        self.assertIn("first_principles>=2", result["goal_definition"]["missing_fields"])

    def test_goal_set_accepts_detailed_process_nodes_outputs_and_final_acceptance(self) -> None:
        path = self.root / "goal-definition.json"
        path.write_text(json.dumps(detailed_goal_definition(), ensure_ascii=False, indent=2), encoding="utf-8")

        result = self.json_run(
            "goal-set",
            "--text", detailed_goal_definition()["precise_goal"],
            "--definition-file", "goal-definition.json",
            "--require-detailed",
        )
        north = self.read_json(".agent/north_star_goal.json")
        definition = north["goal_definition"]

        self.assertTrue(result["detailed"])
        self.assertEqual(definition["quality"], "STRUCTURED_DETAILED")
        self.assertEqual(definition["detail_metrics"]["process_node_count"], 2)
        self.assertEqual(definition["process"]["nodes"][1]["outputs"][0], "release result with evidence links")
        self.assertIn("validation_method", definition["final_acceptance"][0])
        self.assertIn(definition["process"]["nodes"][0]["objective"], north["main_path"])
        status = self.json_run("status", "--verbose")
        self.assertEqual(len(status["north_star"]["definition"]["process_nodes"]), 2)
        self.assertEqual(status["north_star"]["definition"]["final_acceptance"][0]["evidence"], "fixture input, result record, and linked rule evidence")

    def test_goal_mode_objective_is_structured_and_verifies_before_delivery(self) -> None:
        path = self.root / "goal-definition.json"
        path.write_text(json.dumps(detailed_goal_definition(), ensure_ascii=False, indent=2), encoding="utf-8")

        result = self.json_run(
            "goal-set",
            "--text", detailed_goal_definition()["precise_goal"],
            "--definition-file", "goal-definition.json",
            "--require-detailed",
        )

        objective = result["goal_mode_objective"]
        self.assertTrue(objective.startswith("目标：Build a traceable packaging release evidence system"))
        self.assertIn("1. 第一性原理", objective)
        self.assertIn("2. 大板块、具体动作与节点签收", objective)
        self.assertIn("具体动作：validate identifiers", objective)
        self.assertIn("签收标准：every rule has a deterministic result", objective)
        self.assertIn("小时目标：从实际启动起 5 小时内完成", objective)
        self.assertIn("每 2 小时检查一次", objective)
        self.assertIn("3. 模块间联调与接口检验", objective)
        self.assertIn("4. 最终成品交付前的全链路检验", objective)
        self.assertIn("5. 最终成品交付", objective)
        self.assertIn("7. 开源复用与不重复造轮子", objective)
        self.assertIn("连续运行每满 24 小时", objective)
        self.assertLess(objective.index("最终成品交付前的全链路检验"), objective.index("5. 最终成品交付"))
        self.assertGreaterEqual(len(objective), 2000)
        self.assertLessEqual(len(objective), 3500)

    def test_detailed_goal_requires_research_and_hour_level_segments(self) -> None:
        definition = detailed_goal_definition()
        definition.pop("planning_research")
        definition["process"]["nodes"][0].pop("timebox_hours")
        path = self.root / "goal-definition.json"
        path.write_text(json.dumps(definition, ensure_ascii=False, indent=2), encoding="utf-8")

        result = self.json_run(
            "goal-set",
            "--text", definition["precise_goal"],
            "--definition-file", "goal-definition.json",
            "--require-detailed",
            check=False,
        )

        self.assertEqual(result["status"], "GOAL_DEFINITION_INCOMPLETE")
        self.assertIn("planning_research.completed", result["missing_fields"])
        self.assertIn("planning_research.refresh_interval_hours=24", result["missing_fields"])
        self.assertIn("process.nodes[0].timebox_hours>0", result["missing_fields"])

    def test_long_segment_requires_bounded_reminder_cadence(self) -> None:
        definition = detailed_goal_definition()
        definition["process"]["nodes"][1]["reminder_interval_hours"] = 0
        path = self.root / "goal-definition.json"
        path.write_text(json.dumps(definition, ensure_ascii=False, indent=2), encoding="utf-8")

        result = self.json_run(
            "goal-set",
            "--text", definition["precise_goal"],
            "--definition-file", "goal-definition.json",
            "--require-detailed",
            check=False,
        )

        self.assertIn("process.nodes[1].reminder_interval_hours", result["missing_fields"])

    def test_north_star_sentence_is_separate_from_detailed_goal_mode_contract(self) -> None:
        definition = detailed_goal_definition()
        path = self.root / "goal-definition.json"
        path.write_text(json.dumps(definition, ensure_ascii=False, indent=2), encoding="utf-8")

        result = self.json_run(
            "goal-set",
            "--text", "Build a traceable packaging release evidence system.",
            "--definition-file", "goal-definition.json",
            "--require-detailed",
        )
        north = self.read_json(".agent/north_star_goal.json")

        self.assertEqual(north["goal"], "Build a traceable packaging release evidence system.")
        self.assertLess(len(north["goal"]), 120)
        self.assertGreaterEqual(len(result["goal_mode_objective"]), 2000)
        self.assertNotEqual(north["goal"], result["goal_mode_objective"])

    def test_goal_set_returns_exact_native_goal_sync_contract(self) -> None:
        definition = detailed_goal_definition()
        path = self.root / "goal-definition.json"
        path.write_text(json.dumps(definition, ensure_ascii=False, indent=2), encoding="utf-8")

        result = self.json_run(
            "goal-set",
            "--text", "Build a traceable packaging release evidence system.",
            "--definition-file", "goal-definition.json",
            "--require-detailed",
        )
        north = self.read_json(".agent/north_star_goal.json")
        objective = result["goal_mode_objective"]
        expected_hash = hashlib.sha256(objective.encode("utf-8")).hexdigest()

        self.assertEqual(result["native_goal_sync"]["status"], "CREATE_REQUIRED")
        self.assertEqual(result["native_goal_sync"]["objective_source_field"], "goal_mode_objective")
        self.assertEqual(result["native_goal_sync"]["objective_chars"], len(objective))
        self.assertEqual(result["native_goal_sync"]["objective_sha256"], expected_hash)
        self.assertIn("create_goal", result["native_goal_sync"]["required_action"])
        self.assertIn("get_goal", result["native_goal_sync"]["required_action"])
        self.assertEqual(north["native_goal_contract"]["objective_sha256"], expected_hash)
        self.assertEqual(north["native_goal_contract"]["objective_chars"], len(objective))

    def test_super_complex_goal_keeps_compressed_contract_and_references_full_plan(self) -> None:
        plan_ref = "docs/PROJECT_EXECUTION_PLAN.md"
        plan_path = self.root / plan_ref
        plan_path.parent.mkdir(parents=True)
        plan = super_complex_plan_text()
        plan_path.write_text(plan, encoding="utf-8")
        definition = super_complex_goal_definition(plan_ref)
        definition_path = self.root / "goal-definition.json"
        definition_path.write_text(json.dumps(definition, ensure_ascii=False, indent=2), encoding="utf-8")

        result = self.json_run(
            "goal-set",
            "--text", "Build a traceable packaging release evidence system.",
            "--definition-file", "goal-definition.json",
            "--require-detailed",
        )
        objective = result["goal_mode_objective"]

        self.assertGreaterEqual(len(objective), 2000)
        self.assertLessEqual(len(objective), 3500)
        self.assertIn(plan_ref, objective)
        self.assertEqual(result["execution_plan_ref"], plan_ref)
        self.assertGreater(len(plan), 4000)
        self.assertNotIn("tool_sources_reviewed", plan)
        self.assertNotIn("reuse_decisions", plan)

    def test_super_complex_goal_requires_visible_reuse_and_commercial_consultation(self) -> None:
        plan_ref = "docs/PROJECT_EXECUTION_PLAN.md"
        plan_path = self.root / plan_ref
        plan_path.parent.mkdir(parents=True)
        plan_path.write_text(super_complex_plan_text(), encoding="utf-8")
        definition = super_complex_goal_definition(plan_ref, confirmed=False)
        definition_path = self.root / "goal-definition.json"
        definition_path.write_text(json.dumps(definition, ensure_ascii=False, indent=2), encoding="utf-8")

        result = self.json_run(
            "goal-set",
            "--text", "Build a traceable packaging release evidence system.",
            "--definition-file", "goal-definition.json",
            "--require-detailed",
            check=False,
        )

        self.assertEqual(result["status"], "GOAL_DEFINITION_INCOMPLETE")
        self.assertIn("planning_research.user_consultation.asked_in_conversation", result["missing_fields"])
        self.assertIn("planning_research.user_consultation.commercial_use", result["missing_fields"])
        self.assertEqual(result["required_action"], "ask_user_about_reuse_and_commercial_use")
        self.assertIn("ExistingTool", result["user_question"])
        self.assertFalse(self.read_json(".agent/north_star_goal.json")["confirmed"])

    def test_super_complex_goal_rejects_plan_below_four_thousand_characters(self) -> None:
        plan_ref = "docs/PROJECT_EXECUTION_PLAN.md"
        plan_path = self.root / plan_ref
        plan_path.parent.mkdir(parents=True)
        plan_path.write_text(
            "# 目标\n## 执行步骤\n## 并行\n## 串行\n## 依赖\n## 对总目标的贡献\n## 验收\n",
            encoding="utf-8",
        )
        definition = super_complex_goal_definition(plan_ref)
        definition_path = self.root / "goal-definition.json"
        definition_path.write_text(json.dumps(definition, ensure_ascii=False, indent=2), encoding="utf-8")

        result = self.json_run(
            "goal-set",
            "--text", "Build a traceable packaging release evidence system.",
            "--definition-file", "goal-definition.json",
            "--require-detailed",
            check=False,
        )

        self.assertEqual(result["status"], "GOAL_DEFINITION_INCOMPLETE")
        self.assertIn("execution_plan_chars>=4001", result["missing_fields"])

    def test_goal_set_rejects_short_summary_when_detailed_goal_is_required(self) -> None:
        shallow = {
            "precise_goal": "Build a packaging tool.",
            "problem_statement": "Records are fragmented.",
            "first_principles": ["Keep evidence traceable"],
            "deliverables": ["A working tool"],
            "final_acceptance": ["It works"],
        }
        (self.root / "shallow.json").write_text(json.dumps(shallow), encoding="utf-8")

        result = self.json_run(
            "goal-set",
            "--text", "Build a packaging tool.",
            "--definition-file", "shallow.json",
            "--require-detailed",
            check=False,
        )

        self.assertEqual(result["status"], "GOAL_DEFINITION_INCOMPLETE")
        self.assertIn("process.nodes>=2", result["missing_fields"])
        self.assertFalse(self.read_json(".agent/north_star_goal.json")["confirmed"])

    def test_goal_set_rejects_structured_contract_below_goal_mode_minimum(self) -> None:
        compact = detailed_goal_definition()
        compact.update({
            "problem_statement": "Evidence is fragmented.",
            "current_state": "No shared result.",
            "desired_state": "One verified result.",
            "stakeholders": ["operator"],
            "source_requirements": ["Produce one verified result."],
            "constraints": ["Stay local."],
            "non_goals": ["No platform."],
            "assumptions": [],
        })
        compact["first_principles"] = [
            {"principle": "Use evidence.", "rationale": "Claims need proof.", "implications": ["Validate output."]},
            {"principle": "Stay bounded.", "rationale": "Scope costs time.", "implications": ["Avoid extras."]},
        ]
        for index, node in enumerate(compact["process"]["nodes"], 1):
            node.update({
                "name": f"Step {index}",
                "objective": "Produce one bounded result.",
                "inputs": ["prior result"],
                "actions": ["perform step"],
                "outputs": ["step result"],
                "exit_criteria": ["result exists"],
                "contribution_to_goal": "Advances the verified result.",
            })
        compact["deliverables"] = [{
            "name": "Result", "description": "Verified result.", "format": "file",
            "consumer": "operator", "acceptance": ["result passes"],
        }]
        compact["final_acceptance"] = [{
            "criterion": "Result passes.", "evidence": "result file", "validation_method": "run check",
        }]
        path = self.root / "compact.json"
        path.write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8")

        result = self.json_run(
            "goal-set", "--text", "Build one verified result.",
            "--definition-file", "compact.json", "--require-detailed", check=False,
        )

        self.assertEqual(result["status"], "GOAL_DEFINITION_INCOMPLETE")
        self.assertIn("goal_mode_objective_chars=2000..3500", result["missing_fields"])

    def test_goal_set_does_not_truncate_overlong_goal_mode_contract(self) -> None:
        definition = detailed_goal_definition()
        definition["source_requirements"].append("保留全部真实需求细节，不允许静默截断。" * 100)
        path = self.root / "overlong.json"
        path.write_text(json.dumps(definition, ensure_ascii=False, indent=2), encoding="utf-8")

        result = self.json_run(
            "goal-set", "--text", "Build a traceable packaging release evidence system.",
            "--definition-file", "overlong.json", "--require-detailed", check=False,
        )

        self.assertEqual(result["status"], "GOAL_DEFINITION_INCOMPLETE")
        self.assertIn("goal_mode_objective_chars=2000..3500", result["missing_fields"])
        self.assertFalse(self.read_json(".agent/north_star_goal.json")["confirmed"])

    def test_goal_detect_self_words_without_product_evidence_returns_unknown(self) -> None:
        work = self.root / "work"
        work.mkdir()
        (work / "operator_notes.md").write_text(
            "Goal Compass should use North Star and scope-sink controls during this run.\n",
            encoding="utf-8",
        )

        detected = self.json_run("goal-detect")

        self.assertEqual(detected["project_detected_goal"], "Unknown project goal.")
        first = detected["detected_candidate_goals"][0]
        self.assertNotIn("Goal Compass", first["goal"])

    def test_goal_detect_ignores_goal_compass_files(self) -> None:
        (self.root / "README.md").write_text(
            "AI Automatic Video Generator. This project turns prompts into video artifacts.\n",
            encoding="utf-8",
        )
        generator = self.root / "src" / "video" / "mock" / "generator.ts"
        generator.parent.mkdir(parents=True)
        generator.write_text("export function promptToVideoArtifact(){ return 'mock.mp4'; }\n", encoding="utf-8")
        test = self.root / "tests" / "video" / "mock-video-pipeline.test.ts"
        test.parent.mkdir(parents=True)
        test.write_text("test('prompt to video artifact', () => {});\n", encoding="utf-8")
        detected = self.json_run("goal-detect")
        goal = detected["project_detected_goal"].lower()
        self.assertIn("video", goal)
        self.assertNotIn("goal compass", goal)
        self.assertNotIn("custodian", goal)
        self.assertNotIn("janitor", goal)
        self.assertNotIn("harness", goal)

    def test_goal_detect_does_not_use_rbac_as_supporting_evidence(self) -> None:
        (self.root / "README.md").write_text(
            "AI Automatic Video Generator. This project turns prompts into video artifacts.\n",
            encoding="utf-8",
        )
        rbac = self.root / "src" / "security" / "rbac" / "full.ts"
        rbac.parent.mkdir(parents=True)
        rbac.write_text(
            "// prompt routing adapter video artifact AI video generation\nexport const roles = [];\n",
            encoding="utf-8",
        )
        detected = self.json_run("goal-detect")
        first = detected["detected_candidate_goals"][0]
        self.assertIn("video", detected["project_detected_goal"].lower())
        support = json.dumps(first.get("supporting_evidence", first.get("evidence", [])), ensure_ascii=False)
        self.assertNotIn("src/security/rbac/full.ts", support)
        rejected = json.dumps(
            first.get("backlog_candidate_evidence", [])
            + first.get("noise_evidence", [])
            + first.get("contradicting_evidence", []),
            ensure_ascii=False,
        )
        self.assertIn("src/security/rbac/full.ts", rejected)

    def test_goal_detect_does_not_use_marketplace_as_supporting_evidence(self) -> None:
        (self.root / "README.md").write_text(
            "AI Automatic Video Generator. This project turns prompts into video artifacts.\n",
            encoding="utf-8",
        )
        market = self.root / "src" / "providers" / "marketplace" / "index.ts"
        market.parent.mkdir(parents=True)
        market.write_text(
            "// prompt adapter video artifact for AI video generation\nexport const marketplace = [];\n",
            encoding="utf-8",
        )
        detected = self.json_run("goal-detect")
        first = detected["detected_candidate_goals"][0]
        self.assertIn("video", detected["project_detected_goal"].lower())
        support = json.dumps(first.get("supporting_evidence", first.get("evidence", [])), ensure_ascii=False)
        self.assertNotIn("src/providers/marketplace/index.ts", support)
        rejected = json.dumps(
            first.get("backlog_candidate_evidence", [])
            + first.get("noise_evidence", [])
            + first.get("contradicting_evidence", []),
            ensure_ascii=False,
        )
        self.assertIn("src/providers/marketplace/index.ts", rejected)

    def test_goal_detect_prefers_glb_product_goal_over_goal_compass_words(self) -> None:
        (self.root / "README.md").write_text(
            "Goal Compass is enabled for this run.\n"
            "The real product goal is an AI automatic GLB product modeling system with SVG dieline input, UV alignment, and quality checks.\n",
            encoding="utf-8",
        )
        detected = self.json_run("goal-detect")
        goal = detected["project_detected_goal"].lower()
        self.assertIn("glb", goal)
        self.assertIn("model", goal)
        self.assertNotIn("goal compass", goal)

    def test_goal_detect_reads_work_brief_files(self) -> None:
        work = self.root / "work"
        work.mkdir()
        (work / "AI全自动建模技术路线整理.md").write_text(
            "目标是用 AI Agent 完成 GLB 商品模型自动建模、SVG / 刀版解析、UV 映射、自动质检，并输出可换图的 GLB。\n",
            encoding="utf-8",
        )
        detected = self.json_run("goal-detect")
        goal = detected["project_detected_goal"].lower()
        self.assertIn("glb", goal)
        support = json.dumps(detected["detected_candidate_goals"][0].get("supporting_evidence", []), ensure_ascii=False)
        self.assertIn("work/AI全自动建模技术路线整理.md", support)

    def test_goal_detect_detects_agent_registry_over_mockup_binary(self) -> None:
        (self.root / "README.md").write_text(
            "LAN Agent Registry / Skill Hub MVP. Upload zip Agent packages, validate agent.yaml and README.md, "
            "scan secrets, support sanitize_mode, store in SQLite, search, download, and keep a SHA256 hash-chain ledger.\n",
            encoding="utf-8",
        )
        work = self.root / "work"
        work.mkdir()
        (work / "mockup.png").write_bytes(b"\x89PNG\r\nGoal Compass GLB video artifact fake binary words")
        detected = self.json_run("goal-detect")
        goal = detected["project_detected_goal"].lower()
        self.assertIn("agent registry", goal)
        self.assertIn("skill hub", goal)
        support = json.dumps(detected["detected_candidate_goals"][0].get("supporting_evidence", []), ensure_ascii=False)
        self.assertIn("README.md", support)
        self.assertNotIn("work/mockup.png", support)

    def test_goal_set_structures_glb_north_star(self) -> None:
        goal = "Build an AI Agent driven automatic GLB product modeling system with SVG dieline input, UV alignment, route decisions, and quality checks."
        self.cli(
            "goal-set",
            "--text",
            goal,
        )
        north = self.read_json(".agent/north_star_goal.json")
        self.assertEqual(north["goal"], goal)
        self.assertTrue(north["main_path"])
        self.assertEqual(north["allowed_subgoals"], [])
        self.assertEqual(north["anti_goals"], [])
        self.assertEqual(north["backlog_domains"], [])
        self.assertIn(goal, north["main_path"])

    def test_goal_set_does_not_inject_product_defaults(self) -> None:
        goal = "Build a hospital bed-capacity planning tool for regional operations teams."
        self.cli("goal-set", "--text", goal)

        north = self.read_json(".agent/north_star_goal.json")

        encoded = json.dumps(north, ensure_ascii=False).lower()
        self.assertEqual(north["goal"], goal)
        self.assertNotIn("video", encoded)
        self.assertNotIn("glb", encoded)
        self.assertNotIn("provider marketplace", encoded)

    def test_confirmed_rich_video_goal_accepts_generic_same_domain_detection(self) -> None:
        self.cli(
            "goal-set",
            "--text",
            "Build a profitable AI video product with an official funnel, mock-first production path, creator workflow, and measurable delivery quality.",
        )

        result = self.json_run("goal-check", "--user-goal", "Build an AI automatic video generation system.")

        self.assertIn(result["status"], {"ALIGNED", "PARTIAL"})

    def test_exact_confirmed_north_star_is_aligned(self) -> None:
        goal = "Build an aviation maintenance planning system that links findings to auditable work packages."
        self.cli("goal-set", "--text", goal)

        result = self.json_run("goal-check", "--user-goal", goal)

        self.assertEqual(result["status"], "ALIGNED")
        self.assertEqual(result["alignment_score"], 1.0)

    def test_unconfirmed_north_star_requires_confirmation_without_command_failure(self) -> None:
        proc = self.cli(
            "goal-check",
            "--user-goal", "Build a bounded hospital planning tool.",
            check=False,
        )
        result = json.loads(proc.stdout)

        self.assertEqual(proc.returncode, 0)
        self.assertEqual(result["status"], "NEEDS_CONFIRMATION")
        self.assertEqual(result["alignment_status"], "UNKNOWN")
        self.assertEqual(result["required_action"], "confirm_north_star")

    def test_confirmed_product_geometry_goal_accepts_glb_same_domain_detection(self) -> None:
        self.cli(
            "goal-set",
            "--text",
            "构建产品几何操作系统，覆盖商品建模、结构解析、贴图映射、质量校验和专业软件交付。",
        )

        result = self.json_run("goal-check", "--user-goal", "Build an AI automatic GLB product modeling system.")

        self.assertIn(result["status"], {"ALIGNED", "PARTIAL"})

    def test_truly_conflicting_known_domains_mismatch(self) -> None:
        self.cli("goal-set", "--text", "Build an AI automatic video generation system.")

        result = self.json_run(
            "goal-check",
            "--user-goal",
            "Build a multi-market quantitative trading system with portfolio execution and backtesting.",
            check=False,
        )

        self.assertEqual(result["status"], "MISMATCH")

    def test_goal_detect_uses_generic_medical_readme_without_domain_defaults(self) -> None:
        (self.root / "README.md").write_text(
            "# Regional Bed Capacity Planner\n"
            "Build a hospital bed-capacity planning tool that forecasts demand, coordinates transfers, and gives operations teams an auditable daily plan.\n",
            encoding="utf-8",
        )

        result = self.json_run("goal-detect")

        goal = result["project_detected_goal"].lower()
        self.assertIn("hospital", goal)
        self.assertIn("bed-capacity", goal)
        self.assertNotIn("video", goal)
        self.assertNotIn("glb", goal)

    def test_goal_detect_prefers_goal_md_exact_wording(self) -> None:
        rich_goal = "Build a legal matter intelligence service that preserves privilege boundaries, links evidence to claims, and produces human-reviewable litigation timelines."
        (self.root / "GOAL.md").write_text("# North Star\n" + rich_goal + "\n", encoding="utf-8")
        (self.root / "README.md").write_text("# Legal AI Tool\nA generic legal application.\n", encoding="utf-8")

        result = self.json_run("goal-detect")

        self.assertEqual(result["project_detected_goal"], rich_goal)
        self.assertIn("GOAL.md", json.dumps(result["detected_candidate_goals"][0]["supporting_evidence"], ensure_ascii=False))

    def test_goal_detect_accepts_declarative_chinese_goal_md(self) -> None:
        goal = "为瓦楞纸板、纸箱与运输包装制造提供可追溯的实验室测试记录与合格判定，覆盖纸质、ECT、BCT、抗压、跌落、印刷、模切、钉粘箱。"
        (self.root / "GOAL.md").write_text("# North Star Goal\n\n" + goal + "\n", encoding="utf-8")

        detected = self.json_run("goal-detect")
        self.cli("goal-set", "--text", goal)
        scan = self.json_run("onboard-scan", "--verbose", check=False)

        self.assertEqual(detected["project_detected_goal"], goal)
        self.assertEqual(scan["goal_alignment"], "ALIGNED")

    def test_goal_detect_does_not_invent_unknown_domain_when_docs_are_ambiguous(self) -> None:
        (self.root / "README.md").write_text("# Atlas\nNotes and links.\n", encoding="utf-8")

        result = self.json_run("goal-detect")

        self.assertEqual(result["project_detected_goal"], "Unknown project goal.")
