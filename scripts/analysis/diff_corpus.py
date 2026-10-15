#!/usr/bin/env python3
"""Compare two corpus databases without modifying either input.

Run through ``python3.15t scripts/dev.py diff-corpus --old OLD --new NEW``.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from pathlib import Path


def repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    )
    return Path(result.stdout.strip())


def tables(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def count(connection: sqlite3.Connection, table: str) -> int:
    return connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]


def main() -> int:
    root = repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", default=root / "rulesdb" / "patterns.db", type=Path)
    parser.add_argument("--new", required=True, type=Path)
    parser.add_argument("--json", default=root / "tmp" / "diff_corpus.json", type=Path)
    args = parser.parse_args()
    if not args.old.is_file() or not args.new.is_file():
        parser.error("--old and --new must name existing corpus databases")

    with sqlite3.connect(f"file:{args.old}?mode=ro", uri=True) as old, sqlite3.connect(
        f"file:{args.new}?mode=ro", uri=True
    ) as new:
        old_tables, new_tables = tables(old), tables(new)
        required = {"corpus_run", "file", "type", "member", "method"}
        missing = sorted(required - old_tables | required - new_tables)
        if missing:
            parser.error(f"corpus schema missing required table(s): {', '.join(missing)}")
        counts = {
            table: (
                count(old, table) if table in old_tables else None,
                count(new, table) if table in new_tables else None,
            )
            for table in sorted(old_tables | new_tables)
        }
        old_files = dict(old.execute("SELECT path, sha256 FROM file"))
        new_files = dict(new.execute("SELECT path, sha256 FROM file"))
        old_types = dict(old.execute("SELECT key, name FROM type"))
        new_types = dict(new.execute("SELECT key, name FROM type"))

    files_added = sorted(new_files.keys() - old_files.keys())
    files_removed = sorted(old_files.keys() - new_files.keys())
    files_changed = sorted(
        path for path in old_files.keys() & new_files.keys() if old_files[path] != new_files[path]
    )
    types_added = sorted(new_types.keys() - old_types.keys())
    types_removed = sorted(old_types.keys() - new_types.keys())
    result = {
        "counts": counts,
        "files_added": files_added,
        "files_removed": files_removed,
        "files_changed": files_changed,
        "types_added": types_added,
        "types_removed": types_removed,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"files: +{len(files_added)} -{len(files_removed)} changed {len(files_changed)}; "
        f"types: +{len(types_added)} -{len(types_removed)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
