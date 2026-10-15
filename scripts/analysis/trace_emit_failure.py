#!/usr/bin/env python3
"""Resolve rustc-style failures back to annotated emission provenance.

This is the mechanical counterpart to reading `// seq:NNNNNN ...` comments by
eye. Given a rustc short-format log and the SQLite provenance store emitted by
`csharp_emitter.py --annotate-rules`, it:

1. parses each failing `path:line:col: error ...` entry
2. opens the named Rust file
3. walks upward to the nearest preceding `// seq:NNNNNN ...` marker
4. looks that sequence up in `tmp/logs/emit-annotate.sqlite3`
5. prints the originating rule/tag, source type/method, and emitted line

Typical use after an annotated emit:

    python3 scripts/analysis/trace_emit_failure.py \
        --rustc-log tmp/logs/issue78-cargo-check.log \
        --annotation-db tmp/logs/emit-annotate.sqlite3 \
        --emitted-root tmp/compile_check
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


def repo_root() -> Path:
    return Path(subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], text=True).strip())


ROOT = repo_root()
RUSTC_LINE = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+):(?P<col>\d+): error(?P<code>\[[A-Z0-9]+\])?: (?P<msg>.*)$"
)
SEQ_LINE = re.compile(r"^\s*//\s+seq:(?P<seq>\d{6})\s+(?P<tag>.+?)\s*$")


@dataclass
class Failure:
    path: str
    line: int
    col: int
    code: str | None
    message: str


@dataclass
class Trace:
    failure: Failure
    source_file: str
    seq: int | None
    tags: list[str]
    module: str | None
    type_name: str | None
    method_name: str | None
    register_name: str | None
    emitted_line: str | None
    marker_line: int | None
    status: str


def parse_failures(path: Path) -> list[Failure]:
    out: list[Failure] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = RUSTC_LINE.match(raw)
        if not m:
            continue
        out.append(Failure(
            path=m.group("path"),
            line=int(m.group("line")),
            col=int(m.group("col")),
            code=m.group("code"),
            message=m.group("msg"),
        ))
    return out


def resolve_source(path_text: str, emitted_root: Path) -> Path:
    p = Path(path_text)
    if p.is_absolute():
        return p
    if p.parts and p.parts[0] == "src":
        return emitted_root / p
    return ROOT / p


def nearest_seq(path: Path, line_no: int) -> tuple[int | None, int | None, list[str], str | None]:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = min(max(line_no - 1, 0), len(lines) - 1)
    for idx in range(start, -1, -1):
        m = SEQ_LINE.match(lines[idx])
        if m:
            seq = int(m.group("seq"))
            tags = [m.group("tag")]
            j = idx - 1
            while j >= 0:
                more = SEQ_LINE.match(lines[j])
                if not more or int(more.group("seq")) != seq:
                    break
                tags.append(more.group("tag"))
                j -= 1
            tags.reverse()
            code_line = None
            k = idx + 1
            while k < len(lines):
                if lines[k].strip() and not lines[k].lstrip().startswith("//"):
                    code_line = lines[k]
                    break
                k += 1
            return seq, idx + 1, tags, code_line
    return None, None, [], None


def fetch_event(con: sqlite3.Connection, seq: int) -> tuple[dict | None, list[str]]:
    row = con.execute(
        "SELECT seq, module, type_name, method_name, register_name, line "
        "FROM emission_event WHERE seq=?",
        (seq,),
    ).fetchone()
    tags = [tag for (_ord, tag) in con.execute(
        "SELECT ord, tag FROM emission_event_tag WHERE seq=? ORDER BY ord",
        (seq,),
    )]
    if row is None:
        return None, tags
    keys = ("seq", "module", "type_name", "method_name", "register_name", "line")
    return dict(zip(keys, row)), tags


def trace_failures(failures: list[Failure], annotation_db: Path | None,
                   emitted_root: Path) -> list[Trace]:
    con = sqlite3.connect(annotation_db) if annotation_db and annotation_db.exists() else None
    out: list[Trace] = []
    try:
        for failure in failures:
            src = resolve_source(failure.path, emitted_root)
            if not src.exists():
                out.append(Trace(
                    failure=failure,
                    source_file=str(src),
                    seq=None,
                    tags=[],
                    module=None,
                    type_name=None,
                    method_name=None,
                    register_name=None,
                    emitted_line=None,
                    marker_line=None,
                    status="source-missing",
                ))
                continue
            seq, marker_line, marker_tags, code_line = nearest_seq(src, failure.line)
            if seq is None:
                out.append(Trace(
                    failure=failure,
                    source_file=str(src),
                    seq=None,
                    tags=[],
                    module=None,
                    type_name=None,
                    method_name=None,
                    register_name=None,
                    emitted_line=None,
                    marker_line=None,
                    status="no-marker",
                ))
                continue
            if con is None:
                out.append(Trace(
                    failure=failure,
                    source_file=str(src),
                    seq=seq,
                    tags=marker_tags,
                    module=Path(src).stem,
                    type_name=None,
                    method_name=None,
                    register_name=None,
                    emitted_line=code_line,
                    marker_line=marker_line,
                    status="comment-only",
                ))
                continue
            event, tags = fetch_event(con, seq)
            if event is None:
                out.append(Trace(
                    failure=failure,
                    source_file=str(src),
                    seq=seq,
                    tags=tags or marker_tags,
                    module=None,
                    type_name=None,
                    method_name=None,
                    register_name=None,
                    emitted_line=code_line,
                    marker_line=marker_line,
                    status="seq-missing",
                ))
                continue
            out.append(Trace(
                failure=failure,
                source_file=str(src),
                seq=seq,
                tags=tags or marker_tags,
                module=event["module"],
                type_name=event["type_name"],
                method_name=event["method_name"],
                register_name=event["register_name"],
                emitted_line=event["line"] or code_line,
                marker_line=marker_line,
                status="ok",
            ))
    finally:
        if con is not None:
            con.close()
    return out


def render_text(traces: list[Trace]) -> str:
    lines: list[str] = []
    for tr in traces:
        fail = tr.failure
        lines.append(f"Failure: {fail.path}:{fail.line}:{fail.col}")
        lines.append(f"  message: {fail.message}")
        lines.append(f"  source file: {tr.source_file}")
        lines.append(f"  status: {tr.status}")
        if tr.seq is not None:
            lines.append(f"  seq: {tr.seq:06d}")
        if tr.marker_line is not None:
            lines.append(f"  marker line: {tr.marker_line}")
        if tr.tags:
            lines.append(f"  tags: {', '.join(tr.tags)}")
        if tr.module:
            lines.append(f"  module: {tr.module}")
        if tr.type_name:
            lines.append(f"  type: {tr.type_name}")
        if tr.method_name:
            lines.append(f"  method: {tr.method_name}")
        if tr.register_name:
            lines.append(f"  register: {tr.register_name}")
        if tr.emitted_line:
            lines.append(f"  emitted line: {tr.emitted_line}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rustc-log", required=True,
                    help="rustc short-format log to resolve")
    ap.add_argument("--annotation-db", default="tmp/logs/emit-annotate.sqlite3",
                    help="SQLite provenance database from --annotate-rules")
    ap.add_argument("--emitted-root", default="tmp/compile_check",
                    help="root of the emitted crate when rustc paths start with src/")
    ap.add_argument("--json", action="store_true",
                    help="print JSON instead of text")
    ap.add_argument("--limit", type=int, default=0,
                    help="maximum failures to report; 0 means all")
    args = ap.parse_args()

    rustc_log = ROOT / args.rustc_log
    annotation_db = None if args.annotation_db == "-" else (ROOT / args.annotation_db)
    emitted_root = ROOT / args.emitted_root

    failures = parse_failures(rustc_log)
    if args.limit > 0:
        failures = failures[:args.limit]
    traces = trace_failures(failures, annotation_db, emitted_root)

    if args.json:
        sys.stdout.write(json.dumps([asdict(t) for t in traces], indent=2) + "\n")
    else:
        sys.stdout.write(render_text(traces))
    return 0


if __name__ == "__main__":
    sys.exit(main())