#!/usr/bin/env python3
"""Build a reproducible Agent package from an already working project loop."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
STATE_RELATIVE = Path(".agent/agent-assembly")
BLUEPRINT_NAME = "agent-blueprint.json"
LOCK_NAME = "agent-assembly.lock.json"
DEFAULT_RECIPE_CATALOG = PLUGIN_ROOT / "skills/agent-assembler/assets/recipes.v1.json"
SKIP_NAMES = {
    ".git", ".agent", ".codex", ".agents", "node_modules", "__pycache__",
    ".pytest_cache", ".venv", "venv", "dist", "build", "tmp", "artifacts",
}
SOURCE_SKIP_NAMES = {".git", "__pycache__", ".DS_Store", ".pytest_cache"}
SOURCE_MAX_FILES = 4_000
SOURCE_MAX_BYTES = 256 * 1024 * 1024
PROJECT_MAX_FILES = 20_000
PROJECT_MAX_BYTES = 2 * 1024 * 1024 * 1024
ACCEPTANCE_TIMEOUT_MAX = 30 * 60
STATE_MODES = {"stateless", "checkpoint", "sqlite", "keyword", "vector", "hybrid"}
LICENSE_DISPOSITIONS = {"compatible", "user_confirmed", "reference_only"}
DIST_MODES = {"vendor", "reference"}
EXPERIENCE_OUTCOMES = {"adopted", "adapted", "rejected", "failed"}


class AssemblyError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AssemblyError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AssemblyError(f"expected a JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def project_root(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise AssemblyError(f"project root does not exist: {root}")
    return root


def blueprint_path(root: Path, explicit: str | None) -> Path:
    return Path(explicit).expanduser().resolve() if explicit else root / STATE_RELATIVE / BLUEPRINT_NAME


def state_root(root: Path) -> Path:
    return root / STATE_RELATIVE


def safe_relative(value: str, *, allow_control_state: bool = False) -> Path:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise AssemblyError(f"unsafe relative path: {value!r}")
    if not allow_control_state and path.parts and path.parts[0] in {".git", ".agent", ".codex", ".agents"}:
        raise AssemblyError(f"control/runtime path cannot be packaged: {value!r}")
    return path


def normalized_id(value: str) -> str:
    result = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", result):
        raise AssemblyError(f"invalid id: {value!r}")
    return result


def iter_tree_files(root: Path, *, source_tree: bool, max_files: int, max_bytes: int):
    if root.is_symlink():
        raise AssemblyError(f"symlink roots are not supported: {root}")
    if root.is_file():
        if root.stat().st_size > max_bytes:
            raise AssemblyError(f"file exceeds size limit: {root}")
        yield root, Path(root.name)
        return
    if not root.is_dir():
        raise AssemblyError(f"path does not exist: {root}")
    skipped = SOURCE_SKIP_NAMES if source_tree else SKIP_NAMES
    count = 0
    total = 0
    for current, directories, files in os.walk(root):
        directories[:] = sorted(name for name in directories if name not in skipped)
        current_path = Path(current)
        for name in sorted(files):
            if name in skipped or name.endswith((".pyc", ".pyo")):
                continue
            path = current_path / name
            if path.is_symlink():
                raise AssemblyError(f"symlinks are not supported: {path}")
            size = path.stat().st_size
            count += 1
            total += size
            if count > max_files or total > max_bytes:
                raise AssemblyError(
                    f"tree exceeds limit: files={count}/{max_files}, bytes={total}/{max_bytes}: {root}"
                )
            yield path, path.relative_to(root)


def tree_identity(root: Path, *, source_tree: bool = False) -> dict[str, Any]:
    digest = hashlib.sha256()
    count = 0
    total = 0
    limits = (
        (SOURCE_MAX_FILES, SOURCE_MAX_BYTES)
        if source_tree
        else (PROJECT_MAX_FILES, PROJECT_MAX_BYTES)
    )
    for path, relative in iter_tree_files(root, source_tree=source_tree, max_files=limits[0], max_bytes=limits[1]):
        raw = path.read_bytes()
        relative_bytes = relative.as_posix().encode("utf-8")
        digest.update(len(relative_bytes).to_bytes(8, "big"))
        digest.update(relative_bytes)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
        count += 1
        total += len(raw)
    return {"sha256": digest.hexdigest(), "file_count": count, "total_bytes": total}


def redact_source(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https", "ssh"}:
        return value
    hostname = parsed.hostname or ""
    if parsed.port:
        hostname += f":{parsed.port}"
    return urllib.parse.urlunsplit((parsed.scheme, hostname, parsed.path, "", ""))


def run_process(command: list[str], *, cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    if not command or not all(isinstance(item, str) and item for item in command):
        raise AssemblyError("commands must be non-empty string arrays")
    environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
        "GIT_TERMINAL_PROMPT": "0",
    }
    kwargs: dict[str, Any] = {
        "cwd": cwd,
        "env": environment,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if os.name != "nt":
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate(timeout=5)
        raise AssemblyError(f"command timed out after {timeout}s: {command}") from exc
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def default_blueprint(name: str, goal: str, runtime: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "agent": {
            "name": name.strip(),
            "business_goal": goal.strip(),
            "target_runtime": runtime.strip(),
            "entrypoints": [],
            "inputs": [],
            "outputs": [],
        },
        "state": {
            "mode": "stateless",
            "rationale": "No durable state is required unless product evidence proves otherwise.",
            "backend": None,
        },
        "capabilities": [],
        "acceptance": [],
        "package": {
            "include_paths": [],
            "exclude_paths": [".git", ".agent", ".codex", ".agents", "node_modules", "tmp", "artifacts"],
        },
        "reuse_research": {
            "status": "required",
            "decision_summary": "",
            "sources_checked": [],
        },
    }


def list_objects(value: Any, field: str, errors: list[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        errors.append(f"{field} must be an array")
        return []
    if not all(isinstance(item, dict) for item in value):
        errors.append(f"{field} entries must be objects")
        return []
    return value


def validate_blueprint(value: dict[str, Any], root: Path, *, require_files: bool = True) -> list[str]:
    errors: list[str] = []
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    agent = value.get("agent")
    if not isinstance(agent, dict):
        errors.append("agent must be an object")
        agent = {}
    for field in ("name", "business_goal", "target_runtime"):
        if not isinstance(agent.get(field), str) or not agent[field].strip():
            errors.append(f"agent.{field} is required")
    entrypoints = list_objects(agent.get("entrypoints"), "agent.entrypoints", errors)
    if not entrypoints:
        errors.append("agent.entrypoints must contain at least one runnable entrypoint")
    for index, entry in enumerate(entrypoints):
        command = entry.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
            errors.append(f"agent.entrypoints[{index}].command must be a non-empty string array")

    state = value.get("state")
    if not isinstance(state, dict):
        errors.append("state must be an object")
        state = {}
    if state.get("mode") not in STATE_MODES:
        errors.append("state.mode must be one of: " + ", ".join(sorted(STATE_MODES)))
    if state.get("mode") != "stateless" and not str(state.get("rationale") or "").strip():
        errors.append("state.rationale is required for stateful architectures")

    research = value.get("reuse_research")
    if not isinstance(research, dict) or research.get("status") != "completed":
        errors.append("reuse_research.status must be completed before assembly")
    elif not str(research.get("decision_summary") or "").strip():
        errors.append("reuse_research.decision_summary is required")

    acceptance = list_objects(value.get("acceptance"), "acceptance", errors)
    if not acceptance:
        errors.append("acceptance must contain at least one machine check")
    acceptance_ids: set[str] = set()
    for index, check in enumerate(acceptance):
        try:
            check_id = normalized_id(str(check.get("id") or ""))
        except AssemblyError as exc:
            errors.append(f"acceptance[{index}]: {exc}")
            continue
        if check_id in acceptance_ids:
            errors.append(f"duplicate acceptance id: {check_id}")
        acceptance_ids.add(check_id)
        command = check.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
            errors.append(f"acceptance[{index}].command must be a non-empty string array")
        timeout = check.get("timeout_sec", 60)
        if not isinstance(timeout, int) or timeout < 1 or timeout > ACCEPTANCE_TIMEOUT_MAX:
            errors.append(f"acceptance[{index}].timeout_sec must be 1..{ACCEPTANCE_TIMEOUT_MAX}")
        try:
            safe_relative(str(check.get("cwd") or "."), allow_control_state=False)
        except AssemblyError as exc:
            errors.append(f"acceptance[{index}].cwd: {exc}")

    capabilities = list_objects(value.get("capabilities"), "capabilities", errors)
    capability_ids: set[str] = set()
    for index, capability in enumerate(capabilities):
        try:
            capability_id = normalized_id(str(capability.get("id") or ""))
        except AssemblyError as exc:
            errors.append(f"capabilities[{index}]: {exc}")
            continue
        if capability_id in capability_ids:
            errors.append(f"duplicate capability id: {capability_id}")
        capability_ids.add(capability_id)
        if not str(capability.get("purpose") or "").strip():
            errors.append(f"capabilities[{index}].purpose is required")
        source = capability.get("source")
        if not isinstance(source, dict) or source.get("kind") not in {"git", "local"}:
            errors.append(f"capabilities[{index}].source.kind must be git or local")
        elif not str(source.get("location") or "").strip():
            errors.append(f"capabilities[{index}].source.location is required")
        elif source.get("kind") == "git" and not str(source.get("ref") or "").strip():
            errors.append(f"capabilities[{index}].source.ref is required")
        expected_tree = source.get("expected_tree_sha256") if isinstance(source, dict) else None
        if expected_tree is not None and not re.fullmatch(r"[0-9a-f]{64}", str(expected_tree)):
            errors.append(
                f"capabilities[{index}].source.expected_tree_sha256 must be a lowercase SHA-256"
            )
        if capability.get("distribution") not in DIST_MODES:
            errors.append(f"capabilities[{index}].distribution must be vendor or reference")
        license_disposition = capability.get("license_disposition")
        if license_disposition not in LICENSE_DISPOSITIONS:
            errors.append(f"capabilities[{index}].license_disposition is invalid")
        if capability.get("distribution") == "vendor" and license_disposition == "reference_only":
            errors.append(f"capabilities[{index}] cannot vendor a reference-only dependency")
        verification_ids = capability.get("verification_ids")
        if not isinstance(verification_ids, list) or not verification_ids:
            errors.append(f"capabilities[{index}].verification_ids must be non-empty")
        else:
            for verification_id in verification_ids:
                if verification_id not in acceptance_ids:
                    errors.append(
                        f"capabilities[{index}] references unknown acceptance id: {verification_id}"
                    )

    package = value.get("package")
    if not isinstance(package, dict):
        errors.append("package must be an object")
        package = {}
    includes = package.get("include_paths")
    if not isinstance(includes, list) or not includes:
        errors.append("package.include_paths must contain at least one product path")
    else:
        for item in includes:
            try:
                relative = safe_relative(str(item))
                if require_files and not (root / relative).exists():
                    errors.append(f"package include path does not exist: {relative.as_posix()}")
            except AssemblyError as exc:
                errors.append(str(exc))
    return errors


def find_by_id(rows: list[dict[str, Any]], value: str, field: str) -> dict[str, Any]:
    expected = normalized_id(value)
    for row in rows:
        if row.get("id") == expected:
            return row
    raise AssemblyError(f"unknown {field}: {expected}")


def command_init(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    path = blueprint_path(root, args.blueprint)
    if path.exists() and not args.force:
        raise AssemblyError(f"blueprint already exists: {path}")
    value = default_blueprint(args.name, args.goal, args.runtime)
    write_json(path, value)
    print_json({"status": "DRAFT", "blueprint": str(path), "next_action": "complete_and_validate_blueprint"})
    return 0


def command_inspect(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    metadata_names = {
        "package.json", "pyproject.toml", "requirements.txt", "Cargo.toml", "go.mod",
        "pom.xml", "build.gradle", "Dockerfile", "docker-compose.yml", "mcp.json", "apm.yml",
    }
    entry_names = {"main.py", "app.py", "server.py", "index.js", "index.ts", "main.go", "main.rs"}
    metadata: list[str] = []
    entrypoints: list[str] = []
    tests: list[str] = []
    files = 0
    total = 0
    for path, relative in iter_tree_files(
        root, source_tree=False, max_files=PROJECT_MAX_FILES, max_bytes=PROJECT_MAX_BYTES
    ):
        files += 1
        total += path.stat().st_size
        relative_text = relative.as_posix()
        if path.name in metadata_names:
            metadata.append(relative_text)
        if path.name in entry_names or path.name.startswith("cli."):
            entrypoints.append(relative_text)
        if "test" in path.name.casefold() or "tests" in relative.parts:
            tests.append(relative_text)
    print_json({
        "status": "INSPECTED",
        "project": str(root),
        "inventory": {"file_count": files, "total_bytes": total},
        "project_metadata": sorted(metadata)[:100],
        "entrypoint_candidates": sorted(entrypoints)[:100],
        "test_candidates": sorted(tests)[:200],
        "note": "These are structural candidates, not an architecture decision.",
    })
    return 0


def command_validate(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    path = blueprint_path(root, args.blueprint)
    value = read_json(path)
    errors = validate_blueprint(value, root)
    print_json({"status": "VALID" if not errors else "INVALID", "blueprint": str(path), "errors": errors})
    return 0 if not errors else 2


def command_recipes(args: argparse.Namespace) -> int:
    path = Path(args.catalog).expanduser().resolve() if args.catalog else DEFAULT_RECIPE_CATALOG
    catalog = read_json(path)
    recipes = catalog.get("recipes")
    if catalog.get("schema_version") != SCHEMA_VERSION or not isinstance(recipes, list):
        raise AssemblyError(f"invalid recipe catalog: {path}")
    query = str(args.query or "").strip().casefold()
    matches: list[dict[str, Any]] = []
    for recipe in recipes:
        if not isinstance(recipe, dict):
            raise AssemblyError(f"invalid recipe entry in catalog: {path}")
        searchable = " ".join(
            str(recipe.get(field) or "") for field in ("id", "title", "summary", "tags", "runtimes")
        ).casefold()
        if not query or query in searchable:
            matches.append(recipe)
    print_json({
        "status": "RECIPES_FOUND" if matches else "NO_RECIPES",
        "catalog_version": catalog.get("catalog_version"),
        "query": query,
        "recipes": matches[:100],
        "note": "Recipes are maintainer-tested metadata, not bundled capability source.",
    })
    return 0


def clone_source(source: dict[str, Any], staging: Path) -> tuple[Path, str]:
    kind = source["kind"]
    location = str(source["location"])
    if kind == "local":
        origin = Path(location).expanduser().resolve()
        if not origin.is_dir():
            raise AssemblyError(f"local capability source does not exist: {origin}")
        target = staging / "source"
        shutil.copytree(origin, target, ignore=shutil.ignore_patterns(*SOURCE_SKIP_NAMES))
        identity = tree_identity(target, source_tree=True)
        return target, f"local-{identity['sha256']}"

    target = staging / "source"
    clone = run_process(["git", "clone", "--quiet", "--no-checkout", location, str(target)], cwd=staging, timeout=120)
    if clone.returncode != 0:
        raise AssemblyError(f"git clone failed: {clone.stderr[-1000:]}")
    checkout = run_process(["git", "checkout", "--quiet", "--detach", str(source["ref"])], cwd=target, timeout=60)
    if checkout.returncode != 0:
        raise AssemblyError(f"git checkout failed: {checkout.stderr[-1000:]}")
    revision = run_process(["git", "rev-parse", "HEAD"], cwd=target, timeout=10)
    if revision.returncode != 0:
        raise AssemblyError(f"git rev-parse failed: {revision.stderr[-1000:]}")
    return target, revision.stdout.strip()


def command_fetch(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    path = blueprint_path(root, args.blueprint)
    blueprint = read_json(path)
    errors = validate_blueprint(blueprint, root)
    if errors:
        raise AssemblyError("blueprint is invalid: " + "; ".join(errors))
    capability = find_by_id(blueprint["capabilities"], args.capability, "capability")
    capability_id = normalized_id(capability["id"])
    destination_parent = state_root(root) / "sources" / capability_id
    destination_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="agent-assembly-source-", dir=destination_parent) as temporary:
        source_root, revision = clone_source(capability["source"], Path(temporary))
        identity = tree_identity(source_root, source_tree=True)
        expected_tree = capability["source"].get("expected_tree_sha256")
        if expected_tree and identity["sha256"] != expected_tree:
            raise AssemblyError(
                f"capability content does not match tested recipe: {capability_id}: "
                f"expected {expected_tree}, got {identity['sha256']}"
            )
        destination = destination_parent / identity["sha256"][:16]
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source_root, destination, ignore=shutil.ignore_patterns(*SOURCE_SKIP_NAMES))
    license_files = sorted(
        relative.as_posix()
        for path, relative in iter_tree_files(
            destination,
            source_tree=True,
            max_files=SOURCE_MAX_FILES,
            max_bytes=SOURCE_MAX_BYTES,
        )
        if path.name.casefold().startswith(("license", "copying", "notice"))
    )
    record = {
        "schema_version": SCHEMA_VERSION,
        "capability_id": capability_id,
        "source": {
            **capability["source"],
            "location": redact_source(str(capability["source"]["location"])),
        },
        "resolved_revision": revision,
        "tree_sha256": identity["sha256"],
        "file_count": identity["file_count"],
        "total_bytes": identity["total_bytes"],
        "license_files": license_files,
        "cache_path": str(destination.relative_to(root)),
    }
    record_path = state_root(root) / "candidates" / f"{capability_id}.json"
    write_json(record_path, record)
    print_json({"status": "FETCHED_UNVERIFIED", "record": str(record_path), **record})
    return 0


def candidate_records(root: Path, blueprint: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for capability in blueprint["capabilities"]:
        capability_id = normalized_id(capability["id"])
        record_path = state_root(root) / "candidates" / f"{capability_id}.json"
        if not record_path.is_file():
            raise AssemblyError(f"capability has not been fetched: {capability_id}")
        record = read_json(record_path)
        cache = root / safe_relative(str(record.get("cache_path") or ""), allow_control_state=True)
        identity = tree_identity(cache, source_tree=True)
        if identity["sha256"] != record.get("tree_sha256"):
            raise AssemblyError(f"cached capability changed after fetch: {capability_id}")
        records[capability_id] = record
    return records


def input_fingerprint(root: Path, blueprint: dict[str, Any], records: dict[str, dict[str, Any]]) -> str:
    includes: list[dict[str, Any]] = []
    for value in sorted(str(item) for item in blueprint["package"]["include_paths"]):
        relative = safe_relative(value)
        identity = tree_identity(root / relative)
        includes.append({"path": relative.as_posix(), **identity})
    payload = {
        "blueprint_sha256": sha256_bytes(canonical_bytes(blueprint)),
        "include_paths": includes,
        "capabilities": {
            key: {"revision": value["resolved_revision"], "tree_sha256": value["tree_sha256"]}
            for key, value in sorted(records.items())
        },
    }
    return sha256_bytes(canonical_bytes(payload))


def expanded_command(command: list[str], root: Path) -> list[str]:
    replacements = {"{python}": sys.executable, "{project}": str(root)}
    return [replacements.get(item, item.replace("{project}", str(root))) for item in command]


def execute_acceptance(root: Path, check: dict[str, Any]) -> dict[str, Any]:
    relative_cwd = safe_relative(str(check.get("cwd") or "."))
    cwd = (root / relative_cwd).resolve()
    if root != cwd and root not in cwd.parents:
        raise AssemblyError(f"acceptance cwd escapes project: {relative_cwd}")
    if not cwd.is_dir():
        raise AssemblyError(f"acceptance cwd does not exist: {relative_cwd}")
    command = expanded_command(check["command"], root)
    started = time.monotonic()
    result = run_process(command, cwd=cwd, timeout=int(check.get("timeout_sec", 60)))
    return {
        "id": check["id"],
        "passed": result.returncode == 0,
        "returncode": result.returncode,
        "duration_ms": round((time.monotonic() - started) * 1000),
        "command": command,
        "cwd": relative_cwd.as_posix(),
        "stdout_tail": result.stdout[-4000:],
        "stderr_tail": result.stderr[-4000:],
    }


def command_verify(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    path = blueprint_path(root, args.blueprint)
    blueprint = read_json(path)
    errors = validate_blueprint(blueprint, root)
    if errors:
        raise AssemblyError("blueprint is invalid: " + "; ".join(errors))
    records = candidate_records(root, blueprint)
    fingerprint = input_fingerprint(root, blueprint, records)
    checks = blueprint["acceptance"]
    if args.acceptance:
        checks = [find_by_id(checks, args.acceptance, "acceptance")]
    results = [execute_acceptance(root, check) for check in checks]
    evidence_root = state_root(root) / "evidence"
    for result in results:
        write_json(evidence_root / f"{result['id']}.json", {
            "schema_version": SCHEMA_VERSION,
            "input_fingerprint": fingerprint,
            **result,
        })
    passed = all(result["passed"] for result in results)
    print_json({
        "status": "VERIFIED" if passed else "VERIFICATION_FAILED",
        "input_fingerprint": fingerprint,
        "results": results,
    })
    return 0 if passed else 1


def require_current_evidence(
    root: Path,
    blueprint: dict[str, Any],
    records: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, dict[str, Any]]]:
    fingerprint = input_fingerprint(root, blueprint, records)
    evidence: dict[str, dict[str, Any]] = {}
    for check in blueprint["acceptance"]:
        path = state_root(root) / "evidence" / f"{check['id']}.json"
        if not path.is_file():
            raise AssemblyError(f"acceptance has not been run: {check['id']}")
        result = read_json(path)
        if not result.get("passed"):
            raise AssemblyError(f"acceptance did not pass: {check['id']}")
        if result.get("input_fingerprint") != fingerprint:
            raise AssemblyError(f"acceptance is stale for current inputs: {check['id']}")
        evidence[check["id"]] = result
    for capability in blueprint["capabilities"]:
        for verification_id in capability["verification_ids"]:
            if verification_id not in evidence:
                raise AssemblyError(
                    f"capability {capability['id']} lacks current verification: {verification_id}"
                )
    return fingerprint, evidence


def command_lock(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    path = blueprint_path(root, args.blueprint)
    blueprint = read_json(path)
    errors = validate_blueprint(blueprint, root)
    if errors:
        raise AssemblyError("blueprint is invalid: " + "; ".join(errors))
    records = candidate_records(root, blueprint)
    fingerprint, evidence = require_current_evidence(root, blueprint, records)
    lock = {
        "schema_version": SCHEMA_VERSION,
        "blueprint_sha256": sha256_bytes(canonical_bytes(blueprint)),
        "input_fingerprint": fingerprint,
        "capabilities": [
            {
                "id": capability["id"],
                "purpose": capability["purpose"],
                "distribution": capability["distribution"],
                "license_disposition": capability["license_disposition"],
                "source": records[capability["id"]]["source"],
                "resolved_revision": records[capability["id"]]["resolved_revision"],
                "tree_sha256": records[capability["id"]]["tree_sha256"],
                "file_count": records[capability["id"]]["file_count"],
                "total_bytes": records[capability["id"]]["total_bytes"],
                "license_files": records[capability["id"]]["license_files"],
                "verification_ids": capability["verification_ids"],
            }
            for capability in blueprint["capabilities"]
        ],
        "acceptance": [
            {
                "id": check_id,
                "returncode": result["returncode"],
                "duration_ms": result["duration_ms"],
            }
            for check_id, result in sorted(evidence.items())
        ],
    }
    lock_path = state_root(root) / LOCK_NAME
    write_json(lock_path, lock)
    print_json({"status": "LOCKED", "lock": str(lock_path), **lock})
    return 0


def load_current_lock(root: Path, blueprint: dict[str, Any], records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    path = state_root(root) / LOCK_NAME
    if not path.is_file():
        raise AssemblyError("assembly has not been locked")
    lock = read_json(path)
    fingerprint, _ = require_current_evidence(root, blueprint, records)
    if lock.get("blueprint_sha256") != sha256_bytes(canonical_bytes(blueprint)):
        raise AssemblyError("lock does not match current blueprint")
    if lock.get("input_fingerprint") != fingerprint:
        raise AssemblyError("lock does not match current project inputs")
    return lock


def add_zip_file(archive: zipfile.ZipFile, source: Path, destination: str) -> None:
    info = zipfile.ZipInfo(destination, date_time=(2026, 1, 1, 0, 0, 0))
    info.external_attr = (0o755 if os.access(source, os.X_OK) else 0o644) << 16
    archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def command_package(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    path = blueprint_path(root, args.blueprint)
    blueprint = read_json(path)
    errors = validate_blueprint(blueprint, root)
    if errors:
        raise AssemblyError("blueprint is invalid: " + "; ".join(errors))
    records = candidate_records(root, blueprint)
    lock = load_current_lock(root, blueprint, records)
    destination = Path(args.output).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    package_name = normalized_id(str(blueprint["agent"]["name"]).replace(" ", "-"))
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "package_name": package_name,
        "business_goal": blueprint["agent"]["business_goal"],
        "target_runtime": blueprint["agent"]["target_runtime"],
        "entrypoints": blueprint["agent"]["entrypoints"],
        "state": blueprint["state"],
        "input_fingerprint": lock["input_fingerprint"],
        "capabilities": lock["capabilities"],
    }
    written: set[str] = set()
    with zipfile.ZipFile(temporary, "w") as archive:
        for include in sorted(str(item) for item in blueprint["package"]["include_paths"]):
            relative = safe_relative(include)
            source = root / relative
            for file_path, tree_relative in iter_tree_files(
                source, source_tree=False, max_files=PROJECT_MAX_FILES, max_bytes=PROJECT_MAX_BYTES
            ):
                package_relative = relative if source.is_file() else relative / tree_relative
                destination_name = f"{package_name}/{package_relative.as_posix()}"
                if destination_name in written:
                    continue
                add_zip_file(archive, file_path, destination_name)
                written.add(destination_name)
        for capability in blueprint["capabilities"]:
            if capability["distribution"] != "vendor":
                continue
            record = records[capability["id"]]
            source_root = root / safe_relative(record["cache_path"], allow_control_state=True)
            for file_path, relative in iter_tree_files(
                source_root,
                source_tree=True,
                max_files=SOURCE_MAX_FILES,
                max_bytes=SOURCE_MAX_BYTES,
            ):
                destination_name = f"{package_name}/capabilities/{capability['id']}/{relative.as_posix()}"
                add_zip_file(archive, file_path, destination_name)
        for filename, value in (
            (BLUEPRINT_NAME, blueprint),
            (LOCK_NAME, lock),
            ("agent-package-manifest.json", manifest),
        ):
            info = zipfile.ZipInfo(f"{package_name}/{filename}", date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            archive.writestr(info, json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(destination)
    print_json({
        "status": "PACKAGED",
        "archive": str(destination),
        "sha256": sha256_bytes(destination.read_bytes()),
        "file_count": len(written) + 3,
        "input_fingerprint": lock["input_fingerprint"],
    })
    return 0


def bounded_text(value: str | None, limit: int = 1000) -> str:
    return str(value or "").strip()[:limit]


def current_verification_summary(root: Path, blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for check in blueprint.get("acceptance", []):
        if not isinstance(check, dict) or not check.get("id"):
            continue
        path = state_root(root) / "evidence" / f"{check['id']}.json"
        if not path.is_file():
            summary.append({"id": check["id"], "status": "NOT_RUN"})
            continue
        result = read_json(path)
        summary.append({
            "id": check["id"],
            "status": "PASS" if result.get("passed") else "FAIL",
            "returncode": result.get("returncode"),
        })
    return summary


def command_experience(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    blueprint = read_json(blueprint_path(root, args.blueprint))
    capabilities = blueprint.get("capabilities")
    if not isinstance(capabilities, list):
        raise AssemblyError("blueprint capabilities must be an array")
    capability = find_by_id(capabilities, args.capability, "capability")
    outcome = str(args.outcome).strip().lower()
    if outcome not in EXPERIENCE_OUTCOMES:
        raise AssemblyError("outcome must be one of: " + ", ".join(sorted(EXPERIENCE_OUTCOMES)))
    summary = bounded_text(args.summary)
    if not summary:
        raise AssemblyError("experience summary is required")
    capability_id = normalized_id(capability["id"])
    record_path = state_root(root) / "candidates" / f"{capability_id}.json"
    candidate = read_json(record_path) if record_path.is_file() else {}
    source = capability.get("source") if isinstance(capability.get("source"), dict) else {}
    source_identity = {
        "kind": source.get("kind"),
        "ref": source.get("ref"),
        "expected_tree_sha256": source.get("expected_tree_sha256"),
        "resolved_revision": candidate.get("resolved_revision"),
        "tree_sha256": candidate.get("tree_sha256"),
    }
    experience = {
        "schema_version": SCHEMA_VERSION,
        "capability_id": capability_id,
        "recipe_id": capability.get("recipe_id"),
        "source_fingerprint": sha256_bytes(canonical_bytes(source_identity)),
        "resolved_revision": candidate.get("resolved_revision"),
        "tree_sha256": candidate.get("tree_sha256"),
        "target_runtime": str(blueprint.get("agent", {}).get("target_runtime") or "unknown"),
        "outcome": outcome,
        "summary": summary,
        "adaptation_summary": bounded_text(args.adaptation),
        "error_category": bounded_text(args.error_category, 120) or None,
        "verification": current_verification_summary(root, blueprint),
        "contains_source_or_attachment": False,
        "sharing_policy": "local_only_unless_existing_project_feedback_consent",
    }
    digest = sha256_bytes(canonical_bytes(experience))
    destination = state_root(root) / "experience-outbox" / f"{capability_id}-{digest[:16]}.json"
    write_json(destination, experience)
    print_json({
        "status": "EXPERIENCE_RECORDED",
        "record": str(destination),
        "experience": experience,
        "sharing": {"shared": False, "reason": "local_only_default"},
    })
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assemble an already working project loop into a reproducible Agent package."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    value = sub.add_parser("init", help="Create a draft Agent assembly blueprint.")
    value.add_argument("--project", required=True)
    value.add_argument("--blueprint")
    value.add_argument("--name", required=True)
    value.add_argument("--goal", required=True)
    value.add_argument("--runtime", required=True)
    value.add_argument("--force", action="store_true")
    value.set_defaults(func=command_init)

    value = sub.add_parser("inspect", help="Return a bounded structural project inventory.")
    value.add_argument("--project", required=True)
    value.set_defaults(func=command_inspect)

    value = sub.add_parser("recipes", help="Query maintainer-tested recipe metadata.")
    value.add_argument("--catalog")
    value.add_argument("--query")
    value.set_defaults(func=command_recipes)

    value = sub.add_parser("experience", help="Record a local, metadata-only capability experience.")
    value.add_argument("--project", required=True)
    value.add_argument("--blueprint")
    value.add_argument("--capability", required=True)
    value.add_argument("--outcome", required=True, choices=sorted(EXPERIENCE_OUTCOMES))
    value.add_argument("--summary", required=True)
    value.add_argument("--adaptation")
    value.add_argument("--error-category")
    value.set_defaults(func=command_experience)

    for name, help_text, func in (
        ("validate", "Validate the assembly blueprint.", command_validate),
        ("fetch", "Fetch one selected capability into the isolated assembly cache.", command_fetch),
        ("verify", "Run blueprint machine acceptance against current inputs.", command_verify),
        ("lock", "Lock verified project and capability inputs.", command_lock),
        ("package", "Create a deterministic portable Agent archive.", command_package),
    ):
        value = sub.add_parser(name, help=help_text)
        value.add_argument("--project", required=True)
        value.add_argument("--blueprint")
        if name == "fetch":
            value.add_argument("--capability", required=True)
        if name == "verify":
            value.add_argument("--acceptance")
        if name == "package":
            value.add_argument("--output", required=True)
        value.set_defaults(func=func)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except AssemblyError as exc:
        print_json({"status": "ERROR", "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
