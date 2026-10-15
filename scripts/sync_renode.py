#!/usr/bin/env python3
"""Pin a Renode release worktree and ingest a verified scratch corpus.

Run through ``python3.15t scripts/dev.py sync-renode --tag vX.Y.Z``. The
canonical corpus is never an output path; review the scratch corpus first and
pass ``--activate`` only when it is ready to become the local source checkout.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path


def repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    )
    return Path(result.stdout.strip())


def read_env(root: Path, key: str) -> str | None:
    env_file = root / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return None


def write_env(root: Path, key: str, value: Path) -> None:
    env_file = root / ".env"
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    lines = [line for line in lines if not line.startswith(f"{key}=")]
    lines.append(f"{key}={value}")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(log: logging.Logger, args: list[str], **kwargs: object) -> None:
    log.info("+ %s", " ".join(args))
    subprocess.run(args, check=True, **kwargs)


def tfm_from_build_script(worktree: Path) -> str:
    match = re.search(
        r'^TFM="([^"]+)"', (worktree / "build.sh").read_text(encoding="utf-8"), re.M
    )
    if not match:
        raise RuntimeError('build.sh no longer declares TFM="..."')
    return match.group(1)


def verify_corpus(db: Path, log_file: Path) -> None:
    uri = f"file:{db}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        run_row = connection.execute(
            "SELECT config, renode_commit FROM corpus_run ORDER BY id DESC LIMIT 1"
        ).fetchone()
        file_count = connection.execute("SELECT COUNT(*) FROM file").fetchone()[0]
        type_count = connection.execute("SELECT COUNT(*) FROM type").fetchone()[0]
    metadata_matches = re.findall(r"(\d+) metadata refs", log_file.read_text(encoding="utf-8"))
    metadata_references = int(metadata_matches[-1]) if metadata_matches else 0
    if run_row is None or run_row[0] != "tree":
        raise RuntimeError("scratch database has no canonical whole-tree corpus run")
    if file_count == 0 or type_count == 0 or metadata_references == 0:
        raise RuntimeError(
            "scratch database is unusable: expected files, types, and resolved metadata references"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="upstream tag, e.g. v1.17.0")
    parser.add_argument(
        "--store", help="shared Renode Git store (defaults to RENODE_STORE in environment or .env)"
    )
    parser.add_argument("--db", help="scratch corpus path (defaults to tmp/patterns-<tag>.db)")
    parser.add_argument(
        "--activate",
        action="store_true",
        help="write RENODE_SRC to .env after the scratch corpus passes verification",
    )
    args = parser.parse_args()

    root = repo_root()
    logs = root / "tmp" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("sync_renode")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    for handler in (
        logging.FileHandler(logs / "sync_renode.log", mode="w", encoding="utf-8"),
        logging.StreamHandler(),
    ):
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

    store_value = args.store or os.environ.get("RENODE_STORE") or read_env(root, "RENODE_STORE")
    if not store_value:
        logger.error("RENODE_STORE is required (--store, environment, or .env)")
        return 1
    store = Path(store_value).resolve()
    if not (store / ".git").exists():
        logger.error("not a Git store: %s", store)
        return 1

    worktree = root / "tmp" / f"renode-{args.tag}"
    db = (root / (args.db or f"tmp/patterns-{args.tag}.db")).resolve()
    canonical = (root / "rulesdb" / "patterns.db").resolve()
    if db == canonical:
        logger.error("refusing to overwrite canonical rulesdb/patterns.db")
        return 1
    db.parent.mkdir(parents=True, exist_ok=True)

    try:
        with (logs / "sync_renode.log").open("a", encoding="utf-8") as output:
            run(logger, ["git", "-C", str(store), "fetch", "--no-tags", "origin", "tag", args.tag],
                stdout=output, stderr=subprocess.STDOUT)
            target = subprocess.run(
                ["git", "-C", str(store), "rev-parse", f"{args.tag}^{{commit}}"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            if worktree.exists():
                actual = subprocess.run(
                    ["git", "-C", str(worktree), "rev-parse", "HEAD"],
                    check=True, capture_output=True, text=True,
                ).stdout.strip()
                if actual != target:
                    raise RuntimeError(
                        f"existing worktree {worktree} is {actual[:12]}, not {args.tag} ({target[:12]})"
                    )
            else:
                run(logger, ["git", "-C", str(store), "worktree", "add", "--detach",
                             str(worktree), target], stdout=output, stderr=subprocess.STDOUT)
            run(logger, ["git", "-C", str(worktree), "submodule", "update", "--init",
                         "--recursive", "--", "src/Infrastructure"],
                stdout=output, stderr=subprocess.STDOUT)

            tfm = tfm_from_build_script(worktree)
            (worktree / "Directory.Build.targets").write_text(
                "<Project>\n  <PropertyGroup>\n"
                f"    <TargetFrameworks>{tfm}</TargetFrameworks>\n"
                "    <EnableWindowsTargeting>true</EnableWindowsTargeting>\n"
                "  </PropertyGroup>\n</Project>\n",
                encoding="utf-8",
            )
            project = worktree / "src" / "Infrastructure" / "src" / "Infrastructure.csproj"
            run(logger, ["dotnet", "restore", str(project)], stdout=output, stderr=subprocess.STDOUT)
            run(logger, ["dotnet", "build", "frontend/RenodeIngest", "--no-restore"],
                cwd=root, stdout=output, stderr=subprocess.STDOUT)
            temporary_db = db.with_suffix(f"{db.suffix}.new")
            temporary_db.unlink(missing_ok=True)
            run(logger, ["dotnet", "run", "--no-build", "--project", "frontend/RenodeIngest",
                         "--", "--db", str(temporary_db)],
                cwd=root, env={**os.environ, "RENODE_SRC": str(worktree)},
                stdout=output, stderr=subprocess.STDOUT)
        verify_corpus(temporary_db, logs / "sync_renode.log")
        shutil.move(temporary_db, db)
    except (OSError, RuntimeError, sqlite3.Error, subprocess.CalledProcessError) as error:
        logger.error("sync failed: %s", error)
        return 1

    logger.info("verified scratch corpus: %s", db.relative_to(root))
    if args.activate:
        write_env(root, "RENODE_SRC", worktree)
        logger.info("updated RENODE_SRC in .env: %s", worktree.relative_to(root))
    else:
        logger.info("RENODE_SRC is unchanged; review and promote the scratch corpus before --activate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
