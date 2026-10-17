#!/usr/bin/env python3
"""Minimal pack adapter for C# -> Rust differential test foundation.

Run: python3 packs/adapter/adapter.py --list
     python3 packs/adapter/adapter.py --run ALL

This intentionally performs only source-side validation (compilation) when the
`dotnet` SDK is present. If not present, it emits explicit blocked evidence
and does not attempt conversion or touch emitted artifacts.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO / "packs" / "adapter" / "fixtures"
TMP_ROOT = REPO / "tmp" / "adapter_runs"

FIXTURES = [p.name for p in sorted(FIXTURE_DIR.glob("*.cs"))]


def list_fixtures() -> None:
    print("Available fixtures:")
    for f in FIXTURES:
        print(" -", f)


def run_fixture(fname: str) -> dict:
    """Run source-side validation for a single fixture.

    Returns a result dict with fields:
      name, path, source_ok, compile_supported, compile_ok, message
    """
    p = FIXTURE_DIR / fname
    res = {"name": fname, "path": str(p), "source_ok": p.exists()}
    if not p.exists():
        res.update({"compile_supported": False, "compile_ok": False,
                    "message": "fixture missing"})
        return res

    dotnet = shutil.which("dotnet")
    if not dotnet:
        # Blocked: cannot attempt compile without SDK
        res.update({"compile_supported": False, "compile_ok": False,
                    "message": "blocked: dotnet SDK missing"})
        return res

    # Create a temporary project under REPO/tmp/adapter_runs/<name>
    work = TMP_ROOT / fname.replace(".cs", "")
    if work.exists():
        # clean previous run
        for p2 in work.glob("**/*"):
            try:
                if p2.is_file():
                    p2.unlink()
            except Exception:
                pass
    work.mkdir(parents=True, exist_ok=True)

    # Create minimal csproj
    csproj = work / (work.name + ".csproj")
    csproj.write_text("""<Project Sdk=\"Microsoft.NET.Sdk\">\n  <PropertyGroup>\n    <OutputType>Exe</OutputType>\n    <TargetFramework>net8.0</TargetFramework>\n    <ImplicitUsings>disable</ImplicitUsings>\n  </PropertyGroup>\n</Project>\n""")

    # Copy fixture into Program.cs
    dest = work / "Program.cs"
    dest.write_text(p.read_text())

    # Attempt dotnet build (restore should be fast for minimal project)
    try:
        proc = subprocess.run([dotnet, "build", "-c", "Release"],
                              cwd=work, capture_output=True, text=True, check=False,
                              timeout=60)
    except subprocess.TimeoutExpired:
        res.update({"compile_supported": True, "compile_ok": False,
                    "message": "dotnet build timed out"})
        return res

    if proc.returncode == 0:
        res.update({"compile_supported": True, "compile_ok": True,
                    "message": "build ok"})
    else:
        # capture stderr/stdout messages for evidence
        msg = proc.stdout + "\n" + proc.stderr
        # Truncate for safety
        res.update({"compile_supported": True, "compile_ok": False,
                    "message": msg[:4000]})
    return res


def run_all() -> list:
    results = []
    for f in FIXTURES:
        print(f"Running {f} ...", file=sys.stderr)
        r = run_fixture(f)
        results.append(r)
    return results


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--run", nargs="*", default=[],
                    help="Run named fixture(s) or ALL")
    ap.add_argument("--json", action="store_true", help="emit JSON result")
    args = ap.parse_args(argv[1:])

    if args.list:
        list_fixtures()
        return 0

    to_run = args.run
    if not to_run:
        print("Nothing to run. Use --list to see fixtures or --run ALL", file=sys.stderr)
        return 2

    if len(to_run) == 1 and to_run[0].upper() == "ALL":
        results = run_all()
    else:
        results = []
        for name in to_run:
            if name not in FIXTURES:
                print(f"unknown fixture: {name}", file=sys.stderr)
                return 2
            results.append(run_fixture(name))

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            print(f"{r['name']}: compile_supported={r['compile_supported']}, compile_ok={r['compile_ok']}")
            if not r['compile_ok']:
                print("  message:")
                for line in str(r['message']).splitlines():
                    print("   ", line)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
