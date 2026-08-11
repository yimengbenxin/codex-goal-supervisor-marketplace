#!/usr/bin/env python3
"""Verify or automatically provision Goal Supervisor device delivery.

This maintenance helper never accepts a Token and never uploads a file. Device
credentials are issued by the feedback service only after a project has granted
explicit upload consent through Goal Compass.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "project",
        type=Path,
        help="An installed Goal Supervisor project that has explicit upload consent.",
    )
    args = parser.parse_args()
    project = args.project.expanduser().resolve()
    compass = project / ".agent" / "goal_compass.py"
    if not compass.is_file():
        print(json.dumps({
            "ok": False,
            "error": "goal_compass_not_installed",
            "required_action": "install_goal_supervisor_in_project",
        }, ensure_ascii=False))
        return 2
    result = subprocess.run(
        [sys.executable, str(compass), "feedback", "--flush"],
        cwd=str(project),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
        errors="replace",
    )
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
