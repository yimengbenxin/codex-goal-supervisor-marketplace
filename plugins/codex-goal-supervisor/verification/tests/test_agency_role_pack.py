from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

try:
    from .helpers import INSTALLER, PLUGIN_ROOT, run_cmd
except ImportError:
    from helpers import INSTALLER, PLUGIN_ROOT, run_cmd


TOOL = PLUGIN_ROOT / "scripts" / "agency_role_pack.py"
PACK = PLUGIN_ROOT / "assets" / "role-packs" / "agency-agents"
if str(TOOL.parent) not in sys.path:
    sys.path.insert(0, str(TOOL.parent))


def load_tool_module():
    spec = importlib.util.spec_from_file_location("agency_role_pack_test", TOOL)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {TOOL}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ROLE_TOOL = load_tool_module()


class AgencyRolePackTests(unittest.TestCase):
    def run_tool(self, *args: str, check: bool = True):
        return run_cmd([sys.executable, str(TOOL), *args], cwd=PLUGIN_ROOT, timeout=12, check=check)

    def test_manifest_keeps_pinned_source_license_and_full_catalog(self) -> None:
        manifest = json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["pack_id"], "agency-agents")
        self.assertEqual(manifest["role_count"], 270)
        self.assertEqual(manifest["division_count"], 17)
        self.assertEqual(manifest["raw_prompt_policy"], "byte_for_byte_upstream_snapshot")
        self.assertEqual(manifest["selection_policy"], "optional_main_thread_choice")
        self.assertEqual(manifest["authority"], "expert_reference_not_final_decision_maker")
        self.assertEqual(len(manifest["source"]["commit"]), 40)
        self.assertEqual(manifest["source"]["license"], "MIT")
        self.assertTrue((PACK / "LICENSE").is_file())

    def test_verify_checks_every_prompt_hash(self) -> None:
        result = self.run_tool("verify")
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["roles"], 270)
        self.assertEqual(payload["errors"], [])

    def test_show_returns_exact_untruncated_upstream_prompt(self) -> None:
        role = "specialized/supply-chain-strategist"
        source = PACK / "roles" / f"{role}.md"
        result = self.run_tool("show", "--role", role)
        self.assertEqual(result.stdout, source.read_text(encoding="utf-8"))
        self.assertEqual(
            hashlib.sha256(result.stdout.encode("utf-8")).hexdigest(),
            hashlib.sha256(source.read_bytes()).hexdigest(),
        )
        self.assertIn("Personality", result.stdout)
        self.assertIn("Default requirement", result.stdout)

    def test_search_returns_candidates_without_selecting_a_decision_authority(self) -> None:
        result = self.run_tool(
            "search", "--query", "China manufacturing supplier procurement supply chain", "--limit", "5", "--json"
        )
        rows = json.loads(result.stdout)
        self.assertEqual(rows[0]["id"], "specialized/supply-chain-strategist")
        self.assertNotIn("selected", rows[0])
        self.assertNotIn("decision", rows[0])

    def test_list_can_filter_one_division(self) -> None:
        result = self.run_tool("list", "--division", "healthcare", "--json")
        rows = json.loads(result.stdout)
        self.assertGreaterEqual(len(rows), 3)
        self.assertTrue(all(row["division"] == "healthcare" for row in rows))

    def test_installer_does_not_copy_role_pack_into_user_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "project"
            repo.mkdir()
            (repo / "README.md").write_text("User project\n", encoding="utf-8")
            run_cmd(
                [sys.executable, str(INSTALLER), str(repo), "--force"],
                cwd=PLUGIN_ROOT,
                timeout=20,
                check=True,
            )
            self.assertFalse((repo / ".agent" / "role-packs").exists())
            self.assertFalse(any(path.name == "agency-agents" for path in repo.rglob("agency-agents")))
            self.assertEqual((repo / "README.md").read_text(encoding="utf-8"), "User project\n")

    def test_slim_marketplace_downloads_and_verifies_role_pack_on_explicit_use(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source" / "agency-agents"
            prompt = source / "roles" / "testing" / "fixture.md"
            prompt.parent.mkdir(parents=True)
            prompt.write_text("# Fixture role\n", encoding="utf-8")
            license_path = source / "LICENSE"
            license_path.write_text("MIT fixture\n", encoding="utf-8")
            commit = "a" * 40
            manifest = {
                "schema_version": 1,
                "asset_id": "agency-agents",
                "pack_id": "agency-agents",
                "display_name": "Fixture",
                "role_count": 1,
                "division_count": 1,
                "raw_prompt_policy": "byte_for_byte_upstream_snapshot",
                "selection_policy": "optional_main_thread_choice",
                "authority": "expert_reference_not_final_decision_maker",
                "source": {
                    "commit": commit,
                    "license_file": "LICENSE",
                    "license_sha256": hashlib.sha256(license_path.read_bytes()).hexdigest(),
                },
                "roles": [{
                    "id": "testing/fixture",
                    "division": "testing",
                    "name": "Fixture",
                    "prompt_file": "roles/testing/fixture.md",
                    "prompt_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
                }],
            }
            (source / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            archive = root / "agency-agents.zip"
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for path in sorted(source.rglob("*")):
                    if path.is_file():
                        bundle.write(path, Path("agency-agents") / path.relative_to(source))
            raw = archive.read_bytes()
            descriptor = root / "agency-agents.remote.json"
            descriptor.write_text(json.dumps({
                "schema_version": 1,
                "asset_id": "agency-agents",
                "pack_id": "agency-agents",
                "source_commit": commit,
                "archive_url": "https://updates.example/agency-agents.zip",
                "archive_root": "agency-agents",
                "archive_sha256": hashlib.sha256(raw).hexdigest(),
                "archive_bytes": len(raw),
                "max_files": 10,
                "max_uncompressed_bytes": 100_000,
            }), encoding="utf-8")

            class Response(io.BytesIO):
                def __init__(self, payload: bytes):
                    super().__init__(payload)
                    self.headers = {"Content-Length": str(len(payload))}

                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    self.close()

            env = {
                "GOAL_SUPERVISOR_ROLE_PACK_DESCRIPTOR": str(descriptor),
                "GOAL_SUPERVISOR_ROLE_PACK_CACHE": str(root / "cache"),
            }
            with (
                mock.patch.object(ROLE_TOOL, "DEFAULT_PACK", root / "not-bundled"),
                mock.patch.dict(os.environ, env, clear=False),
                mock.patch.object(
                    ROLE_TOOL.verified_asset.urllib.request,
                    "urlopen",
                    return_value=Response(raw),
                ) as download,
            ):
                resolved = ROLE_TOOL.resolve_pack(None)
                result = ROLE_TOOL.verify(resolved, ROLE_TOOL.load_manifest(resolved))
            self.assertTrue(result["ok"])
            self.assertEqual(resolved.parent, (root / "cache").resolve())
            self.assertEqual(download.call_count, 1)


if __name__ == "__main__":
    unittest.main()
