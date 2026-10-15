"""GitHub `owner/name` slug of this repo, derived from the `origin` remote.

Single source: scripts must import this, never retype the slug.
"""

from __future__ import annotations

import re
import subprocess


def repo_slug() -> str:
    url = subprocess.run(["git", "remote", "get-url", "origin"],
                         capture_output=True, text=True, check=True).stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    if not m:
        raise RuntimeError(f"origin is not a github.com remote: {url!r}")
    return m.group(1)


def repo_name() -> str:
    return repo_slug().split("/", 1)[1]


if __name__ == "__main__":
    print(repo_slug())
