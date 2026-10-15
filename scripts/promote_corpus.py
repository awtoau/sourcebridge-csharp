#!/usr/bin/env python3
"""Atomically promote a verified scratch corpus to rulesdb/patterns.db."""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
from pathlib import Path


def repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    )
    return Path(result.stdout.strip())


def verify(connection: sqlite3.Connection) -> None:
    run = connection.execute(
        "SELECT config FROM corpus_run ORDER BY id DESC LIMIT 1"
    ).fetchone()
    counts = {
        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("file", "type", "operation")
    }
    if run is None or run[0] != "tree" or any(count == 0 for count in counts.values()):
        raise ValueError("source is not a usable whole-tree corpus")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-db", required=True, type=Path, dest="source")
    args = parser.parse_args()

    root = repo_root()
    source = args.source.resolve()
    destination = (root / "rulesdb" / "patterns.db").resolve()
    if source == destination:
        parser.error("--from-db must be a verified scratch corpus, not the canonical database")
    if not source.is_file():
        parser.error(f"corpus does not exist: {source}")

    temporary = destination.with_suffix(".db.new")
    temporary.unlink(missing_ok=True)
    try:
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as read_connection:
            verify(read_connection)
            with sqlite3.connect(temporary) as write_connection:
                read_connection.backup(write_connection)
        with sqlite3.connect(f"file:{temporary}?mode=ro", uri=True) as promoted:
            verify(promoted)
        os.replace(temporary, destination)
    except (OSError, sqlite3.Error, ValueError) as error:
        temporary.unlink(missing_ok=True)
        parser.error(str(error))
    print(f"promoted {source.relative_to(root)} to rulesdb/patterns.db")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
