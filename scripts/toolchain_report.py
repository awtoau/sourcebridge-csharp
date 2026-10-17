#!/usr/bin/env python3
"""Emit the Sourcebridge C# pack toolchain currency report.

The report records host-installed .NET facts, project declarations, restored
NuGet facts, and an explicitly bounded latest-version observation.  It does not
turn any of those observations into a conversion-capability claim.

Examples:
    python3 scripts/dev.py toolchain-report
    python3 scripts/dev.py roslyn-report
    python3 scripts/dev.py toolchain-report --no-network
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Callable, Iterable


REPO = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT = REPO / "frontend" / "RenodeIngest" / "RenodeIngest.csproj"
REPORT_TYPE = "sourcebridge.toolchain_currency"
SCHEMA_VERSION = 1
NUGET_FLAT_CONTAINER = "https://api.nuget.org/v3-flatcontainer"
_VERSION_PARTS = re.compile(r"^\d+(?:\.\d+){0,3}(?:[-+].*)?$")

CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


class ToolchainReportError(ValueError):
    """Raised when a pack toolchain report cannot be collected."""


@dataclass(frozen=True)
class PackageDeclaration:
    package_id: str
    version: str | None
    version_source: str
    declared_in: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.package_id,
            "version": self.version,
            "version_source": self.version_source,
            "declared_in": self.declared_in,
        }


def _run(
    argv: list[str],
    *,
    timeout: float = 10,
    runner: CommandRunner | None = None,
) -> subprocess.CompletedProcess[str]:
    if runner is not None:
        return runner(argv)
    return subprocess.run(
        argv,
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return path.as_posix()


def _xml_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _property_value(element: ET.Element, name: str) -> str | None:
    for child in element:
        if _xml_name(child.tag) == name and child.text:
            value = child.text.strip()
            if value:
                return value
    return None


def _central_versions(project: Path) -> dict[str, str]:
    versions: dict[str, str] = {}
    current = project.parent.resolve()
    repo = REPO.resolve()
    stop = repo if repo == current or repo in current.parents else None
    while True:
        props = current / "Directory.Packages.props"
        if props.is_file():
            try:
                root = ET.fromstring(props.read_text(encoding="utf-8"))
            except (OSError, ET.ParseError):
                root = None
            if root is not None:
                for element in root.iter():
                    if _xml_name(element.tag) != "PackageVersion":
                        continue
                    package_id = element.attrib.get("Include") or element.attrib.get("Update")
                    version = (
                        element.attrib.get("Version")
                        or _property_value(element, "Version")
                    )
                    if package_id and version:
                        versions.setdefault(package_id.lower(), version)
        if current == stop or current.parent == current:
            break
        current = current.parent
    return versions


def _global_sdk_declaration(project: Path) -> dict[str, Any]:
    current = project.parent.resolve()
    repo = REPO.resolve()
    stop = repo if repo == current or repo in current.parents else None
    while True:
        candidate = current / "global.json"
        if candidate.is_file():
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                return {
                    "status": "unavailable",
                    "path": _relative(candidate),
                    "reason": f"cannot read global.json: {error}",
                }
            sdk = payload.get("sdk", {}) if isinstance(payload, dict) else {}
            if not isinstance(sdk, dict):
                sdk = {}
            return {
                "status": "available",
                "path": _relative(candidate),
                "version": sdk.get("version"),
                "roll_forward": sdk.get("rollForward"),
                "allow_prerelease": sdk.get("allowPrerelease"),
            }
        if current == stop or current.parent == current:
            break
        current = current.parent
    return {"status": "not_present"}


def discover_declared(project: Path) -> dict[str, Any]:
    """Read target frameworks and PackageReference declarations from a csproj."""

    project = project.resolve()
    if not project.is_file():
        raise ToolchainReportError(f"{project}: project file does not exist")
    try:
        root = ET.fromstring(project.read_text(encoding="utf-8"))
    except (OSError, ET.ParseError) as error:
        raise ToolchainReportError(f"{project}: cannot parse project: {error}") from error

    frameworks: list[str] = []
    for element in root.iter():
        if _xml_name(element.tag) not in {"TargetFramework", "TargetFrameworks"}:
            continue
        if not element.text:
            continue
        frameworks.extend(
            item.strip() for item in element.text.split(";") if item.strip()
        )

    central = _central_versions(project)
    declarations: list[PackageDeclaration] = []
    for element in root.iter():
        if _xml_name(element.tag) != "PackageReference":
            continue
        package_id = element.attrib.get("Include") or element.attrib.get("Update")
        if not package_id:
            continue
        version = (
            element.attrib.get("Version")
            or element.attrib.get("VersionOverride")
            or _property_value(element, "Version")
        )
        source = "project" if version else "unspecified"
        if version is None:
            version = central.get(package_id.lower())
            if version is not None:
                source = "central"
        declarations.append(
            PackageDeclaration(
                package_id=package_id,
                version=version,
                version_source=source,
                declared_in=_relative(project),
            )
        )
    declarations.sort(key=lambda item: (item.package_id.lower(), item.package_id))
    return {
        "project": _relative(project),
        "sdk": _global_sdk_declaration(project),
        "target_frameworks": sorted(set(frameworks)),
        "packages": [item.as_dict() for item in declarations],
    }


def _parse_sdk_lines(stdout: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for line in stdout.splitlines():
        match = re.match(r"^\s*([^\s]+)\s+\[(.+)\]\s*$", line)
        if match:
            records.append({"version": match.group(1), "path": match.group(2)})
    return records


def _parse_runtime_lines(stdout: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for line in stdout.splitlines():
        match = re.match(r"^\s*(\S+)\s+(\S+)\s+\[(.+)\]\s*$", line)
        if match:
            records.append(
                {
                    "name": match.group(1),
                    "version": match.group(2),
                    "path": match.group(3),
                }
            )
    return records


def discover_installed_dotnet(
    *,
    executable: str | None = None,
    runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Record the SDK and runtimes selected by the host, without interpretation."""

    dotnet = executable or shutil.which("dotnet")
    if not dotnet:
        return {
            "status": "unavailable",
            "reason": "dotnet executable was not found on PATH",
        }
    path = shutil.which(dotnet) or dotnet
    try:
        version = _run([path, "--version"], runner=runner).stdout.strip()
        sdks_result = _run([path, "--list-sdks"], runner=runner)
        runtimes_result = _run([path, "--list-runtimes"], runner=runner)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"status": "unavailable", "path": path, "reason": str(error)}
    if not version:
        return {
            "status": "unavailable",
            "path": path,
            "reason": "dotnet --version returned no version",
        }
    return {
        "status": "available",
        "path": path,
        "selected_version": version,
        "sdks": _parse_sdk_lines(sdks_result.stdout),
        "runtimes": _parse_runtime_lines(runtimes_result.stdout),
    }


def _asset_package_records(
    assets: dict[str, Any],
    declarations: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    direct_ids = {
        str(item["id"]).lower()
        for item in declarations
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    records: list[dict[str, Any]] = []
    libraries = assets.get("libraries", {})
    if not isinstance(libraries, dict):
        return [], sorted(direct_ids)
    for key, metadata in libraries.items():
        if not isinstance(key, str) or not isinstance(metadata, dict):
            continue
        package_id, separator, version = key.partition("/")
        if not separator or metadata.get("type") != "package":
            continue
        record: dict[str, Any] = {
            "id": package_id,
            "version": version,
            "direct": package_id.lower() in direct_ids,
        }
        for field in ("path", "sha512"):
            if isinstance(metadata.get(field), str):
                record[field] = metadata[field]
        records.append(record)
    records.sort(key=lambda item: (item["id"].lower(), item["version"]))
    resolved_ids = {item["id"].lower() for item in records}
    missing = sorted(direct_ids - resolved_ids)
    return records, missing


def discover_resolved(
    project: Path,
    declared: dict[str, Any],
    *,
    assets_path: Path | None = None,
) -> dict[str, Any]:
    assets = (assets_path or project.parent / "obj" / "project.assets.json").resolve()
    if not assets.is_file():
        return {
            "status": "unavailable",
            "assets_file": _relative(assets),
            "packages": [],
            "reason": "assets file was not found; run dotnet restore",
        }
    try:
        payload = json.loads(assets.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {
            "status": "unavailable",
            "assets_file": _relative(assets),
            "packages": [],
            "reason": f"cannot read assets file: {error}",
        }
    if not isinstance(payload, dict):
        return {
            "status": "unavailable",
            "assets_file": _relative(assets),
            "packages": [],
            "reason": "assets file is not a JSON object",
        }
    packages, missing = _asset_package_records(payload, declared.get("packages", []))
    result: dict[str, Any] = {
        "status": "available",
        "assets_file": _relative(assets),
        "packages": packages,
    }
    if missing:
        result["missing_declared_packages"] = missing
    return result


def _version_key(version: str) -> tuple[tuple[int, ...], int, str]:
    core, separator, suffix = version.partition("-")
    numbers = tuple(int(part) for part in core.split(".") if part.isdigit())
    return numbers, 0 if not separator else -1, suffix


def fetch_latest_version(package_id: str, *, timeout: float = 3.0) -> str:
    """Fetch the highest stable NuGet version for one package ID."""

    url = f"{NUGET_FLAT_CONTAINER}/{package_id.lower()}/index.json"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "sourcebridge-toolchain-report/1"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    versions = payload.get("versions", []) if isinstance(payload, dict) else []
    stable = [
        version
        for version in versions
        if isinstance(version, str)
        and _VERSION_PARTS.fullmatch(version)
        and "-" not in version
    ]
    if not stable:
        raise ToolchainReportError(f"NuGet returned no stable versions for {package_id}")
    return max(stable, key=_version_key)


def discover_latest(
    declared: dict[str, Any],
    *,
    network: bool = True,
    fetcher: Callable[[str], str] = fetch_latest_version,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for package in declared.get("packages", []):
        package_id = package["id"]
        record: dict[str, Any] = {"id": package_id}
        if not network:
            record.update(
                {
                    "status": "not_queried",
                    "version": None,
                    "reason": "network discovery disabled",
                }
            )
        else:
            try:
                record.update({"status": "available", "version": fetcher(package_id)})
            except (OSError, ToolchainReportError, urllib.error.URLError, ValueError) as error:
                record.update(
                    {
                        "status": "unavailable",
                        "version": None,
                        "reason": str(error),
                    }
                )
        records.append(record)
    return {
        "source": NUGET_FLAT_CONTAINER,
        "packages": records,
        "status": (
            "available"
            if records and all(item["status"] == "available" for item in records)
            else "partial"
            if any(item["status"] == "available" for item in records)
            else "unavailable"
            if records
            else "not_applicable"
        ),
    }


def _is_roslyn(package_id: str) -> bool:
    lowered = package_id.lower()
    return lowered.startswith("microsoft.codeanalysis") or lowered.startswith(
        "microsoft.net.compilers"
    )


def _filter_roslyn(packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in packages if _is_roslyn(str(item.get("id", "")))]


def _load_proposals(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ToolchainReportError(f"{path}: invalid upgrade evidence: {error}") from error
    proposals = payload.get("upgrade_proposals") if isinstance(payload, dict) else payload
    if not isinstance(proposals, list):
        raise ToolchainReportError(f"{path}: upgrade proposals must be a JSON list")
    for index, proposal in enumerate(proposals):
        _validate_proposal(proposal, f"{path}: upgrade_proposals[{index}]")
    return proposals


def _validate_proposal(proposal: Any, label: str) -> None:
    required = {
        "id",
        "component",
        "from",
        "to",
        "compatibility_evidence",
        "validation",
        "decision",
    }
    if not isinstance(proposal, dict) or required - set(proposal):
        raise ToolchainReportError(
            f"{label}: compatibility, validation, and adopt/defer evidence are required"
        )
    if not all(isinstance(proposal[field], str) and proposal[field] for field in
               ("id", "component", "from", "to")):
        raise ToolchainReportError(f"{label}: proposal identity fields are required")
    compatibility = proposal["compatibility_evidence"]
    if not isinstance(compatibility, list) or not compatibility:
        raise ToolchainReportError(f"{label}: compatibility_evidence is required")
    if any(not isinstance(item, dict) or not item for item in compatibility):
        raise ToolchainReportError(
            f"{label}: compatibility_evidence entries must be non-empty objects"
        )
    validation = proposal["validation"]
    decision = proposal["decision"]
    if (
        not isinstance(validation, dict)
        or not validation.get("command")
        or not validation.get("result")
        or not isinstance(decision, dict)
        or decision.get("status") not in {"adopt", "defer"}
        or not decision.get("evidence")
    ):
        raise ToolchainReportError(
            f"{label}: validation result and explicit adopt/defer evidence are required"
        )


def build_report(
    project: Path = DEFAULT_PROJECT,
    *,
    focus: str | None = None,
    network: bool = True,
    proposals_path: Path | None = None,
    runner: CommandRunner | None = None,
    latest_fetcher: Callable[[str], str] = fetch_latest_version,
) -> dict[str, Any]:
    project = project.resolve()
    declared = discover_declared(project)
    installed = discover_installed_dotnet(runner=runner)
    resolved = discover_resolved(project, declared)
    if focus == "roslyn":
        declared = {
            **declared,
            "packages": _filter_roslyn(declared["packages"]),
        }
    latest = discover_latest(declared, network=network, fetcher=latest_fetcher)
    if focus == "roslyn":
        resolved = {
            **resolved,
            "packages": _filter_roslyn(resolved.get("packages", [])),
        }
        latest = {
            **latest,
            "packages": _filter_roslyn(latest.get("packages", [])),
            "status": (
                latest["status"] if latest.get("packages") else "not_applicable"
            ),
        }
    proposals = _load_proposals(proposals_path)
    return {
        "schema_version": SCHEMA_VERSION,
        "report_type": REPORT_TYPE,
        "pack": {"id": "sourcebridge-csharp", "kind": "frontend"},
        "scope": {
            "project": _relative(project),
            "focus": focus or "all",
        },
        "observations": {
            "installed": {"dotnet": installed},
            "declared": declared,
            "resolved": resolved,
            "latest": latest,
        },
        "conversion_capability": {
            "status": "not_claimed",
            "reason": (
                "toolchain availability and package currency do not establish "
                "source conversion capability"
            ),
        },
        "upgrade_proposals": proposals,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="toolchain-report", allow_abbrev=False)
    parser.add_argument(
        "--project",
        type=Path,
        default=DEFAULT_PROJECT,
        help="C# project to inspect (default: frontend/RenodeIngest/RenodeIngest.csproj)",
    )
    parser.add_argument(
        "--no-network",
        action="store_true",
        help="record latest NuGet discovery as not_queried",
    )
    parser.add_argument(
        "--proposals",
        type=Path,
        help="JSON upgrade proposals with compatibility/validation/adopt-defer evidence",
    )
    parser.add_argument("--output", type=Path, help="also save the JSON report here")
    parser.add_argument("--pretty", action="store_true", help="indent JSON output")
    parser.add_argument(
        "--focus",
        choices=("all", "roslyn"),
        default="all",
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = build_report(
            args.project,
            focus=None if args.focus == "all" else args.focus,
            network=not args.no_network,
            proposals_path=args.proposals,
        )
        encoded = json.dumps(
            report,
            indent=2 if args.pretty else None,
            sort_keys=True,
            separators=None if args.pretty else (",", ":"),
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded + "\n", encoding="utf-8")
        print(encoded)
        return 0
    except (OSError, ToolchainReportError, subprocess.TimeoutExpired) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
