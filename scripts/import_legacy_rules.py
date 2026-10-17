#!/usr/bin/env python3
"""Import tracked legacy rule JSON as provenance-preserving, unvalidated data.

This deliberately validates only JSON syntax.  It does not assess whether any
rule is correct for a target or suitable for conversion.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RULE_GLOB = "rulesdb/rules/*.json"
OUTPUT = ROOT / "rulesdb" / "imports" / "legacy-csharp-rules-v1.json"
STATUS = "unvalidated-legacy-import"
SOURCE_REPOSITORY = "awtoau/csharp2rust"

CLASSIFICATIONS = {
    "rulesdb/rules/bug_rules.json": ("project", "renode-source-defect-rules"),
    "rulesdb/rules/constructor.json": ("language", "generic-csharp-to-rust"),
    "rulesdb/rules/csharp_core.json": ("language", "generic-csharp-to-rust"),
    "rulesdb/rules/object_graph.json": ("language", "generic-csharp-to-rust"),
    "rulesdb/rules/offset_switch.json": ("project", "renode-offset-switch-rules"),
    "rulesdb/rules/register_dsl.json": ("project", "renode-register-dsl-rules"),
}


def tracked_rule_paths(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--", RULE_GLOB],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return [root / line for line in result.stdout.splitlines() if line]


def source_revision(root: Path) -> tuple[str, str]:
    provenance = json.loads(
        (root / "docs" / "legacy-rule-import.json").read_text(encoding="utf-8")
    )
    revision = provenance.get("legacy_tip")
    if revision:
        return revision, "docs/legacy-rule-import.json:legacy_tip"

    for source in (
        root.parent / "sourcebridge-csharp" / "csharp2rust",
        root.parent / "csharp2rust",
    ):
        if source.is_dir():
            result = subprocess.run(
                ["git", "-C", source, "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip(), "sourcebridge-csharp/csharp2rust HEAD"
    raise FileNotFoundError("no csharp2rust checkout available for source provenance")


def build_manifest(root: Path) -> dict[str, object]:
    revision, revision_source = source_revision(root)
    paths = tracked_rule_paths(root)
    source_paths = {path.relative_to(root).as_posix() for path in paths}
    if source_paths != set(CLASSIFICATIONS):
        raise ValueError(
            "every tracked legacy rule requires an explicit layer/classification: "
            f"tracked={sorted(source_paths)} classified={sorted(CLASSIFICATIONS)}"
        )
    records = []
    for path in paths:
        relative_path = path.relative_to(root).as_posix()
        layer, classification = CLASSIFICATIONS[relative_path]
        raw = path.read_bytes()
        records.append({
            "source_repository": SOURCE_REPOSITORY,
            "source_revision": revision,
            "source_revision_provenance": revision_source,
            "source_path": relative_path,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "layer": layer,
            "classification": classification,
            "status": STATUS,
            "original_payload": json.loads(raw),
        })

    return {
        "schema_version": 1,
        "importer": "scripts/import_legacy_rules.py",
        "import_status": STATUS,
        "records": records,
    }


def main() -> int:
    manifest = build_manifest(ROOT)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"imported {len(manifest['records'])} tracked rule payloads -> "
          f"{OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
