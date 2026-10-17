#!/usr/bin/env python3
"""Dispatch pack fixtures to their Sourcebridge result adapters."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


def main() -> int:
    if len(sys.argv) != 2:
        print("expected exactly one fixture path", file=sys.stderr)
        return 2
    fixture = Path(sys.argv[1]).resolve()
    if fixture.suffix == ".cs":
        command = [
            sys.executable,
            str(ROOT / "adapter.py"),
            "--run",
            fixture.name,
            "--sourcebridge-result",
        ]
    elif fixture.name == "renode-pipeline.json":
        command = [sys.executable, str(ROOT / "renode_pipeline.py"), str(fixture)]
    else:
        print(f"unsupported Sourcebridge fixture: {fixture}", file=sys.stderr)
        return 2
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
