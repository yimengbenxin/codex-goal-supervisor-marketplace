from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = PLUGIN_ROOT / "scripts" / "agent_assembler.py"
SHARE_SCRIPT = PLUGIN_ROOT / "scripts" / "share_agent_assembly_experience.py"


def run(args: list[str], cwd: Path, *, check: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"command failed: {result.stdout}\n{result.stderr}")
    return result


class AgentAssemblerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="agent-assembler-test-")
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "agent_app.py").write_text(
            "import sys\nprint('agent:' + (sys.argv[1] if len(sys.argv) > 1 else 'ready'))\n",
            encoding="utf-8",
        )
        self.source = self.root / "community-skill"
        self.source.mkdir()
        (self.source / "SKILL.md").write_text("---\nname: useful-skill\n---\nUseful.\n", encoding="utf-8")
        (self.source / "LICENSE").write_text("MIT fixture\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=self.source, check=True, timeout=5)
        subprocess.run(["git", "add", "."], cwd=self.source, check=True, timeout=5)
        subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"],
            cwd=self.source,
            check=True,
            timeout=5,
        )
        self.revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.source, check=True, capture_output=True, text=True, timeout=5
        ).stdout.strip()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @property
    def blueprint_path(self) -> Path:
        return self.project / ".agent/agent-assembly/agent-blueprint.json"

    def init_blueprint(self) -> dict:
        result = run(
            [
                "init", "--project", str(self.project), "--name", "fixture-agent",
                "--goal", "Expose the already working fixture as a portable agent.",
                "--runtime", "standalone-python",
            ],
            self.root,
            check=True,
        )
        self.assertEqual(json.loads(result.stdout)["status"], "DRAFT")
        return json.loads(self.blueprint_path.read_text(encoding="utf-8"))

    def complete_blueprint(self) -> dict:
        value = self.init_blueprint()
        value["agent"]["entrypoints"] = [{"id": "cli", "command": ["{python}", "agent_app.py", "hello"]}]
        value["agent"]["inputs"] = [{"name": "message", "type": "string", "required": False}]
        value["agent"]["outputs"] = [{"name": "stdout", "type": "string", "consumer": "caller"}]
        value["reuse_research"] = {
            "status": "completed",
            "decision_summary": "Use one fixture Skill because it supplies the missing reusable instruction.",
            "sources_checked": [str(self.source)],
        }
        value["capabilities"] = [{
            "id": "useful-skill",
            "purpose": "Provide the reusable fixture instruction.",
            "source": {"kind": "git", "location": str(self.source), "ref": self.revision},
            "distribution": "vendor",
            "license_disposition": "compatible",
            "verification_ids": ["smoke"],
        }]
        value["acceptance"] = [{
            "id": "smoke",
            "command": ["{python}", "agent_app.py", "hello"],
            "cwd": ".",
            "timeout_sec": 10,
        }]
        value["package"]["include_paths"] = ["agent_app.py"]
        self.blueprint_path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return value

    def test_init_is_draft_and_does_not_bundle_third_party_plugins(self) -> None:
        value = self.init_blueprint()
        self.assertEqual(value["capabilities"], [])
        self.assertFalse((self.project / "plugins").exists())
        result = run(["validate", "--project", str(self.project)], self.root)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "INVALID")
        self.assertIn("reuse_research.status must be completed before assembly", payload["errors"])

    def test_full_fetch_verify_lock_and_package_flow(self) -> None:
        self.complete_blueprint()
        validate = run(["validate", "--project", str(self.project)], self.root, check=True)
        self.assertEqual(json.loads(validate.stdout)["status"], "VALID")

        fetched = run(
            ["fetch", "--project", str(self.project), "--capability", "useful-skill"],
            self.root,
            check=True,
        )
        fetched_payload = json.loads(fetched.stdout)
        self.assertEqual(fetched_payload["status"], "FETCHED_UNVERIFIED")
        self.assertEqual(fetched_payload["resolved_revision"], self.revision)
        self.assertEqual(fetched_payload["license_files"], ["LICENSE"])

        before_verify = run(["lock", "--project", str(self.project)], self.root)
        self.assertNotEqual(before_verify.returncode, 0)
        self.assertIn("acceptance has not been run", before_verify.stdout)

        verified = run(["verify", "--project", str(self.project)], self.root, check=True)
        self.assertEqual(json.loads(verified.stdout)["status"], "VERIFIED")
        locked = run(["lock", "--project", str(self.project)], self.root, check=True)
        self.assertEqual(json.loads(locked.stdout)["status"], "LOCKED")

        archive = self.root / "fixture-agent.zip"
        packaged = run(
            ["package", "--project", str(self.project), "--output", str(archive)],
            self.root,
            check=True,
        )
        self.assertEqual(json.loads(packaged.stdout)["status"], "PACKAGED")
        with zipfile.ZipFile(archive) as bundle:
            names = set(bundle.namelist())
        self.assertIn("fixture-agent/agent_app.py", names)
        self.assertIn("fixture-agent/capabilities/useful-skill/SKILL.md", names)
        self.assertIn("fixture-agent/agent-package-manifest.json", names)
        self.assertFalse(any(".agent/" in name or ".git/" in name for name in names))

    def test_product_change_invalidates_evidence_and_lock(self) -> None:
        self.complete_blueprint()
        run(["fetch", "--project", str(self.project), "--capability", "useful-skill"], self.root, check=True)
        run(["verify", "--project", str(self.project)], self.root, check=True)
        run(["lock", "--project", str(self.project)], self.root, check=True)
        (self.project / "agent_app.py").write_text("print('changed')\n", encoding="utf-8")
        result = run(
            ["package", "--project", str(self.project), "--output", str(self.root / "stale.zip")],
            self.root,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("acceptance is stale", result.stdout)

    def test_reference_only_capability_cannot_be_vendored(self) -> None:
        value = self.complete_blueprint()
        value["capabilities"][0]["license_disposition"] = "reference_only"
        self.blueprint_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        result = run(["validate", "--project", str(self.project)], self.root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot vendor a reference-only dependency", result.stdout)

    def test_tested_recipe_hash_mismatch_rejects_fetch(self) -> None:
        value = self.complete_blueprint()
        value["capabilities"][0]["source"]["expected_tree_sha256"] = "0" * 64
        self.blueprint_path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        result = run(
            ["fetch", "--project", str(self.project), "--capability", "useful-skill"],
            self.root,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match tested recipe", result.stdout)
        self.assertFalse((self.project / ".agent/agent-assembly/candidates/useful-skill.json").exists())

    def test_experience_is_local_only_and_contains_no_source_payload(self) -> None:
        self.complete_blueprint()
        result = run(
            [
                "experience", "--project", str(self.project), "--capability", "useful-skill",
                "--outcome", "adapted", "--summary", "Needed one runtime-specific adapter.",
                "--adaptation", "Mapped the existing input contract without copying source.",
            ],
            self.root,
            check=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "EXPERIENCE_RECORDED")
        self.assertEqual(payload["sharing"]["reason"], "local_only_default")
        record = json.loads(Path(payload["record"]).read_text(encoding="utf-8"))
        self.assertFalse(record["contains_source_or_attachment"])
        self.assertNotIn(str(self.source), json.dumps(record))
        self.assertNotIn("SKILL.md", json.dumps(record))

    def test_recipe_catalog_is_metadata_only(self) -> None:
        result = run(["recipes", "--query", "memory"], self.root, check=True)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "NO_RECIPES")
        self.assertEqual(payload["recipes"], [])
        catalog = json.loads(
            (PLUGIN_ROOT / "skills/agent-assembler/assets/recipes.v1.json").read_text(encoding="utf-8")
        )
        self.assertEqual(catalog["recipes"], [])
        self.assertNotIn("source_code", catalog)

    def test_share_bridge_uses_only_existing_authorized_feedback_transport(self) -> None:
        self.complete_blueprint()
        recorded = run(
            [
                "experience", "--project", str(self.project), "--capability", "useful-skill",
                "--outcome", "adopted", "--summary", "Passed the fixture business loop.",
            ],
            self.root,
            check=True,
        )
        record = json.loads(recorded.stdout)["record"]
        unavailable = subprocess.run(
            [sys.executable, str(SHARE_SCRIPT), "--project", str(self.project), "--record", record],
            cwd=self.root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertNotEqual(unavailable.returncode, 0)
        self.assertIn("feedback runtime is unavailable", unavailable.stdout)

        runtime = self.project / ".agent/goal_compass_runtime"
        runtime.mkdir(parents=True)
        (runtime / "__init__.py").write_text("", encoding="utf-8")
        (runtime / "feedback.py").write_text(
            "def ensure_config(agent_dir): return {'upload_enabled': True}\n"
            "def upload_authorized(config): return config.get('upload_enabled') is True\n"
            "def record(**kwargs):\n"
            "    return {'captured': True, 'uploaded': True, "
            "'kind': kwargs['kind'], 'context': kwargs['context']}\n",
            encoding="utf-8",
        )
        shared = subprocess.run(
            [sys.executable, str(SHARE_SCRIPT), "--project", str(self.project), "--record", record],
            cwd=self.root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(shared.returncode, 0, shared.stdout + shared.stderr)
        payload = json.loads(shared.stdout)
        self.assertEqual(payload["status"], "SHARE_REQUESTED")
        self.assertEqual(payload["result"]["kind"], "skill_experience")
        self.assertFalse(payload["result"]["context"]["contains_source_or_attachment"])


if __name__ == "__main__":
    unittest.main()
