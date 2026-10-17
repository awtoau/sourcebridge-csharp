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
    res = {
        "name": fname,
        "path": str(p),
        "source_ok": p.exists(),
        "target_status": "blocked",
        "blocked_reason": "converter not invoked; adapter only performs source-side validation",
    }
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
        # clean previous run by removing the per-fixture temporary directory entirely
        # This is explicit and avoids broad exception suppression during cleanup.
        try:
            shutil.rmtree(work)
        except FileNotFoundError:
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
                    "message": "dotnet build timed out",
                    "blocked_reason": "source build timed out; no target produced"})
        return res

    if proc.returncode == 0:
        res.update({"compile_supported": True, "compile_ok": True,
                    "message": "build ok"})
        # Run the built fixture (source-side execution). We do not invoke any
        # converter or emitter here; record run output and then mark target as
        # blocked because no generic converter has been invoked yet.
        try:
            run_proc = subprocess.run([dotnet, "run", "-c", "Release", "--no-build"],
                                      cwd=work, capture_output=True, text=True, check=False,
                                      timeout=10)
            res.update({
                "run_exit_code": run_proc.returncode,
                "run_stdout": run_proc.stdout[:4000],
                "run_stderr": run_proc.stderr[:4000],
            })
        except subprocess.TimeoutExpired:
            res.update({"run_exit_code": None, "run_stdout": "",
                        "run_stderr": "run timed out"})
    else:
        # capture stderr/stdout messages for evidence
        msg = proc.stdout + "\n" + proc.stderr
        # Truncate for safety
        res.update({"compile_supported": True, "compile_ok": False,
                    "message": msg[:4000],
                    "blocked_reason": "build failed; no target produced"})
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
    ap.add_argument("--selftest", action="store_true", help="Run internal self-test: validates result shape and fixture selection")
    args = ap.parse_args(argv[1:])

    if args.list:
        list_fixtures()
        return 0

    if args.selftest:
        # Deterministic validation: run ALL fixtures and assert result shape
        results = run_all()
        ok = True
        if len(results) != len(FIXTURES):
            print("selftest failed: result count mismatch", file=sys.stderr)
            ok = False
        for r in results:
            for key in ("name", "compile_supported", "compile_ok", "target_status"):
                if key not in r:
                    print(f"selftest failed: missing key {key} in result for {r.get('name')}", file=sys.stderr)
                    ok = False
        if ok:
            print("selftest: ok")
            return 0
        else:
            return 1

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
            print(f"{r['name']}: compile_supported={r['compile_supported']}, compile_ok={r['compile_ok']}, target_status={r.get('target_status')}")
            if not r['compile_ok']:
                print("  message:")
                for line in str(r.get('message','')).splitlines():
                    print("   ", line)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
