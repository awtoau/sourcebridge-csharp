#!/usr/bin/env python3
"""Run the preserved Renode C# to Rust pipeline as a Sourcebridge adapter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


REPO = Path(__file__).resolve().parents[2]
GATES = REPO / "scripts" / "gates.py"


def load_fixture(path: Path) -> dict[str, str]:
    try:
        fixture = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{path}: cannot read pipeline fixture: {error}") from error
    if set(fixture) != {"schema_version", "source_revision"}:
        raise ValueError(f"{path}: unsupported pipeline fixture shape")
    if fixture["schema_version"] != 1 or not isinstance(fixture["source_revision"], str):
        raise ValueError(f"{path}: unsupported pipeline fixture version")
    return fixture


def gate_statuses(output: str) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and (
            parts[0].startswith("check_") or parts[0] in {"gap_census", "compile_check"}
        ):
            statuses[parts[0]] = "passed" if "ok" in parts[1:] else "failed"
    return statuses


def side(status: str, **details: object) -> dict[str, object]:
    return {"status": status, "details": details}


def run(fixture_path: Path) -> dict[str, object]:
    fixture = load_fixture(fixture_path)
    result = subprocess.run(
        [sys.executable, str(GATES), "--full"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    output = result.stdout + result.stderr
    statuses = gate_statuses(output)
    source_ok = statuses.get("check_ingest") == "passed" and statuses.get(
        "check_bug_rules"
    ) == "passed"
    extraction_checks = (
        "check_rule_negatives",
        "check_semantic_differences",
        "check_inheritance",
        "check_postconditions",
        "check_generated",
        "gap_census",
    )
    extraction_ok = all(statuses.get(name) == "passed" for name in extraction_checks)
    target_ok = statuses.get("compile_check") == "passed"
    details = {
        "source_revision": fixture["source_revision"],
        "exit_code": result.returncode,
        "gate_statuses": statuses,
        "output_tail": output[-4000:],
    }
    return {
        "schema_version": 1,
        "source": side("passed" if source_ok else "failed", **details),
        "extraction": side("passed" if extraction_ok else "failed", **details),
        "target": side("passed" if target_ok else "failed", **details),
        "oracle": side(
            "skipped",
            reason="the full gate does not execute Renode trace replay",
            **details,
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", type=Path)
    arguments = parser.parse_args()
    try:
        print(json.dumps(run(arguments.fixture), sort_keys=True))
    except (ValueError, subprocess.TimeoutExpired) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
