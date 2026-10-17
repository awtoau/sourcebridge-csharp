#!/usr/bin/env python3
"""Emit the C# pack's Roslyn-focused toolchain currency report."""

from __future__ import annotations

import sys

from toolchain_report import main as report_main


if __name__ == "__main__":
    raise SystemExit(report_main(["--focus", "roslyn", *sys.argv[1:]]))
