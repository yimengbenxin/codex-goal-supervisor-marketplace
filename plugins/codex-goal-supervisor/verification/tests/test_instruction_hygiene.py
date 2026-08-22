from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from .helpers import DEFAULT_TIMEOUT, PLUGIN_ROOT, copy_goal_compass_runtime, run_cmd, run_goal_compass
except ImportError:
    from helpers import DEFAULT_TIMEOUT, PLUGIN_ROOT, copy_goal_compass_runtime, run_cmd, run_goal_compass

from goal_compass_runtime.instruction_hygiene import correction_candidate


HOOK = PLUGIN_ROOT / "scripts" / "goal_hook.py"


class InstructionHygieneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.parent = Path(self.tmp.name)
        self.repo = self.parent / "ordinary-project"
        copy_goal_compass_runtime(self.repo, writable=True)
        init = run_goal_compass(["init"], cwd=self.repo)
        if init.returncode != 0:
            raise AssertionError(init.stderr)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def hook(self, event: dict) -> str:
        result = run_cmd(
            [sys.executable, str(HOOK)],
            cwd=self.parent,
            timeout=DEFAULT_TIMEOUT,
            check=True,
            input_text=json.dumps({"cwd": str(self.repo), **event}, ensure_ascii=False),
        )
        return result.stdout

    def test_correction_candidate_recognizes_explicit_and_rhetorical_subtraction(self) -> None:
        self.assertEqual(correction_candidate("不要再加东坡肉。"), {"target": "东坡肉", "confidence": "explicit"})
        self.assertEqual(correction_candidate("不需要加入东坡肉。"), {"target": "东坡肉", "confidence": "explicit"})
        self.assertEqual(correction_candidate("有必要加东坡肉吗？"), {"target": "东坡肉", "confidence": "candidate"})
        self.assertIsNone(correction_candidate("这个有必要吗？"))

    def test_general_profile_tombstones_temporary_request_across_compaction(self) -> None:
        common = {"session_id": "general-compaction"}
        self.assertEqual(self.hook({
            **common,
            "turn_id": "main",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "实现一个可运行的商品目录并完成端到端验证。",
        }), "")
        temporary = self.hook({
            **common,
            "turn_id": "temporary",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "插一句：解释一下当前端口的含义。",
        })
        self.assertIn("General Return Guard", temporary)
        self.hook({
            **common,
            "turn_id": "temporary",
            "hook_event_name": "Stop",
            "last_assistant_message": "端口用于本地服务监听。",
        })
        for revision in range(3):
            turn_id = f"compact-{revision}"
            self.hook({**common, "turn_id": turn_id, "hook_event_name": "PreCompact", "trigger": "auto"})
            self.hook({**common, "turn_id": turn_id, "hook_event_name": "PostCompact", "trigger": "auto"})
            recovered = self.hook({
                **common,
                "turn_id": turn_id,
                "hook_event_name": "SessionStart",
                "source": "compact",
            })

            self.assertIn("GENERAL CONTINUITY CHECKPOINT", recovered)
            self.assertIn("实现一个可运行的商品目录", recovered)
            self.assertIn("tombstoned", recovered)
            self.assertNotIn("解释一下当前端口", recovered)

    def test_resolved_rejected_variant_cannot_leak_into_later_completion(self) -> None:
        common = {"session_id": "correction-residue"}
        self.hook({
            **common,
            "turn_id": "main",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "实现番茄炒蛋菜谱并准备提交。",
        })
        correction = self.hook({
            **common,
            "turn_id": "correction",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "有必要加东坡肉吗？",
        })
        self.assertIn("Instruction Hygiene", correction)
        first_stop = json.loads(self.hook({
            **common,
            "turn_id": "correction",
            "hook_event_name": "Stop",
            "last_assistant_message": "你说得对，没有必要，已经去掉东坡肉。",
        }))
        self.assertNotEqual(first_stop.get("decision"), "block")

        repeated = json.loads(self.hook({
            **common,
            "turn_id": "later",
            "hook_event_name": "Stop",
            "last_assistant_message": "已提交番茄炒蛋（无东坡肉），并解释了为什么不需要东坡肉。",
        }))
        self.assertEqual(repeated["decision"], "block")
        self.assertIn("canonical positive result", repeated["reason"])

        clean = json.loads(self.hook({
            **common,
            "turn_id": "later-clean",
            "hook_event_name": "Stop",
            "last_assistant_message": "番茄炒蛋实现已提交并通过验证。",
        }))
        self.assertNotEqual(clean.get("decision"), "block")

    def test_general_profile_bounds_unmarked_short_side_question(self) -> None:
        common = {"session_id": "general-side-question"}
        self.hook({
            **common,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "完成本地商品目录服务并跑通端到端验证。",
        })
        bounded = self.hook({
            **common,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "这个预算是插件给的吗？",
        })
        self.hook({
            **common,
            "hook_event_name": "Stop",
            "last_assistant_message": "预算来自当前客户端，不是项目插件。",
        })
        self.hook({**common, "hook_event_name": "PreCompact", "trigger": "auto"})
        recovered = self.hook({**common, "hook_event_name": "SessionStart", "source": "compact"})

        self.assertIn("General Return Guard", bounded)
        self.assertIn("完成本地商品目录服务", recovered)
        self.assertNotIn("这个预算是插件给的吗", recovered)

    def test_direct_correction_without_turn_id_skips_only_its_own_response(self) -> None:
        common = {"session_id": "correction-without-turn-id"}
        self.hook({
            **common,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "不要加东坡肉。",
        })
        first_stop = json.loads(self.hook({
            **common,
            "hook_event_name": "Stop",
            "last_assistant_message": "已经去掉东坡肉，菜谱只保留番茄和鸡蛋。",
        }))
        repeated = json.loads(self.hook({
            **common,
            "hook_event_name": "Stop",
            "last_assistant_message": "已提交番茄炒蛋（无东坡肉）。",
        }))

        self.assertNotEqual(first_stop.get("decision"), "block")
        self.assertEqual(repeated.get("decision"), "block")

    def test_instruction_hygiene_state_redacts_secrets(self) -> None:
        secret = "sk-example-secret-1234567890"
        self.hook({
            "session_id": "secret-redaction",
            "hook_event_name": "UserPromptSubmit",
            "prompt": f"实现本地目录服务，api_key={secret}",
        })
        state_text = (self.repo / ".agent/runtime/instruction_hygiene.json").read_text(encoding="utf-8")

        self.assertNotIn(secret, state_text)
        self.assertIn("[redacted]", state_text)

    def test_resolved_variant_is_blocked_from_pr_title_without_blocking_product_code(self) -> None:
        common = {"session_id": "correction-publication"}
        self.hook({
            **common,
            "turn_id": "main",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "实现番茄炒蛋菜谱。",
        })
        self.hook({
            **common,
            "turn_id": "correction",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "不要加东坡肉。",
        })
        blocked = self.hook({
            **common,
            "turn_id": "publish",
            "hook_event_name": "PreToolUse",
            "tool_name": "exec_command",
            "tool_input": {"cmd": "gh pr create --title '番茄炒蛋（无东坡肉）'"},
        })
        allowed = self.hook({
            **common,
            "turn_id": "code",
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"patch": "*** Begin Patch\n*** Add File: src/recipe.py\n+def cook(): return 'tomato egg'\n*** End Patch"},
        })

        self.assertIn('"permissionDecision": "deny"', blocked)
        self.assertEqual(allowed, "")

    def test_resolved_variant_is_blocked_from_product_source_reintroduction(self) -> None:
        common = {"session_id": "correction-product-source"}
        self.hook({
            **common,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "不要加东坡肉。",
        })
        blocked = self.hook({
            **common,
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {
                "patch": (
                    "*** Begin Patch\n"
                    "*** Update File: src/menu_manifest.py\n"
                    "+OPTIONAL_DISH = '东坡肉'\n"
                    "*** End Patch"
                ),
            },
        })

        self.assertIn('"permissionDecision": "deny"', blocked)
        self.assertIn("product or publication artifact", blocked)

    def test_removing_resolved_variant_from_product_source_is_allowed(self) -> None:
        common = {"session_id": "correction-product-removal"}
        self.hook({
            **common,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "不要加东坡肉。",
        })
        allowed = self.hook({
            **common,
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {
                "patch": (
                    "*** Begin Patch\n"
                    "*** Update File: src/menu_manifest.py\n"
                    "-OPTIONAL_DISH = '东坡肉'\n"
                    "+OPTIONAL_DISH = None\n"
                    "*** End Patch"
                ),
            },
        })

        self.assertEqual(allowed, "")

    def test_explicit_reopen_allows_product_source_reintroduction(self) -> None:
        common = {"session_id": "correction-product-reopen"}
        self.hook({
            **common,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "不要加东坡肉。",
        })
        self.hook({
            **common,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "明确恢复：重新加入东坡肉。",
        })
        allowed = self.hook({
            **common,
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {
                "patch": (
                    "*** Begin Patch\n"
                    "*** Update File: src/menu_manifest.py\n"
                    "+OPTIONAL_DISH = '东坡肉'\n"
                    "*** End Patch"
                ),
            },
        })

        self.assertEqual(allowed, "")

    def test_resolved_variant_is_blocked_from_structured_pull_request_tool(self) -> None:
        common = {"session_id": "correction-structured-pr"}
        self.hook({
            **common,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "不要加东坡肉。",
        })
        blocked = self.hook({
            **common,
            "hook_event_name": "PreToolUse",
            "tool_name": "github_create_pull_request",
            "tool_input": {"title": "番茄炒蛋（无东坡肉）", "body": "解释为什么不需要东坡肉。"},
        })

        self.assertIn('"permissionDecision": "deny"', blocked)

    def test_resolved_variant_with_join_verb_is_blocked_from_markdown(self) -> None:
        common = {"session_id": "correction-join-verb"}
        self.hook({
            **common,
            "turn_id": "correction",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "不需要加入东坡肉。",
        })
        blocked = self.hook({
            **common,
            "turn_id": "publish",
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {
                "patch": "*** Begin Patch\n*** Add File: docs/RESULT.md\n+# 番茄炒蛋（无东坡肉）\n*** End Patch",
            },
        })

        self.assertIn('"permissionDecision": "deny"', blocked)

    def test_resolved_variant_can_be_explicitly_reopened(self) -> None:
        common = {"session_id": "correction-reopen"}
        self.hook({
            **common,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "不需要加入东坡肉。",
        })
        self.hook({
            **common,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "明确恢复：重新开放东坡肉作为候选。",
        })
        allowed = self.hook({
            **common,
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {
                "patch": "*** Begin Patch\n*** Add File: docs/REOPENED.md\n+# 东坡肉候选\n*** End Patch",
            },
        })

        self.assertEqual(allowed, "")

    def test_goal_profile_compaction_does_not_reinject_closed_temporary_text(self) -> None:
        goal = run_goal_compass(["goal-set", "--text", "Build a reliable local product."], cwd=self.repo)
        self.assertEqual(goal.returncode, 0, goal.stderr)
        common = {"session_id": "goal-compaction"}
        self.hook({
            **common,
            "turn_id": "temporary",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "插一句：反复检查东坡肉版本。",
        })
        self.hook({
            **common,
            "turn_id": "temporary",
            "hook_event_name": "Stop",
            "last_assistant_message": "已完成临时检查。",
        })
        self.hook({**common, "turn_id": "compact", "hook_event_name": "PreCompact", "trigger": "auto"})
        self.hook({**common, "turn_id": "compact", "hook_event_name": "PostCompact", "trigger": "auto"})
        recovered = self.hook({
            **common,
            "turn_id": "compact",
            "hook_event_name": "SessionStart",
            "source": "compact",
        })

        self.assertIn("Closed temporary branches", recovered)
        self.assertNotIn("反复检查东坡肉版本", recovered)


if __name__ == "__main__":
    unittest.main()
