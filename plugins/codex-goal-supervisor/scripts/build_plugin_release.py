#!/usr/bin/env python3
"""Build a small marketplace tree plus complete offline release archives."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "codex-goal-supervisor"
MARKETPLACE_TEMPLATE = PLUGIN_ROOT / "server" / "goal-supervisor-marketplace.json"
ROLE_PACK = PLUGIN_ROOT / "assets" / "role-packs" / "agency-agents"
ROLE_PACK_REMOTE_NAME = "agency-agents.remote.json"
HARNESS = PLUGIN_ROOT / "assets" / "governor-harness"
HARNESS_REMOTE_NAME = "governor-harness.remote.json"
ROLE_PACK_ASSET_BASE_URL = "https://feedback.xn--15tf697cgrb.xyz/goal-supervisor-assets"
FULL_TOP_LEVEL_DIRS = (
    ".codex-plugin",
    "assets",
    "docs",
    "hooks",
    "scripts",
    "server",
    "skills",
    "templates",
    "verification",
)
MARKETPLACE_TOP_LEVEL_DIRS = (
    ".codex-plugin",
    "hooks",
    "scripts",
    "skills",
    "templates",
)
TOP_LEVEL_FILES = (
    "README.md",
    "INSTALL_GOAL_COMPASS.zh.md",
    "LICENSE",
    "NOTICE",
    "CONTRIBUTING.md",
    "SECURITY.md",
)
EDITIONS = ("offline", "update-only", "full")
MARKETPLACE_NAMES = {
    "full": "goal-supervisor",
    "update-only": "goal-supervisor-update-only",
}
LOCAL_FEEDBACK_TEMPLATE = PLUGIN_ROOT / "scripts" / "release_variants" / "feedback_local.py"
EXCLUDED_NAMES = {
    ".DS_Store",
    "__pycache__",
    ".pytest_cache",
    ".coverage",
    "feedback-inbox",
}


def ignored(_: str, names: list[str]) -> set[str]:
    return {
        name for name in names
        if name in EXCLUDED_NAMES
        or name.endswith((".pyc", ".pyo", ".tmp"))
        or (name.startswith("RELEASE_NOTES_") and name.endswith(".md"))
    }


def plugin_version() -> str:
    manifest = json.loads((PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    return str(manifest["version"])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_full_distribution(target: Path) -> int:
    target.mkdir(parents=True, exist_ok=True)
    for name in FULL_TOP_LEVEL_DIRS:
        source = PLUGIN_ROOT / name
        if not source.is_dir():
            continue
        shutil.copytree(source, target / name, ignore=ignored, dirs_exist_ok=True)
    for name in TOP_LEVEL_FILES:
        source = PLUGIN_ROOT / name
        if source.is_file():
            shutil.copy2(source, target / name)
    return sum(1 for path in target.rglob("*") if path.is_file())


def write_tree_zip(source_root: Path, archive_root: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".tmp")
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(item for item in source_root.rglob("*") if item.is_file()):
            relative = Path(archive_root) / path.relative_to(source_root)
            info = zipfile.ZipInfo.from_file(path, arcname=relative.as_posix())
            info.date_time = (2026, 1, 1, 0, 0, 0)
            info.external_attr = (0o755 if os.access(path, os.X_OK) else 0o644) << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    temp.replace(destination)


def write_role_pack_zip(pack: Path, destination: Path) -> None:
    write_tree_zip(pack, "agency-agents", destination)


def role_pack_descriptor(archive: Path) -> dict[str, Any]:
    manifest = json.loads((ROLE_PACK / "manifest.json").read_text(encoding="utf-8"))
    source = manifest.get("source", {})
    source_commit = str(source.get("commit") or "unknown")
    archive_name = f"agency-agents-{source_commit[:12]}.zip"
    return {
        "schema_version": 1,
        "asset_id": "agency-agents",
        "pack_id": "agency-agents",
        "source_commit": source_commit,
        "archive_url": f"{ROLE_PACK_ASSET_BASE_URL}/{archive_name}",
        "archive_name": archive_name,
        "archive_root": "agency-agents",
        "archive_sha256": sha256(archive),
        "archive_bytes": archive.stat().st_size,
        "max_files": 512,
        "max_uncompressed_bytes": 12 * 1024 * 1024,
    }


def harness_descriptor(archive: Path) -> dict[str, Any]:
    version = plugin_version()
    archive_name = f"governor-harness-{version.replace('+codex.', '-')}.zip"
    return {
        "schema_version": 1,
        "asset_id": "governor-harness",
        "source_version": version,
        "archive_url": f"{ROLE_PACK_ASSET_BASE_URL}/{archive_name}",
        "archive_name": archive_name,
        "archive_root": "governor-harness",
        "archive_sha256": sha256(archive),
        "archive_bytes": archive.stat().st_size,
        "max_files": 128,
        "max_uncompressed_bytes": 4 * 1024 * 1024,
    }


def copy_marketplace_distribution(
    target: Path,
    role_descriptor: dict[str, Any],
    runtime_descriptor: dict[str, Any],
) -> int:
    """Copy only files required at runtime; optional experts remain on demand."""
    target.mkdir(parents=True, exist_ok=True)
    for name in MARKETPLACE_TOP_LEVEL_DIRS:
        source = PLUGIN_ROOT / name
        if source.is_dir():
            shutil.copytree(source, target / name, ignore=ignored, dirs_exist_ok=True)
    descriptor_path = target / "assets" / "role-packs" / ROLE_PACK_REMOTE_NAME
    descriptor_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor_path.write_text(json.dumps(role_descriptor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    runtime_path = target / "assets" / HARNESS_REMOTE_NAME
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(json.dumps(runtime_descriptor, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name in TOP_LEVEL_FILES:
        source = PLUGIN_ROOT / name
        if source.is_file():
            shutil.copy2(source, target / name)
    return sum(1 for path in target.rglob("*") if path.is_file())


def validate_distribution(plugin: Path, edition: str = "full") -> None:
    forbidden_roots = [plugin / ".agent", plugin / ".codex", plugin / ".agents"]
    if any(path.exists() for path in forbidden_roots):
        raise RuntimeError("Release contains project/runtime state directories.")
    generated = [
        path for path in plugin.rglob("*")
        if path.name in {"__pycache__", ".DS_Store"} or path.suffix in {".pyc", ".pyo"}
    ]
    if generated:
        raise RuntimeError(f"Release contains generated files: {generated[:5]}")
    manifest = json.loads((plugin / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    if manifest.get("name") != PLUGIN_NAME or manifest.get("version") != plugin_version():
        raise RuntimeError("Release manifest identity does not match source.")
    if manifest.get("distributionEdition", "full") != edition:
        raise RuntimeError("Release manifest edition does not match requested distribution.")


def remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def replace_between(text: str, start: str, end: str, replacement: str) -> str:
    start_at = text.find(start)
    end_at = text.find(end, start_at + len(start)) if start_at >= 0 else -1
    if start_at < 0 or end_at < 0:
        raise RuntimeError(f"Release source markers not found: {start!r} -> {end!r}")
    return text[:start_at] + replacement + text[end_at:]


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def strip_feedback_transport(plugin: Path) -> None:
    runtime = plugin / "assets" / "governor-harness" / ".agent" / "goal_compass_runtime"
    shutil.copy2(LOCAL_FEEDBACK_TEMPLATE, runtime / "feedback.py")

    compass = plugin / "assets" / "governor-harness" / ".agent" / "goal_compass.py"
    text = compass.read_text(encoding="utf-8")
    text = text.replace(
        "from goal_compass_runtime.feedback import (\n"
        "    configure as configure_feedback,\n"
        "    ensure_config as ensure_feedback_config,\n"
        "    flush as flush_feedback,\n"
        "    record as record_feedback,\n"
        "    status as feedback_status,\n"
        "    upload_authorized as feedback_upload_authorized,\n"
        ")",
        "from goal_compass_runtime.feedback import (\n"
        "    ensure_config as ensure_feedback_config,\n"
        "    record as record_feedback,\n"
        "    status as feedback_status,\n"
        ")",
    )
    local_command = '''def cmd_feedback(args: argparse.Namespace) -> int:\n    if not args.kind or not args.message:\n        print(json.dumps({"ok": False, "error": "--kind and --message are required"}, ensure_ascii=False))\n        return 2\n    result = report_governance_feedback(\n        args.kind,\n        args.message,\n        source="ai_reported_plugin_judgment",\n        severity=args.severity,\n        rule_id=args.rule_id,\n        command=args.command,\n        status="REPORTED",\n        context={"expected_behavior": args.expected_behavior},\n    )\n    ok = bool(result.get("captured"))\n    print(json.dumps({"ok": ok, **result}, ensure_ascii=False, indent=2))\n    return 0 if ok else 2\n\n\n'''
    text = replace_between(
        text,
        "def cmd_feedback_config(args: argparse.Namespace) -> int:",
        "@serialized_current_state\ndef cmd_reuse_check",
        local_command,
    )
    parser_block = '''    p = sub.add_parser("feedback")\n    p.add_argument("--kind", choices=["false_positive", "false_negative", "wrong_status", "plugin_runtime_error", "workflow_friction", "other"])\n    p.add_argument("--message")\n    p.add_argument("--expected-behavior")\n    p.add_argument("--rule-id")\n    p.add_argument("--command")\n    p.add_argument("--severity", choices=["info", "warning", "error", "critical"], default="warning")\n    p.set_defaults(func=cmd_feedback)\n'''
    text = replace_between(
        text,
        '    p = sub.add_parser("feedback-config")',
        '    p = sub.add_parser("reuse-check")',
        parser_block,
    )
    write_text(compass, text)

    installer = plugin / "scripts" / "install_governor.py"
    text = installer.read_text(encoding="utf-8")
    text = replace_between(text, "def prompt_yes_no(", "def plugin_version() -> str:", "")
    for line in (
        '    parser.add_argument("--feedback-context", choices=["enterprise", "personal"], help="Project privacy context for non-interactive installs.")\n',
        '    feedback_upload = parser.add_mutually_exclusive_group()\n',
        '    feedback_upload.add_argument("--allow-feedback-upload", action="store_true", help="Authorize this project to upload redacted governance feedback.")\n',
        '    feedback_upload.add_argument("--deny-feedback-upload", action="store_true", help="Keep feedback in the local outbox only (default).")\n',
        '    parser.add_argument("--confirm-feedback-upload", action="store_true", help="Required confirmation for --allow-feedback-upload.")\n',
        '    context, allow_upload = resolve_feedback_policy(args)\n',
        '    policy_result = configure_feedback_policy(target, context, allow_upload)\n',
        '    if policy_result != 0:\n        return policy_result\n',
    ):
        text = text.replace(line, "")
    write_text(installer, text)

    for relative in (
        "scripts/configure_feedback_client.py",
        "scripts/fetch_feedback.py",
        "verification/scenarios/run_feedback_matrix.py",
        "verification/tests/test_feedback_receiver.py",
    ):
        remove_path(plugin / relative)
    remove_path(plugin / "server")
    for path in (plugin / "docs").glob("*FEEDBACK*"):
        remove_path(path)
    remove_path(plugin / "verification")

    skill = plugin / "skills" / "goal-supervisor" / "SKILL.md"
    skill_text = skill.read_text(encoding="utf-8")
    skill_text = replace_between(
        skill_text,
        "## Feedback Consent",
        "## Optional Ticket Semantics",
        "## Local Diagnostic Records\n\nThis edition keeps redacted plugin diagnostics in the project-local outbox only. It contains no network transport, device registration, remote endpoint, credential handling, or upload command.\n\n",
    )
    skill_text = "\n".join(
        line for line in skill_text.splitlines()
        if "Feedback upload is disabled by default" not in line
    ) + "\n"
    write_text(skill, skill_text)

    readme = plugin / "README.md"
    readme_text = readme.read_text(encoding="utf-8")
    readme_text = readme_text.replace(
        "Installation writes only `.agent/**` and `.codex/hooks.json`. It does not overwrite the project README, AGENTS, or tests. Feedback upload is disabled unless the user explicitly authorizes redacted delivery for that project.",
        "Installation writes only `.agent/**` and `.codex/hooks.json`. It does not overwrite the project README, AGENTS, or tests. This edition stores redacted diagnostics locally and contains no feedback upload transport.",
    )
    readme_text = replace_between(
        readme_text,
        "## Privacy",
        "## Verification",
        "## Privacy\n\nDiagnostic feedback remains project-local. This edition contains no network transport, device registration, remote endpoint, credential handling, or upload command.\n\n",
    )
    readme_text = readme_text.replace(
        "The public repository contains the plugin source, tests, documentation, optional\nself-hosted feedback receiver, and the attributed third-party role snapshot.",
        "The public repository contains the plugin source, tests, documentation, and the\nattributed third-party role snapshot. This package contains no feedback receiver.",
    )
    write_text(readme, readme_text)


def strip_auto_update(plugin: Path) -> None:
    for relative in (
        "scripts/configure_plugin_auto_update.py",
        "scripts/plugin_auto_update.py",
        "verification/tests/test_plugin_auto_update.py",
        "docs/PLUGIN_AUTO_UPDATE_20260809.md",
    ):
        remove_path(plugin / relative)
    skill = plugin / "skills" / "goal-supervisor" / "SKILL.md"
    skill_text = "\n".join(
        line for line in skill.read_text(encoding="utf-8").splitlines()
        if "Plugin auto-update is a separate device-level capability" not in line
    ) + "\n"
    write_text(skill, skill_text)
    readme = plugin / "README.md"
    readme_text = replace_between(
        readme.read_text(encoding="utf-8"),
        "## Plugin Auto Update",
        "## Optional Ticket Flow",
        "",
    )
    write_text(readme, readme_text)


def apply_edition(plugin: Path, edition: str) -> None:
    if edition not in EDITIONS:
        raise RuntimeError(f"Unknown release edition: {edition}")
    manifest_path = plugin / ".codex-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["distributionEdition"] = edition
    manifest["networkFeatures"] = {
        "automaticUpdates": edition in {"update-only", "full"},
        "feedbackUpload": edition == "full",
    }
    capabilities = list(manifest.get("interface", {}).get("capabilities", []))
    if edition != "full":
        capabilities = [item for item in capabilities if "feedback" not in str(item).lower()]
        strip_feedback_transport(plugin)
    if edition == "offline":
        capabilities = [item for item in capabilities if "auto-update" not in str(item).lower()]
        strip_auto_update(plugin)
    manifest["interface"]["capabilities"] = capabilities
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    remove_path(plugin / "scripts" / "release_variants")
    if edition != "full":
        remove_path(plugin / "scripts" / "build_plugin_release.py")
    edition_text = {
        "offline": "No automatic updater and no feedback upload transport are present. Redacted diagnostics stay local.",
        "update-only": "Automatic updater code is present. Feedback upload transport and server code are not present; redacted diagnostics stay local.",
        "full": "Automatic updater and explicit-consent feedback upload transport are present. Upload remains disabled by default.",
    }[edition]
    (plugin / "EDITION.md").write_text(f"# {edition} edition\n\n{edition_text}\n", encoding="utf-8")


def build_edition_zip(edition: str, destination: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix=f"goal-supervisor-{edition}-") as temporary:
        plugin = Path(temporary) / PLUGIN_NAME
        files = copy_full_distribution(plugin)
        apply_edition(plugin, edition)
        validate_distribution(plugin, edition)
        write_zip(plugin, destination)
        return {
            "edition": edition,
            "zip": str(destination.resolve()),
            "zip_sha256": sha256(destination),
            "source_file_count": files,
            "distribution_file_count": sum(1 for path in plugin.rglob("*") if path.is_file()),
        }


def build_all_editions(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    version = plugin_version()
    results = []
    for edition in EDITIONS:
        destination = output_dir / f"{PLUGIN_NAME}-{version}-{edition}.zip"
        results.append(build_edition_zip(edition, destination))
    return {"status": "BUILT", "version": version, "editions": results}


def write_marketplace(root: Path, edition: str = "full") -> None:
    destination = root / ".agents" / "plugins" / "marketplace.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(MARKETPLACE_TEMPLATE.read_text(encoding="utf-8"))
    payload["name"] = MARKETPLACE_NAMES[edition]
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    edition_title = "Full" if edition == "full" else "Update-only"
    feedback_boundary = (
        "Remote feedback support is included but disabled by default and requires explicit project consent."
        if edition == "full"
        else "Remote feedback client, credential, upload, fetch, and server code are physically absent."
    )
    repository = (
        "yimengbenxin/codex-goal-supervisor-marketplace"
        if edition == "full"
        else "yimengbenxin/codex-goal-supervisor-update-only-marketplace"
    )
    readme = f"""# Codex Goal Supervisor - {edition_title} Marketplace

This repository is the official `{edition}` Codex marketplace channel for [Codex Goal Supervisor](https://github.com/yimengbenxin/codex-goal-supervisor), an execution-convergence tool for long-running Codex work.

Codex Goal Supervisor preserves a project North Star, maintains a separate executable Goal contract, distinguishes activity from evidence-backed progress, restores the active Goal after temporary requests or compaction, and offers optional Custodian, company-role, Auditor, Janitor, convergence, and bounded-ticket capabilities.

It is an advisory-first administrator, not a project decision maker. Ordinary work does not require tickets or role receipts. Janitor is MARK_ONLY and never deletes product files. Project use remains explicit opt-in.

## Edition Boundary

- Automatic updates: included and pinned to the `{edition}` channel.
- Feedback: {feedback_boundary}
- Cross-edition replacement: refused by the updater.
- Project activation: never performed by an update check.

## Install

```bash
codex plugin marketplace add {repository} --ref main
codex plugin add codex-goal-supervisor@{MARKETPLACE_NAMES[edition]}
```

For capabilities, project activation, privacy boundaries, verification evidence, and release ZIPs, use the [canonical repository](https://github.com/yimengbenxin/codex-goal-supervisor) and [latest release](https://github.com/yimengbenxin/codex-goal-supervisor/releases/latest).
"""
    (root / "README.md").write_text(readme, encoding="utf-8")


def build_edition_marketplace(output: Path, edition: str, *, force: bool = False) -> dict[str, Any]:
    if edition not in MARKETPLACE_NAMES:
        raise RuntimeError("Only full and update-only editions support automatic updates.")
    if output.exists():
        if not force:
            raise RuntimeError(f"Output already exists; pass --force to replace it: {output}")
        shutil.rmtree(output)
    plugin = output / "plugins" / PLUGIN_NAME
    copy_full_distribution(plugin)
    apply_edition(plugin, edition)
    validate_distribution(plugin, edition)
    write_marketplace(output, edition)
    return {
        "status": "BUILT",
        "edition": edition,
        "version": plugin_version(),
        "marketplace_name": MARKETPLACE_NAMES[edition],
        "marketplace_root": str(output.resolve()),
        "plugin_root": str(plugin.resolve()),
        "file_count": sum(1 for path in output.rglob("*") if path.is_file()),
    }


def write_zip(plugin: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + ".tmp")
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(item for item in plugin.rglob("*") if item.is_file()):
            relative = Path(PLUGIN_NAME) / path.relative_to(plugin)
            info = zipfile.ZipInfo.from_file(path, arcname=relative.as_posix())
            info.date_time = (2026, 1, 1, 0, 0, 0)
            info.external_attr = (0o755 if os.access(path, os.X_OK) else 0o644) << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    temp.replace(destination)


def build(
    output: Path,
    zip_path: Path | None = None,
    role_pack_zip: Path | None = None,
    harness_zip: Path | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    if output.exists():
        if not force:
            raise RuntimeError(f"Output already exists; pass --force to replace it: {output}")
        shutil.rmtree(output)
    if not ROLE_PACK.is_dir() or not HARNESS.is_dir():
        raise RuntimeError("Release source is missing the role pack or project runtime.")
    with tempfile.TemporaryDirectory(prefix="goal-supervisor-release-assets-") as temporary_assets:
        generated_role_pack = role_pack_zip or Path(temporary_assets) / "agency-agents.zip"
        generated_harness = harness_zip or Path(temporary_assets) / "governor-harness.zip"
        write_role_pack_zip(ROLE_PACK, generated_role_pack)
        write_tree_zip(HARNESS, "governor-harness", generated_harness)
        role_descriptor = role_pack_descriptor(generated_role_pack)
        runtime_descriptor = harness_descriptor(generated_harness)

        plugin = output / "plugins" / PLUGIN_NAME
        files = copy_marketplace_distribution(plugin, role_descriptor, runtime_descriptor)
        write_marketplace(output)
        validate_distribution(plugin)
        result: dict[str, Any] = {
            "status": "BUILT",
            "version": plugin_version(),
            "marketplace_root": str(output.resolve()),
            "plugin_root": str(plugin.resolve()),
            "marketplace_file_count": files,
            "role_pack": role_descriptor,
            "project_runtime": runtime_descriptor,
        }
        if role_pack_zip:
            result["role_pack_zip"] = str(role_pack_zip.resolve())
        if harness_zip:
            result["harness_zip"] = str(harness_zip.resolve())
        if zip_path:
            full_plugin = Path(temporary_assets) / "full" / PLUGIN_NAME
            full_files = copy_full_distribution(full_plugin)
            validate_distribution(full_plugin)
            write_zip(full_plugin, zip_path)
            result.update({
                "file_count": full_files,
                "zip": str(zip_path.resolve()),
                "zip_sha256": sha256(zip_path),
            })
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--zip", type=Path)
    parser.add_argument("--role-pack-zip", type=Path)
    parser.add_argument("--harness-zip", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--edition", choices=EDITIONS, default="full")
    parser.add_argument("--all-editions-dir", type=Path)
    parser.add_argument("--marketplace-edition", choices=tuple(MARKETPLACE_NAMES))
    args = parser.parse_args()
    if args.all_editions_dir:
        print(json.dumps(build_all_editions(args.all_editions_dir), ensure_ascii=False, indent=2))
        return 0
    if args.marketplace_edition:
        if not args.output:
            raise SystemExit("--marketplace-edition requires --output")
        result = build_edition_marketplace(args.output, args.marketplace_edition, force=args.force)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.output:
        output = args.output
        temporary = None
    else:
        temporary = tempfile.TemporaryDirectory(prefix="goal-supervisor-release-")
        output = Path(temporary.name) / "marketplace"
    if args.edition != "full":
        if not args.zip:
            raise SystemExit("--edition offline/update-only requires --zip")
        result = build_edition_zip(args.edition, args.zip)
    else:
        result = build(output, args.zip, args.role_pack_zip, args.harness_zip, force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if temporary:
        temporary.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
