#!/usr/bin/env python3
"""Run standalone source-side C# adapter fixtures.

The adapter compiles and executes small C# fixtures when the .NET SDK is
available.  It deliberately does not invoke a converter or emitter, so every
result keeps the target side explicitly blocked rather than implying that
source compilation demonstrates conversion capability.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
TMP_ROOT = REPO / "tmp" / "adapter_runs"
FIXTURES = tuple(path.name for path in sorted(FIXTURE_DIR.glob("*.cs")))


def _run_fixture(name: str) -> dict[str, Any]:
    fixture = FIXTURE_DIR / name
    result: dict[str, Any] = {
        "name": name,
        "path": str(fixture.relative_to(REPO)),
        "source_status": "available" if fixture.is_file() else "missing",
        "target_status": "blocked",
        "blocked_reason": "converter not invoked by this source-side adapter",
    }
    if not fixture.is_file():
        result["source_message"] = "fixture does not exist"
        return result

    dotnet = shutil.which("dotnet")
    if dotnet is None:
        result.update(
            {
                "compile_status": "blocked",
                "compile_message": "dotnet SDK was not found on PATH",
            }
        )
        return result

    work = TMP_ROOT / fixture.stem
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    (work / "Program.cs").write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    (work / f"{fixture.stem}.csproj").write_text(
        """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net8.0</TargetFramework>
    <ImplicitUsings>disable</ImplicitUsings>
  </PropertyGroup>
</Project>
""",
        encoding="utf-8",
    )

    try:
        build = subprocess.run(
            [dotnet, "build", "-c", "Release", "--nologo"],
            cwd=work,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        result.update(
            {
                "compile_status": "failed",
                "compile_message": "dotnet build timed out",
            }
        )
        return result
    if build.returncode:
        result.update(
            {
                "compile_status": "failed",
                "compile_message": (build.stdout + "\n" + build.stderr)[-4000:],
            }
        )
        return result

    result["compile_status"] = "passed"
    try:
        execution = subprocess.run(
            [dotnet, "run", "-c", "Release", "--no-build", "--nologo"],
            cwd=work,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        result.update(
            {
                "run_status": "failed",
                "run_exit_code": None,
                "run_stdout": "",
                "run_stderr": "dotnet run timed out",
            }
        )
        return result
    result.update(
        {
            "run_status": "passed" if execution.returncode == 0 else "failed",
            "run_exit_code": execution.returncode,
            "run_stdout": execution.stdout[-4000:],
            "run_stderr": execution.stderr[-4000:],
        }
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="csharp adapter")
    parser.add_argument("--list", action="store_true", help="list fixture names")
    parser.add_argument("--run", nargs="*", metavar="FIXTURE", help="run fixtures or ALL")
    parser.add_argument("--json", action="store_true", help="emit structured JSON")
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="run all fixtures and check the adapter result contract",
    )
    args = parser.parse_args(argv)

    if args.list:
        print("\n".join(FIXTURES))
        return 0
    if args.selftest:
        selected = list(FIXTURES)
    elif args.run:
        selected = list(FIXTURES) if len(args.run) == 1 and args.run[0].upper() == "ALL" else args.run
    else:
        parser.error("one of --list, --selftest, or --run is required")
    unknown = sorted(set(selected) - set(FIXTURES))
    if unknown:
        parser.error(f"unknown fixture(s): {', '.join(unknown)}")

    results = [_run_fixture(name) for name in selected]
    if args.selftest:
        required = {"name", "source_status", "target_status"}
        if any(not required <= result.keys() for result in results):
            print("adapter selftest failed: result contract is incomplete")
            return 1
        print("adapter selftest: ok")
        return 0
    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        for result in results:
            print(
                f"{result['name']}: compile={result.get('compile_status', 'blocked')} "
                f"target={result['target_status']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
