#!/usr/bin/env python3
"""Emit the C# pack's Roslyn-focused toolchain currency report."""

from __future__ import annotations

import sys

from toolchain_report import main as report_main


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if any(
        argument == "--focus" or argument.startswith("--focus=")
        for argument in arguments
    ):
        print(
            "roslyn-report fixes --focus roslyn; do not pass --focus",
            file=sys.stderr,
        )
        return 2
    return report_main(["--focus", "roslyn", *arguments])


if __name__ == "__main__":
    raise SystemExit(main())
