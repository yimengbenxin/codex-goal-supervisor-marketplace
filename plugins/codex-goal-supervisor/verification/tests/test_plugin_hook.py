from __future__ import annotations

import concurrent.futures
import json
import os
import shlex
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

try:
    from .helpers import DEFAULT_TIMEOUT, PLUGIN_ROOT, SCRIPT, copy_goal_compass_runtime, install_product_test_fixtures, run_cmd, run_goal_compass
except ImportError:
    from helpers import DEFAULT_TIMEOUT, PLUGIN_ROOT, SCRIPT, copy_goal_compass_runtime, install_product_test_fixtures, run_cmd, run_goal_compass


HOOK = PLUGIN_ROOT / "scripts" / "goal_hook.py"


class PluginHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_disable_llm_judge = os.environ.get("GOAL_SUPERVISOR_DISABLE_LLM_JUDGE")
        self._old_session_binding_dir = os.environ.get("GOAL_SUPERVISOR_SESSION_BINDING_DIR")
        os.environ["GOAL_SUPERVISOR_DISABLE_LLM_JUDGE"] = "1"
        self.tmp = tempfile.TemporaryDirectory()
        self.parent = Path(self.tmp.name)
        os.environ["GOAL_SUPERVISOR_SESSION_BINDING_DIR"] = str(self.parent / "session-bindings")
        self.repo = self.parent / "nested project 中文"
        copy_goal_compass_runtime(self.repo, writable=True)
        self.cli("init")
        install_product_test_fixtures(self.repo)

    def tearDown(self) -> None:
        self.tmp.cleanup()
        if self._old_disable_llm_judge is None:
            os.environ.pop("GOAL_SUPERVISOR_DISABLE_LLM_JUDGE", None)
        else:
            os.environ["GOAL_SUPERVISOR_DISABLE_LLM_JUDGE"] = self._old_disable_llm_judge
        if self._old_session_binding_dir is None:
            os.environ.pop("GOAL_SUPERVISOR_SESSION_BINDING_DIR", None)
        else:
            os.environ["GOAL_SUPERVISOR_SESSION_BINDING_DIR"] = self._old_session_binding_dir

    def cli(self, *args: str, cwd: Path | None = None):
        result = run_goal_compass(list(args), cwd=cwd or self.repo)
        if result.returncode != 0:
            raise AssertionError(f"goal_compass {args} failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
        return result

    def hook(self, event: dict) -> str:
        proc = run_cmd(
            [sys.executable, str(HOOK)],
            cwd=self.parent,
            timeout=DEFAULT_TIMEOUT,
            check=True,
            input_text=json.dumps(event),
        )
        return proc.stdout

    def complete_company_runtime(self) -> None:
        status = self.cli("company-status")
        company = json.loads(status.stdout)["company_subagents"]
        for index, role in enumerate(company.get("missing_roles", [])):
            agent_id = f"hook-{role}-{index}"
            self.cli("company-record", "--role", role, "--agent-id", agent_id, "--status", "STARTED")
            self.cli("company-record", "--role", role, "--agent-id", agent_id, "--status", "COMPLETED", "--result-hash", f"hook-{role}-result")

    def activate_video(self, cwd: Path | None = None) -> None:
        self.cli("goal-set", "--text", "Build an AI automatic video generation system.", cwd=cwd)
        self.cli("start", ".agent/tickets/examples/VIDEO-MOCK-001.json", cwd=cwd)

    def activate_video_with_company(self) -> None:
        self.cli("goal-set", "--text", "Build an AI automatic video generation system.")
        source = self.repo / ".agent" / "tickets" / "examples" / "VIDEO-MOCK-001.json"
        ticket = json.loads(source.read_text(encoding="utf-8"))
        ticket["ticket_id"] = "VIDEO-MOCK-COMPANY"
        ticket["requested_company_departments"] = ["engineering"]
        pending = self.repo / ".agent" / "tickets" / "pending" / "VIDEO-MOCK-COMPANY.json"
        pending.parent.mkdir(parents=True, exist_ok=True)
        pending.write_text(json.dumps(ticket, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.cli("start", ".agent/tickets/pending/VIDEO-MOCK-COMPANY.json")

    def test_plugin_hook_config_is_globally_passive(self) -> None:
        config = json.loads((PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))

        self.assertEqual(config, {"hooks": {}})

    def test_repo_local_hook_remains_portable(self) -> None:
        config = json.loads((self.repo / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        encoded = json.dumps(config, ensure_ascii=False)

        self.assertIn("project_hook.py", encoded)
        self.assertNotIn("/Users/", encoded)
        self.assertIn("commandWindows", encoded)
        self.assertIn("-X utf8", encoded)
        self.assertNotIn(" -c ", config["hooks"]["PreToolUse"][0]["hooks"][0]["commandWindows"])
        self.assertIn("windows_hook.py", encoded)
        for event in ("PreCompact", "PostCompact", "SessionStart", "SubagentStart", "UserPromptSubmit", "Stop"):
            self.assertIn(event, config["hooks"])
        self.assertNotIn("additionalContextLimit", config["hooks"]["PreCompact"][0]["hooks"][0])
        self.assertEqual(config["hooks"]["SessionStart"][0]["hooks"][0]["additionalContextLimit"], 800)

    def test_repo_hook_records_and_closes_temporary_prompt(self) -> None:
        self.cli("goal-set", "--text", "Build a reliable local product.")
        prompt_output = self.hook({
            "session_id": "hook-goal-return",
            "turn_id": "turn-1",
            "cwd": str(self.repo),
            "hook_event_name": "UserPromptSubmit",
            "prompt": "插一句：这个状态字段是什么意思？",
        })
        stop_output = self.hook({
            "session_id": "hook-goal-return",
            "turn_id": "turn-1",
            "cwd": str(self.repo),
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "这个字段表示当前阶段。",
        })

        self.assertIn("bounded temporary branch", prompt_output)
        self.assertEqual(json.loads(stop_output), {})
        state = json.loads((self.repo / ".agent/runtime/goal_return/state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["sessions"]["hook-goal-return"]["interrupts"][-1]["state"], "CLOSED")

    def test_long_term_goal_change_asks_once_only_after_high_confidence_judgment(self) -> None:
        self.cli("goal-set", "--text", "Build a private LAN Agent Registry for reusable internal Agent packages.")
        north_path = self.repo / ".agent" / "north_star_goal.json"
        north = json.loads(north_path.read_text(encoding="utf-8"))
        north["goal_mode_objective"] = "Private LAN Agent Registry execution contract. " + ("validated internal package workflow. " * 35)
        north["goal_definition"] = {
            "precise_goal": north["goal"],
            "process": {"nodes": [
                {"node_id": "N1", "name": "Package intake", "objective": "Validate internal packages."},
                {"node_id": "N2", "name": "Registry retrieval", "objective": "Search internal packages."},
            ]},
            "final_acceptance": [{"criterion": "Internal packages can be uploaded, searched, and downloaded."}],
        }
        north_path.write_text(json.dumps(north, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        fake = self.repo / "fake_goal_change_judge.py"
        log = self.repo / "fake_goal_change_judge.log"
        fake.write_text(
            "import json, os, pathlib, sys\n"
            "args=sys.argv[1:]\n"
            "prompt=sys.stdin.read()\n"
            "pathlib.Path(args[args.index('-o')+1]).write_text(json.dumps({"
            "'verdict':'CONFIRM_GOAL_CHANGE','confidence':'high',"
            "'rationale':'This is a durable product pivot outside the current registry goal.',"
            "'recommended_action':'ask_user_to_confirm_goal_change','evidence_needed':[]}), encoding='utf-8')\n"
            "with pathlib.Path(os.environ['FAKE_JUDGE_LOG']).open('a', encoding='utf-8') as h: h.write(json.dumps({'called':True,'prompt':prompt})+'\\n')\n",
            encoding="utf-8",
        )
        old_cmd = os.environ.get("GOAL_SUPERVISOR_JUDGE_CMD")
        try:
            os.environ.pop("GOAL_SUPERVISOR_DISABLE_LLM_JUDGE", None)
            os.environ["GOAL_SUPERVISOR_JUDGE_CMD"] = shlex.join([sys.executable, str(fake)])
            os.environ["FAKE_JUDGE_LOG"] = str(log)
            event = {
                "session_id": "goal-change-hook",
                "turn_id": "direction-1",
                "cwd": str(self.repo),
                "hook_event_name": "UserPromptSubmit",
                "prompt": "从现在起产品长期方向转向面向公众的量化交易平台，核心交付改为券商交易执行。",
            }
            first = self.hook(event)
            second = self.hook({**event, "turn_id": "direction-2"})
            confirmed = self.hook({
                **event,
                "turn_id": "direction-confirm",
                "prompt": "确认更新北极星",
            })
        finally:
            os.environ["GOAL_SUPERVISOR_DISABLE_LLM_JUDGE"] = "1"
            os.environ.pop("FAKE_JUDGE_LOG", None)
            if old_cmd is None:
                os.environ.pop("GOAL_SUPERVISOR_JUDGE_CMD", None)
            else:
                os.environ["GOAL_SUPERVISOR_JUDGE_CMD"] = old_cmd

        self.assertIn("是否确认更新北极星指标", first)
        self.assertEqual(second, "")
        self.assertIn("goal-set --replace-existing --require-detailed", confirmed)
        unchanged = json.loads(north_path.read_text(encoding="utf-8"))
        self.assertEqual(unchanged["goal"], "Build a private LAN Agent Registry for reusable internal Agent packages.")
        self.assertEqual(len(log.read_text(encoding="utf-8").splitlines()), 1)

    def test_temporary_or_contained_goal_request_does_not_ask_for_goal_change(self) -> None:
        self.cli("goal-set", "--text", "Build a private LAN Agent Registry for reusable internal Agent packages.")
        north_path = self.repo / ".agent" / "north_star_goal.json"
        north = json.loads(north_path.read_text(encoding="utf-8"))
        north["goal_mode_objective"] = "Private LAN Agent Registry execution contract. " + ("internal package upload search download. " * 35)
        north_path.write_text(json.dumps(north, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        common = {"session_id": "goal-change-negative", "cwd": str(self.repo), "hook_event_name": "UserPromptSubmit"}

        temporary = self.hook({**common, "turn_id": "temporary", "prompt": "临时检查一下量化 API 返回格式。"})
        contained = self.hook({
            **common,
            "turn_id": "contained",
            "prompt": "以后产品方向继续围绕私有局域网 Agent Registry，重点完成内部 Agent 包上传、搜索和下载。",
        })

        self.assertNotIn("Goal Direction Check", temporary)
        self.assertNotIn("更新北极星", contained)

    def test_explicit_goal_change_confirmation_survives_session_change(self) -> None:
        self.cli("goal-set", "--text", "Build a private LAN Agent Registry for reusable internal Agent packages.")
        north_path = self.repo / ".agent" / "north_star_goal.json"
        north = json.loads(north_path.read_text(encoding="utf-8"))
        north["goal_mode_objective"] = "Private LAN Agent Registry execution contract. " + ("validated internal package workflow. " * 35)
        north["goal_definition"] = {
            "precise_goal": north["goal"],
            "process": {"nodes": [
                {"node_id": "N1", "name": "Package intake"},
                {"node_id": "N2", "name": "Registry retrieval"},
            ]},
            "final_acceptance": [{"criterion": "Internal package loop works."}],
        }
        north_path.write_text(json.dumps(north, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        first = self.hook({
            "session_id": "goal-change-before-compaction",
            "turn_id": "direction-1",
            "cwd": str(self.repo),
            "hook_event_name": "UserPromptSubmit",
            "prompt": "把北极星改成面向公众的量化交易平台。",
        })
        repeated = self.hook({
            "session_id": "goal-change-after-compaction",
            "turn_id": "direction-2",
            "cwd": str(self.repo),
            "hook_event_name": "UserPromptSubmit",
            "prompt": "将北极星改为公开量化交易与券商执行平台。",
        })
        confirmed = self.hook({
            "session_id": "goal-change-after-compaction",
            "turn_id": "direction-confirm",
            "cwd": str(self.repo),
            "hook_event_name": "UserPromptSubmit",
            "prompt": "确认更新北极星",
        })

        self.assertIn("是否确认更新北极星指标", first)
        self.assertEqual(repeated, "")
        self.assertIn("goal-set --replace-existing --require-detailed", confirmed)

    def test_uncertain_goal_change_judgment_stays_silent(self) -> None:
        self.cli("goal-set", "--text", "Build a private LAN Agent Registry for reusable internal Agent packages.")
        north_path = self.repo / ".agent" / "north_star_goal.json"
        north = json.loads(north_path.read_text(encoding="utf-8"))
        north["goal_mode_objective"] = "Private LAN Agent Registry execution contract. " + ("validated internal package workflow. " * 35)
        north["goal_definition"] = {
            "precise_goal": north["goal"],
            "process": {"nodes": [
                {"node_id": "N1", "name": "Package intake"},
                {"node_id": "N2", "name": "Registry retrieval"},
            ]},
            "final_acceptance": [{"criterion": "Internal package loop works."}],
        }
        north_path.write_text(json.dumps(north, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        fake = self.repo / "fake_uncertain_goal_change_judge.py"
        fake.write_text(
            "import json, pathlib, sys\n"
            "args=sys.argv[1:]\n"
            "sys.stdin.read()\n"
            "pathlib.Path(args[args.index('-o')+1]).write_text(json.dumps({"
            "'verdict':'INSUFFICIENT_EVIDENCE','confidence':'low',"
            "'rationale':'The request may be a bounded exploration.',"
            "'recommended_action':'continue_without_goal_change_prompt','evidence_needed':[]}), encoding='utf-8')\n",
            encoding="utf-8",
        )
        old_cmd = os.environ.get("GOAL_SUPERVISOR_JUDGE_CMD")
        try:
            os.environ.pop("GOAL_SUPERVISOR_DISABLE_LLM_JUDGE", None)
            os.environ["GOAL_SUPERVISOR_JUDGE_CMD"] = shlex.join([sys.executable, str(fake)])
            output = self.hook({
                "session_id": "uncertain-goal-change",
                "turn_id": "direction-1",
                "cwd": str(self.repo),
                "hook_event_name": "UserPromptSubmit",
                "prompt": "以后产品方向可能转向面向公众的量化交易平台，先探索一下。",
            })
        finally:
            os.environ["GOAL_SUPERVISOR_DISABLE_LLM_JUDGE"] = "1"
            if old_cmd is None:
                os.environ.pop("GOAL_SUPERVISOR_JUDGE_CMD", None)
            else:
                os.environ["GOAL_SUPERVISOR_JUDGE_CMD"] = old_cmd

        self.assertNotIn("Goal Direction Check", output)
        self.assertNotIn("更新北极星", output)

    def test_repo_hook_restores_goal_after_compaction(self) -> None:
        self.cli("goal-set", "--text", "Build a reliable local product.")
        common = {"session_id": "hook-compact", "cwd": str(self.repo)}
        self.hook({**common, "turn_id": "turn-1", "hook_event_name": "UserPromptSubmit", "prompt": "插一句：解释发布状态？"})
        self.hook({**common, "turn_id": "turn-1", "hook_event_name": "Stop", "stop_hook_active": False, "last_assistant_message": "已完成解释。"})
        self.hook({**common, "turn_id": "turn-2", "hook_event_name": "PreCompact", "trigger": "auto"})
        self.hook({**common, "turn_id": "turn-2", "hook_event_name": "PostCompact", "trigger": "auto"})

        output = self.hook({**common, "turn_id": "turn-2", "hook_event_name": "SessionStart", "source": "compact"})

        self.assertIn("GOAL RETURN CHECKPOINT", output)
        self.assertIn("do not resume", output)
        self.assertIn("Build a reliable local product", output)

    def test_repo_hook_returns_from_temporary_branch_before_long_goal_turn_stops(self) -> None:
        self.cli("goal-set", "--text", "Build a reliable local product.")
        common = {"session_id": "hook-in-turn-return", "cwd": str(self.repo), "turn_id": "turn-1"}
        self.hook({
            **common,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "临时修复运行时重试逻辑。",
        })
        self.hook({
            **common,
            "hook_event_name": "PreToolUse",
            "tool_use_id": "branch-write",
            "tool_name": "apply_patch",
            "tool_input": {
                "patch": "*** Begin Patch\n*** Add File: src/runtime.py\n+value = 1\n*** End Patch",
            },
        })
        for tool_use_id in ("focused-check", "regression-check"):
            event = {
                **common,
                "tool_use_id": tool_use_id,
                "tool_name": "Bash",
                "tool_input": {"command": "python3 -m py_compile src/runtime.py"},
            }
            self.hook({**event, "hook_event_name": "PreToolUse"})
            output = self.hook({
                **event,
                "hook_event_name": "PostToolUse",
                "tool_response": {"exit_code": 0},
            })

        payload = json.loads(output)["hookSpecificOutput"]
        self.assertIn("temporary branch has product writes followed by two successful validations", payload["additionalContext"])
        self.assertIn("Do not keep revalidating", payload["additionalContext"])
        state = json.loads((self.repo / ".agent/runtime/goal_return/state.json").read_text(encoding="utf-8"))
        row = state["sessions"]["hook-in-turn-return"]["interrupts"][-1]
        self.assertEqual(row["state"], "CLOSED")
        self.assertEqual(row["close_reason"], "consecutive_validation_passes_after_write")

    def test_registered_product_command_closes_temporary_branch(self) -> None:
        self.cli("goal-set", "--text", "Build a reliable local product.")
        catalog_path = self.repo / ".agent" / "validation_catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        catalog["product_cycle"] = {
            "cmd": "{python} scripts/run_product_cycle.py --fresh",
            "description": "Run the registered product acceptance cycle.",
            "timeout_sec": 30,
        }
        catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        common = {"session_id": "hook-catalog-return", "cwd": str(self.repo), "turn_id": "turn-1"}
        self.hook({
            **common,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "临时修复生产周期执行问题。",
        })
        self.hook({
            **common,
            "hook_event_name": "PreToolUse",
            "tool_use_id": "catalog-write",
            "tool_name": "apply_patch",
            "tool_input": {
                "patch": "*** Begin Patch\n*** Add File: src/product_cycle.py\n+value = 1\n*** End Patch",
            },
        })
        output = ""
        for index in range(2):
            event = {
                **common,
                "tool_use_id": f"catalog-validation-{index}",
                "tool_name": "Bash",
                "tool_input": {"command": f"{sys.executable} scripts/run_product_cycle.py --fresh"},
            }
            self.hook({**event, "hook_event_name": "PreToolUse"})
            output = self.hook({
                **event,
                "hook_event_name": "PostToolUse",
                "tool_response": {"exit_code": 0},
            })

        payload = json.loads(output)["hookSpecificOutput"]
        self.assertIn("Do not keep revalidating", payload["additionalContext"])
        state = json.loads((self.repo / ".agent/runtime/goal_return/state.json").read_text(encoding="utf-8"))
        row = state["sessions"]["hook-catalog-return"]["interrupts"][-1]
        self.assertEqual(row["state"], "CLOSED")
        self.assertEqual(row["close_reason"], "consecutive_validation_passes_after_write")

    def test_unregistered_success_command_does_not_fake_branch_validation(self) -> None:
        self.cli("goal-set", "--text", "Build a reliable local product.")
        common = {"session_id": "hook-unregistered-command", "cwd": str(self.repo), "turn_id": "turn-1"}
        self.hook({
            **common,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "临时修复生产周期执行问题。",
        })
        self.hook({
            **common,
            "hook_event_name": "PreToolUse",
            "tool_use_id": "unregistered-write",
            "tool_name": "apply_patch",
            "tool_input": {
                "patch": "*** Begin Patch\n*** Add File: src/product_cycle.py\n+value = 1\n*** End Patch",
            },
        })
        for index in range(2):
            event = {
                **common,
                "tool_use_id": f"unregistered-command-{index}",
                "tool_name": "Bash",
                "tool_input": {"command": f"{sys.executable} scripts/unregistered_product_cycle.py"},
            }
            self.hook({**event, "hook_event_name": "PreToolUse"})
            self.assertEqual(self.hook({
                **event,
                "hook_event_name": "PostToolUse",
                "tool_response": {"exit_code": 0},
            }), "")

        state = json.loads((self.repo / ".agent/runtime/goal_return/state.json").read_text(encoding="utf-8"))
        row = state["sessions"]["hook-unregistered-command"]["interrupts"][-1]
        self.assertEqual(row["state"], "OPEN")
        self.assertEqual(row["evidence"], [])

    def test_first_closed_branch_replay_is_context_not_visible_reminder(self) -> None:
        self.cli("goal-set", "--text", "Build a reliable local product.")
        common = {"session_id": "hook-replay", "cwd": str(self.repo)}
        self.hook({**common, "turn_id": "turn-1", "hook_event_name": "UserPromptSubmit", "prompt": "临时修复 docs/temporary.md。"})
        original = {
            **common,
            "turn_id": "turn-1",
            "hook_event_name": "PreToolUse",
            "tool_use_id": "original-write",
            "tool_name": "apply_patch",
            "tool_input": {"patch": "*** Begin Patch\n*** Add File: docs/temporary.md\n+temporary\n*** End Patch"},
        }
        self.hook(original)
        self.hook({**common, "turn_id": "turn-1", "hook_event_name": "Stop", "stop_hook_active": False, "last_assistant_message": "已完成临时文档修复。"})
        self.hook({**common, "turn_id": "turn-2", "hook_event_name": "PreCompact", "trigger": "auto"})
        self.hook({**common, "turn_id": "turn-2", "hook_event_name": "PostCompact", "trigger": "auto"})

        replay = dict(original)
        replay["turn_id"] = "turn-3"
        replay["tool_use_id"] = "replay-write"
        output = self.hook(replay)
        payload = json.loads(output)["hookSpecificOutput"]

        self.assertIn("additionalContext", payload)
        self.assertNotIn("Codex Goal Supervisor reminder:", payload["additionalContext"])

    def test_plugin_source_template_is_not_selected_as_user_project(self) -> None:
        event = {
            "cwd": str(PLUGIN_ROOT),
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"patch": "*** Begin Patch\n*** Update File: README.md\n@@\n-old\n+new\n*** End Patch"},
        }
        proc = run_cmd(
            [sys.executable, str(HOOK)],
            cwd=PLUGIN_ROOT,
            timeout=DEFAULT_TIMEOUT,
            check=True,
            input_text=json.dumps(event),
        )

        self.assertEqual(proc.stdout, "")

    def test_nested_active_project_is_enforced_from_parent_session(self) -> None:
        self.activate_video()
        target = self.repo / "src" / "ui" / "forbidden.ts"
        event = {
            "cwd": str(self.parent),
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": f"*** Begin Patch\n*** Add File: {target}\n+x\n*** End Patch"},
        }

        output = self.hook(event)

        self.assertIn('"permissionDecision": "deny"', output)
        self.assertIn("forbids editing", output)

    def test_nearby_active_project_does_not_capture_unrelated_task(self) -> None:
        self.activate_video()
        event = {
            "cwd": str(self.parent),
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"patch": "*** Begin Patch\n*** Add File: unrelated.txt\n+x\n*** End Patch"},
        }

        self.assertEqual(self.hook(event), "")

    def test_explicit_nested_project_reference_binds_lifecycle_hooks_to_session(self) -> None:
        self.cli("goal-set", "--text", "Build a reliable local product.")
        common = {
            "session_id": "nested-goal-session",
            "cwd": str(self.parent),
        }
        self.hook({
            **common,
            "turn_id": "seed",
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"path": str(self.repo / "README.md")},
        })

        prompt_output = self.hook({
            **common,
            "turn_id": "branch",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "插一句：检查一下运行服务为什么失败？",
        })
        stop_output = self.hook({
            **common,
            "turn_id": "branch",
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "已完成检查并验证通过。",
        })

        self.assertIn("bounded temporary branch", prompt_output)
        self.assertEqual(json.loads(stop_output), {})
        state = json.loads((self.repo / ".agent/runtime/goal_return/state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["sessions"]["nested-goal-session"]["interrupts"][-1]["state"], "CLOSED")

        unrelated = self.hook({
            "session_id": "different-session",
            "cwd": str(self.parent),
            "turn_id": "other",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "插一句：这不属于已绑定任务。",
        })
        self.assertEqual(unrelated, "")

    def test_installed_inactive_project_allows_normal_edit(self) -> None:
        event = {
            "cwd": str(self.repo),
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"patch": "*** Begin Patch\n*** Add File: src/small_fix.py\n+x = 1\n*** End Patch"},
        }

        self.assertEqual(self.hook(event), "")
        observer = json.loads((self.repo / ".agent" / "runtime" / "observer_state.json").read_text(encoding="utf-8"))
        self.assertEqual(observer["pre_events"], 1)
        self.assertIn("src/small_fix.py", observer["changed_path_candidates"])

    def test_expired_project_reuse_probe_reminds_once_only_for_detailed_goal(self) -> None:
        north_path = self.repo / ".agent/north_star_goal.json"
        north = json.loads(north_path.read_text(encoding="utf-8"))
        north.update({
            "confirmed": True,
            "goal": "Build a traceable packaging release workflow.",
            "goal_definition": {"quality": "STRUCTURED_DETAILED"},
        })
        north_path.write_text(json.dumps(north), encoding="utf-8")
        reuse_path = self.repo / ".agent/runtime/reuse_probe.json"
        reuse_path.write_text(json.dumps({
            "last_probe": {
                "status": "NO_CANDIDATES",
                "checked_at": "2000-01-01T00:00:00+00:00",
                "expires_at": "2000-01-02T00:00:00+00:00",
            }
        }), encoding="utf-8")
        event = {
            "cwd": str(self.repo),
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"patch": "*** Begin Patch\n*** Add File: src/feature.py\n+x = 1\n*** End Patch"},
        }

        first = self.hook(event)
        second = self.hook(event)

        self.assertIn("24-hour reuse refresh", first)
        self.assertEqual(second, "")

    def test_due_segment_reminder_is_injected_on_next_session_event(self) -> None:
        state_path = self.repo / ".agent/runtime/convergence_state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["segments"] = {
            "active": {
                "UI": {
                    "node_id": "UI",
                    "name": "Mobile UI",
                    "objective": "Complete the accepted mobile UI flow.",
                    "status": "ACTIVE",
                    "started_at": "2000-01-01T00:00:00+00:00",
                    "deadline_at": "2000-01-01T05:00:00+00:00",
                    "timebox_hours": 5,
                    "reminder_interval_hours": 2,
                    "next_reminder_at": "2000-01-01T02:00:00+00:00",
                    "reminder_count": 0,
                }
            },
            "completed": [],
            "last_reminder": None,
        }
        state_path.write_text(json.dumps(state), encoding="utf-8")
        event = {
            "cwd": str(self.repo),
            "hook_event_name": "SessionStart",
            "session_id": "deadline-session",
        }

        output = self.hook(event)

        self.assertIn("Goal segment checkpoint", output)
        self.assertIn("Mobile UI", output)
        persisted = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["segments"]["active"]["UI"]["reminder_count"], 1)

    def test_first_unambiguous_product_write_starts_segment_silently(self) -> None:
        north_path = self.repo / ".agent/north_star_goal.json"
        north = json.loads(north_path.read_text(encoding="utf-8"))
        north.update({
            "confirmed": True,
            "goal": "Deliver the accepted mobile UI flow.",
            "goal_definition": {
                "quality": "STRUCTURED_DETAILED",
                "process": {"nodes": [{
                    "node_id": "UI",
                    "name": "Mobile UI",
                    "objective": "Complete the accepted mobile UI flow.",
                    "dependencies": [],
                    "inputs": ["UI brief"],
                    "outputs": ["Working UI"],
                    "exit_criteria": ["UI validation passes"],
                    "execution_mode": "SERIAL",
                    "contribution_to_goal": "Provides the user-visible product flow.",
                    "timebox_hours": 5,
                    "reminder_interval_hours": 2,
                }]},
            },
        })
        north_path.write_text(json.dumps(north), encoding="utf-8")

        output = self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"patch": "*** Begin Patch\n*** Add File: src/mobile_ui.py\n+x = 1\n*** End Patch"},
        })

        self.assertEqual(output, "")
        state = json.loads((self.repo / ".agent/runtime/convergence_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["segments"]["active"]["UI"]["started_by"], "BACKGROUND_HIGH_CONFIDENCE")
        self.assertTrue(state["segments"]["active"]["UI"]["deadline_at"])

    def test_stop_warns_when_completion_claim_follows_unverified_product_write(self) -> None:
        self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "PreToolUse",
            "tool_use_id": "completion-write",
            "tool_name": "apply_patch",
            "tool_input": {
                "patch": "*** Begin Patch\n*** Add File: src/completed.py\n+x = 1\n*** End Patch",
            },
        })

        output = self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "这个功能已经完成。",
        })

        context = json.loads(output)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Verification required before completion", context)
        self.assertIn("src/completed.py", context)

    def test_validation_start_without_post_result_remains_unverified(self) -> None:
        self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "PreToolUse",
            "tool_use_id": "unobserved-write",
            "tool_name": "apply_patch",
            "tool_input": {
                "patch": "*** Begin Patch\n*** Add File: src/unobserved.py\n+x = 1\n*** End Patch",
            },
        })
        self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "PreToolUse",
            "tool_use_id": "unobserved-validation",
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -m unittest -q verification.tests.test_small"},
        })

        output = self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "修复完成。",
        })

        context = json.loads(output)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("started after the product write", context)
        self.assertIn("successful result was not observed", context)

    def test_successful_validation_after_write_clears_completion_reminder(self) -> None:
        self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "PreToolUse",
            "tool_use_id": "verified-write",
            "tool_name": "apply_patch",
            "tool_input": {
                "patch": "*** Begin Patch\n*** Add File: src/verified.py\n+x = 1\n*** End Patch",
            },
        })
        validation = {
            "cwd": str(self.repo),
            "tool_use_id": "verified-validation",
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -m py_compile src/verified.py"},
        }
        self.hook({**validation, "hook_event_name": "PreToolUse"})
        self.hook({
            **validation,
            "hook_event_name": "PostToolUse",
            "tool_response": {"exit_code": 0},
        })

        output = self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "实现完成并验证通过。",
        })

        self.assertEqual(json.loads(output), {})
        observer = json.loads((self.repo / ".agent/runtime/observer_state.json").read_text(encoding="utf-8"))
        self.assertFalse(observer["verification_debt"]["pending"])
        self.assertTrue(observer["verification_debt"]["validation_result_observed"])

    def test_ordinary_stop_and_generated_state_writes_remain_silent(self) -> None:
        self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "PreToolUse",
            "tool_use_id": "generated-write",
            "tool_name": "apply_patch",
            "tool_input": {
                "patch": "*** Begin Patch\n*** Update File: .agent/runtime/local.json\n+{}\n*** End Patch",
            },
        })
        generated_stop = self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "状态记录已完成。",
        })
        self.assertEqual(json.loads(generated_stop), {})

        self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "PreToolUse",
            "tool_use_id": "unfinished-write",
            "tool_name": "apply_patch",
            "tool_input": {
                "patch": "*** Begin Patch\n*** Add File: src/in_progress.py\n+x = 1\n*** End Patch",
            },
        })
        unfinished_stop = self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "仍在进行，尚未验证。",
        })
        self.assertEqual(json.loads(unfinished_stop), {})

    def test_north_star_completion_claim_requires_current_final_regression_certificate(self) -> None:
        self.cli("goal-set", "--text", "Deliver a verified local product.")

        output = self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "整个项目已完成。",
        })

        context = json.loads(output)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("CERTIFIED_COMPLETE", context)
        self.assertIn("certify-goal", context)

    def test_certified_north_star_completion_claim_is_silent_without_new_writes(self) -> None:
        self.cli("goal-set", "--text", "Deliver a verified local product.")
        state_path = self.repo / ".agent/runtime/convergence_state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["goal_completion"] = {"status": "CERTIFIED_COMPLETE"}
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        output = self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "北极星目标已完成。",
        })

        self.assertEqual(json.loads(output), {})

    def test_stop_hook_selects_concrete_path_when_local_prerequisite_is_treated_as_global(self) -> None:
        north = self.repo / ".agent/north_star_goal.json"
        payload = json.loads(north.read_text(encoding="utf-8"))
        payload.update({
            "confirmed": True,
            "goal": "Deliver the complete Personal AI OS product.",
            "goal_definition": {
                "quality": "STRUCTURED_DETAILED",
                "success_criteria": ["All product paths reach their acceptance evidence."],
                "process": {"nodes": [
                    {"node_id": "N1", "name": "iPhone path"},
                    {"node_id": "N2", "name": "Watch path"},
                    {"node_id": "N3", "name": "RayNeo path"},
                    {"node_id": "N4", "name": "Shared session"},
                ]},
                "final_acceptance": [{"criterion": "Run the complete field demo three times."}],
            },
        })
        north.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.cli("init")

        output = self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "已进入安全暂停。等待你物理打开 Wi-Fi 后才能继续。",
        })

        result = json.loads(output)
        self.assertEqual(result["decision"], "block")
        self.assertIn("DEFERRED_LOCAL", result["reason"])
        self.assertIn("iPhone path", result["reason"])
        self.assertIn("use tools now", result["reason"])
        state = json.loads((self.repo / ".agent/runtime/convergence_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["recovery"]["blocker_scope_review"]["status"], "CONTINUE_INDEPENDENT_PATH")

    def test_stop_hook_retries_planning_only_follow_up_once_without_looping(self) -> None:
        north = self.repo / ".agent/north_star_goal.json"
        payload = json.loads(north.read_text(encoding="utf-8"))
        payload.update({
            "confirmed": True,
            "goal": "Deliver a verified local product.",
            "goal_definition": {
                "quality": "STRUCTURED_DETAILED",
                "success_criteria": ["The product regression passes."],
                "process": {"nodes": [
                    {"node_id": "N1", "name": "Device path", "objective": "Run the physical device path."},
                    {"node_id": "N2", "name": "Offline validation", "objective": "Run independent offline checks."},
                ]},
            },
        })
        north.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.cli("init")

        first = self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "Waiting for the user to connect the physical device before continuing.",
        })
        self.assertEqual(json.loads(first)["decision"], "block")

        retry = self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "Stop",
            "stop_hook_active": True,
            "last_assistant_message": "I still need the user to connect the physical device before continuing.",
        })
        self.assertEqual(json.loads(retry)["decision"], "block")
        self.assertIn("Do not return another plan", json.loads(retry)["reason"])

        exhausted = self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "Stop",
            "stop_hook_active": True,
            "last_assistant_message": "I still need the user to connect the physical device before continuing.",
        })
        self.assertEqual(json.loads(exhausted), {})

    def test_large_read_is_recorded_locally_without_main_thread_injection(self) -> None:
        target = self.repo / "docs" / "large-history.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("history\n", encoding="utf-8")

        output = self.hook({
            "cwd": str(self.repo),
            "session_id": "large-read-session",
            "turn_id": "large-read-turn",
            "hook_event_name": "PostToolUse",
            "tool_use_id": "large-read-output",
            "tool_name": "read_file",
            "tool_input": {"path": str(target)},
            "tool_response": {"content": "x" * (600 * 1024)},
        })

        self.assertEqual(output, "")
        state = json.loads((self.repo / ".agent/runtime/context_continuity.json").read_text(encoding="utf-8"))
        self.assertTrue(state["checkpoint_due"])
        self.assertTrue((self.repo / ".agent/runtime/context/index.json").is_file())

    def test_compaction_session_start_points_to_local_capsule_without_source_text(self) -> None:
        target = self.repo / "docs" / "large-history.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("private source body\n", encoding="utf-8")
        self.hook({
            "cwd": str(self.repo),
            "session_id": "compact-session",
            "hook_event_name": "PostToolUse",
            "tool_name": "read_file",
            "tool_input": {"path": str(target)},
            "tool_response": {"content": "x" * (600 * 1024)},
        })
        self.hook({
            "cwd": str(self.repo),
            "session_id": "compact-session",
            "hook_event_name": "PreCompact",
            "trigger": "auto",
        })

        output = self.hook({
            "cwd": str(self.repo),
            "session_id": "compact-session",
            "hook_event_name": "SessionStart",
            "source": "compact",
        })

        self.assertIn("context/index.json", output)
        self.assertIn("do not blindly reread", output)
        self.assertNotIn("private source body", output)

    def test_subagent_start_guidance_requires_partitionable_read_only_assignment(self) -> None:
        runtime = self.repo / ".agent" / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / "context_continuity.json").write_text(json.dumps({
            "schema_version": 2,
            "subagent_recommended": True,
            "checkpoint_due": True,
            "partitionable_directories": ["archive_0", "archive_1"],
        }) + "\n", encoding="utf-8")

        read_output = self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "SubagentStart",
            "task": "Inspect and summarize archive_0 as a read-only evidence slice.",
        })
        implementation_output = self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "SubagentStart",
            "task": "Implement and edit the API.",
        })

        self.assertIn("stay read-only", read_output)
        self.assertEqual(implementation_output, "")

    def test_inactive_project_hook_blocks_only_deterministic_boundaries(self) -> None:
        cases = (
            (
                "apply_patch",
                {"patch": "*** Begin Patch\n*** Update File: .agent/current_ticket.json\n+{}\n*** End Patch"},
            ),
            ("Bash", {"command": "git reset --hard HEAD~1"}),
        )
        for tool_name, tool_input in cases:
            with self.subTest(tool_name=tool_name):
                output = self.hook({
                    "cwd": str(self.repo),
                    "hook_event_name": "PreToolUse",
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                })
                self.assertIn('"permissionDecision": "deny"', output)

    def test_common_deterministic_command_variants_protect_control_state(self) -> None:
        commands = [
            "git -C . reset --hard HEAD",
            "/usr/bin/git clean -fd",
            "env git -C . reset --hard HEAD",
            "python3 -c \"open('.agent/current_ticket.json', 'w').write('{}')\"",
            "sed -i '.bak' .agent/current_ticket.json",
            "printf '{}\\n' | tee .agent/current_ticket.json",
        ]
        for command in commands:
            with self.subTest(command=command):
                output = self.hook({
                    "cwd": str(self.repo),
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                })
                self.assertIn('"permissionDecision": "deny"', output)

    def test_exec_command_cmd_field_uses_same_boundary_rules(self) -> None:
        denied = self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "PreToolUse",
            "tool_name": "exec_command",
            "tool_input": {"cmd": "git -C . reset --hard HEAD"},
        })
        allowed = self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "PreToolUse",
            "tool_name": "exec_command",
            "tool_input": {"cmd": "git -C . status --short"},
        })

        self.assertIn('"permissionDecision": "deny"', denied)
        self.assertEqual(allowed, "")

    def test_read_only_command_variants_remain_allowed(self) -> None:
        commands = [
            "git -C . status --short",
            "python3 -c \"open('.agent/current_ticket.json', 'r').read()\"",
            "sed -n '1,20p' .agent/current_ticket.json",
        ]
        for command in commands:
            with self.subTest(command=command):
                output = self.hook({
                    "cwd": str(self.repo),
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                })
                self.assertEqual(output, "")

    def test_lightweight_observer_accepts_exit_code_failure_fields(self) -> None:
        outputs = []
        for index in range(3):
            outputs.append(self.hook({
                "cwd": str(self.repo),
                "hook_event_name": "PostToolUse",
                "tool_use_id": f"exit-code-{index}",
                "tool_name": "Bash",
                "tool_input": {"command": "python3 deterministic_failure.py"},
                "tool_response": {"exit_code": 1},
            }))

        state = json.loads((self.repo / ".agent/runtime/observer_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["failed_events"], 3)
        self.assertIn("Three consecutive tool failures", outputs[-1])

    def test_lightweight_hook_enforces_only_repeated_project_authored_deviation(self) -> None:
        north_path = self.repo / ".agent" / "north_star_goal.json"
        north = json.loads(north_path.read_text(encoding="utf-8"))
        north.update({
            "confirmed": True,
            "goal": "Build a private internal Agent Registry.",
            "anti_goals": ["provider marketplace"],
        })
        north_path.write_text(json.dumps(north, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        outputs = []
        for index in range(3):
            outputs.append(self.hook({
                "cwd": str(self.repo),
                "hook_event_name": "PreToolUse",
                "tool_use_id": f"light-deviation-{index}",
                "tool_name": "apply_patch",
                "tool_input": {
                    "patch": (
                        "*** Begin Patch\n"
                        f"*** Add File: src/providers/marketplace/{index}.py\n"
                        "+provider marketplace\n"
                        "*** End Patch"
                    ),
                },
            }))

        self.assertIn("reminder", outputs[0])
        self.assertNotIn("permissionDecision", outputs[0])
        self.assertIn('"permissionDecision": "deny"', outputs[2])
        unrelated = self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "PreToolUse",
            "tool_use_id": "light-aligned-write",
            "tool_name": "apply_patch",
            "tool_input": {
                "patch": "*** Begin Patch\n*** Add File: src/core/registry.py\n+private registry\n*** End Patch",
            },
        })
        self.assertEqual(unrelated, "")

    def test_lightweight_hook_uses_sparse_judge_before_semantic_rail(self) -> None:
        fake = self.repo / "fake_codex.py"
        log = self.repo / "fake_judge_log.jsonl"
        fake.write_text(
            "import json, os, pathlib, sys\n"
            "args=sys.argv[1:]\n"
            "sys.stdin.read()\n"
            "pathlib.Path(args[args.index('-o')+1]).write_text(json.dumps({"
            "'verdict':'ALLOW_SCOPED_ACTION','confidence':'high',"
            "'rationale':'The scoped action needs more evidence before a rail.',"
            "'recommended_action':'continue_scoped_action','evidence_needed':[]}), encoding='utf-8')\n"
            "with pathlib.Path(os.environ['FAKE_JUDGE_LOG']).open('a', encoding='utf-8') as h: h.write('called\\n')\n",
            encoding="utf-8",
        )
        north_path = self.repo / ".agent" / "north_star_goal.json"
        north = json.loads(north_path.read_text(encoding="utf-8"))
        north.update({
            "confirmed": True,
            "goal": "Build a private internal Agent Registry.",
            "anti_goals": ["provider marketplace"],
        })
        north_path.write_text(json.dumps(north, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        old_cmd = os.environ.get("GOAL_SUPERVISOR_JUDGE_CMD")
        try:
            os.environ.pop("GOAL_SUPERVISOR_DISABLE_LLM_JUDGE", None)
            os.environ["GOAL_SUPERVISOR_JUDGE_CMD"] = shlex.join([sys.executable, str(fake)])
            os.environ["FAKE_JUDGE_LOG"] = str(log)
            output = ""
            for index in range(3):
                output = self.hook({
                    "cwd": str(self.repo),
                    "hook_event_name": "PreToolUse",
                    "tool_use_id": f"sparse-judge-{index}",
                    "tool_name": "apply_patch",
                    "tool_input": {
                        "patch": (
                            "*** Begin Patch\n"
                            f"*** Add File: src/providers/marketplace/{index}.py\n"
                            "+provider marketplace\n"
                            "*** End Patch"
                        ),
                    },
                })
        finally:
            os.environ["GOAL_SUPERVISOR_DISABLE_LLM_JUDGE"] = "1"
            os.environ.pop("FAKE_JUDGE_LOG", None)
            if old_cmd is None:
                os.environ.pop("GOAL_SUPERVISOR_JUDGE_CMD", None)
            else:
                os.environ["GOAL_SUPERVISOR_JUDGE_CMD"] = old_cmd

        self.assertNotIn("permissionDecision", output)
        self.assertIn("LLM Judge did not confirm", output)
        self.assertTrue(log.is_file(), output)
        self.assertEqual(log.read_text(encoding="utf-8").splitlines(), ["called"])

    def test_observer_recovers_events_queued_during_lock_contention(self) -> None:
        runtime = self.repo / ".agent" / "runtime"
        lock = runtime / "observer_state.lock"
        lock.write_text(json.dumps({
            "pid": os.getpid(),
            "created_at": time.time(),
            "nonce": "verification-lock",
        }), encoding="utf-8")

        def emit(index: int) -> str:
            return self.hook({
                "cwd": str(self.repo),
                "hook_event_name": "PostToolUse",
                "tool_use_id": f"contended-{index}",
                "tool_name": "apply_patch",
                "tool_input": {"patch": f"*** Begin Patch\n*** Add File: src/batch/{index}.py\n+x = {index}\n*** End Patch"},
                "tool_response": {"exit_code": 0},
            })

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
                outputs = list(pool.map(emit, range(32)))
        finally:
            lock.unlink(missing_ok=True)
        self.assertEqual(outputs, [""] * 32)
        self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "PostToolUse",
            "tool_use_id": "fallback-flush",
            "tool_name": "Read",
            "tool_input": {"path": "README.md"},
            "tool_response": {"exit_code": 0},
        })

        state = json.loads((runtime / "observer_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["post_events"], 33)
        self.assertEqual(state["fallback_events_recovered"], 32)
        self.assertFalse((runtime / "observer_pending").exists())

    def test_deviation_fallback_activates_future_rail_without_blocking_unrelated_recovery_event(self) -> None:
        north_path = self.repo / ".agent" / "north_star_goal.json"
        north = json.loads(north_path.read_text(encoding="utf-8"))
        north.update({
            "confirmed": True,
            "goal": "Build a private internal Agent Registry.",
            "anti_goals": ["provider marketplace"],
        })
        north_path.write_text(json.dumps(north, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        runtime = self.repo / ".agent" / "runtime"
        lock = runtime / "observer_state.lock"
        lock.write_text(json.dumps({
            "pid": os.getpid(),
            "created_at": time.time(),
            "nonce": "semantic-fallback-lock",
        }), encoding="utf-8")

        def emit(index: int) -> str:
            return self.hook({
                "cwd": str(self.repo),
                "hook_event_name": "PreToolUse",
                "tool_use_id": f"semantic-fallback-{index}",
                "tool_name": "apply_patch",
                "tool_input": {
                    "patch": (
                        "*** Begin Patch\n"
                        f"*** Add File: src/providers/marketplace/{index}.py\n"
                        "+provider marketplace\n"
                        "*** End Patch"
                    ),
                },
            })

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                self.assertEqual(list(pool.map(emit, range(3))), ["", "", ""])
        finally:
            lock.unlink(missing_ok=True)

        recovery = self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "PreToolUse",
            "tool_use_id": "semantic-fallback-recovery",
            "tool_name": "apply_patch",
            "tool_input": {
                "patch": "*** Begin Patch\n*** Add File: src/core/registry.py\n+private registry\n*** End Patch",
            },
        })
        self.assertNotIn("permissionDecision", recovery)

        matching = self.hook({
            "cwd": str(self.repo),
            "hook_event_name": "PreToolUse",
            "tool_use_id": "semantic-fallback-next-match",
            "tool_name": "apply_patch",
            "tool_input": {
                "patch": "*** Begin Patch\n*** Add File: src/providers/marketplace/next.py\n+provider marketplace\n*** End Patch",
            },
        })
        self.assertIn('"permissionDecision": "deny"', matching)

    def test_direct_active_project_pretool_is_enforced_by_plugin_fallback(self) -> None:
        self.activate_video()
        self.complete_company_runtime()
        event = {
            "cwd": str(self.repo),
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Add File: src/ui/forbidden.ts\n+x\n*** End Patch"},
        }

        output = self.hook(event)

        self.assertIn('"permissionDecision": "deny"', output)

    def test_official_apply_patch_command_allows_allowed_path(self) -> None:
        self.activate_video()
        self.complete_company_runtime()
        event = {
            "cwd": str(self.repo),
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Add File: src/video/mock/generator.ts\n+x\n*** End Patch"},
        }

        self.assertEqual(self.hook(event), "")

    def test_allowed_product_edit_only_advises_about_optional_company_roles(self) -> None:
        self.activate_video_with_company()
        event = {
            "cwd": str(self.repo),
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Add File: src/video/mock/generator.ts\n+x\n*** End Patch"},
        }

        output = self.hook(event)

        self.assertNotIn('"permissionDecision": "deny"', output)
        self.assertIn("Optional specialist perspectives", output)

    def test_bash_delete_redirection_composite_and_inline_writes_are_denied(self) -> None:
        self.activate_video()
        commands = [
            "rm -f src/ui/forbidden.ts",
            "echo x>src/ui/forbidden.ts",
            "python3 .agent/goal_compass.py status && touch src/ui/forbidden.ts",
            "python3 -c \"from pathlib import Path; Path('src/ui/forbidden.ts').write_text('x')\"",
        ]
        for command in commands:
            with self.subTest(command=command):
                event = {
                    "cwd": str(self.repo),
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                }
                self.assertIn('"permissionDecision": "deny"', self.hook(event))

    def test_repo_hook_finds_compass_from_nested_session_directory(self) -> None:
        self.activate_video()
        nested = self.repo / "src" / "nested"
        nested.mkdir(parents=True)
        config = json.loads((self.repo / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        handler = config["hooks"]["PreToolUse"][0]["hooks"][0]
        command = handler["commandWindows"] if os.name == "nt" else handler["command"]
        event = {
            "cwd": str(nested),
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Add File: src/ui/forbidden.ts\n+x\n*** End Patch"},
        }

        if os.name == "nt":
            proc = run_cmd(command, cwd=nested, input_text=json.dumps(event), check=True, shell=True)
        else:
            proc = run_cmd(["/bin/sh", "-c", command], cwd=nested, input_text=json.dumps(event), check=True)

        self.assertIn('"permissionDecision": "deny"', proc.stdout)

    def test_repo_hook_uses_lightweight_observer_without_active_ticket(self) -> None:
        nested = self.repo / "src" / "nested"
        nested.mkdir(parents=True)
        config = json.loads((self.repo / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        handler = config["hooks"]["PreToolUse"][0]["hooks"][0]
        command = handler["commandWindows"] if os.name == "nt" else handler["command"]
        event = {
            "cwd": str(nested),
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"patch": "*** Begin Patch\n*** Add File: src/local_hook_fix.py\n+x = 1\n*** End Patch"},
        }

        if os.name == "nt":
            proc = run_cmd(command, cwd=nested, input_text=json.dumps(event), check=True, shell=True)
        else:
            proc = run_cmd(["/bin/sh", "-c", command], cwd=nested, input_text=json.dumps(event), check=True)

        self.assertEqual(proc.stdout, "")
        observer = json.loads((self.repo / ".agent" / "runtime" / "observer_state.json").read_text(encoding="utf-8"))
        self.assertEqual(observer["pre_events"], 1)
        self.assertIn("src/local_hook_fix.py", observer["changed_path_candidates"])

    def test_direct_init_merges_existing_project_hooks(self) -> None:
        custom = {
            "hooks": {
                "SessionStart": [{"matcher": ".*", "hooks": [{"type": "command", "command": "echo session"}]}],
                "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo custom"}]}],
            }
        }
        hooks = self.repo / ".codex" / "hooks.json"
        hooks.write_text(json.dumps(custom, indent=2) + "\n", encoding="utf-8")

        self.cli("init")
        merged = json.loads(hooks.read_text(encoding="utf-8"))

        self.assertIn("SessionStart", merged["hooks"])
        self.assertIn("echo custom", json.dumps(merged))
        for event in ("PreToolUse", "PostToolUse"):
            handlers = [handler for group in merged["hooks"][event] for handler in group.get("hooks", [])]
            compass = [handler for handler in handlers if "project_hook.py" in handler.get("command", "")]
            self.assertEqual(len(compass), 1)

    def test_dispatcher_falls_back_for_older_project_install(self) -> None:
        (self.repo / ".agent" / "goal_compass_runtime" / "project_hook.py").unlink()
        event = {
            "cwd": str(self.repo),
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"patch": "*** Begin Patch\n*** Add File: src/legacy_install_fix.py\n+x = 1\n*** End Patch"},
        }

        self.assertEqual(self.hook(event), "")

    def test_dispatcher_selects_explicit_target_when_two_projects_are_active(self) -> None:
        for repo in (self.repo, self.parent / "nested-b"):
            if repo != self.repo:
                copy_goal_compass_runtime(repo)
                self.cli("init", cwd=repo)
                install_product_test_fixtures(repo)
            self.activate_video(cwd=repo)
        event = {
            "cwd": str(self.parent),
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "cd nested-b && touch src/ui/forbidden.ts"},
        }

        output = self.hook(event)

        self.assertIn('"permissionDecision": "deny"', output)

    def test_dispatcher_fails_open_when_project_hook_is_broken(self) -> None:
        self.activate_video()
        (self.repo / ".agent" / "goal_compass.py").write_text("this is invalid python !!!\n", encoding="utf-8")
        event = {
            "cwd": str(self.repo),
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Add File: src/video/mock/ok.ts\n+x\n*** End Patch"},
        }

        output = self.hook(event)

        self.assertNotIn('"permissionDecision": "deny"', output)
        self.assertIn("execution continues", output)

    def test_nested_draft_preparation_can_edit_pending_ticket(self) -> None:
        target = self.repo / ".agent" / "tickets" / "pending" / "DRAFT.json"
        event = {
            "cwd": str(self.parent),
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"patch": f"*** Begin Patch\n*** Add File: {target}\n+{{}}\n*** End Patch"},
        }

        self.assertEqual(self.hook(event), "")

    def test_plugin_hook_is_silent_without_goal_compass_project(self) -> None:
        other = self.parent / "plain"
        other.mkdir()
        event = {
            "cwd": str(other),
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"patch": "*** Begin Patch\n*** Add File: note.txt\n+x\n*** End Patch"},
        }

        self.assertEqual(self.hook(event), "")
