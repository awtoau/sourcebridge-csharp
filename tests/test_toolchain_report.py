from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from toolchain_report import (  # noqa: E402
    DEFAULT_PROJECT,
    build_report,
    discover_declared,
    discover_latest,
    discover_resolved,
    _validate_proposal,
)
from roslyn_report import main as roslyn_report_main  # noqa: E402


class ToolchainReportTests(unittest.TestCase):
    def test_central_package_props_supply_missing_declaration_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "src" / "Example.csproj"
            project.parent.mkdir(parents=True)
            (root / "Directory.Packages.props").write_text(
                """<Project>
  <ItemGroup>
    <PackageVersion Include="Central.Package" Version="2.3.4" />
  </ItemGroup>
</Project>
""",
                encoding="utf-8",
            )
            project.write_text(
                """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><TargetFramework>net9.0</TargetFramework></PropertyGroup>
  <ItemGroup><PackageReference Include="Central.Package" /></ItemGroup>
</Project>
""",
                encoding="utf-8",
            )

            declared = discover_declared(project)

        self.assertEqual(declared["packages"][0]["version"], "2.3.4")
        self.assertEqual(declared["packages"][0]["version_source"], "central")

    def test_declared_and_resolved_package_facts_are_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "frontend" / "Example.csproj"
            project.parent.mkdir(parents=True)
            project.write_text(
                """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup><TargetFramework>net9.0</TargetFramework></PropertyGroup>
  <ItemGroup>
    <PackageReference Include="Microsoft.CodeAnalysis.CSharp.Workspaces" Version="4.11.0" />
    <PackageReference Include="Example.Transitive" />
  </ItemGroup>
</Project>
""",
                encoding="utf-8",
            )
            assets = project.parent / "obj" / "project.assets.json"
            assets.parent.mkdir()
            assets.write_text(
                json.dumps(
                    {
                        "libraries": {
                            "Microsoft.CodeAnalysis.CSharp.Workspaces/4.11.0": {
                                "type": "package",
                                "sha512": "sha",
                            },
                            "Example.Transitive/1.2.3": {
                                "type": "package",
                                "path": "example.transitive/1.2.3",
                            },
                        }
                    }
                ),
                encoding="utf-8",
            )
            declared = discover_declared(project)
            resolved = discover_resolved(project, declared, assets_path=assets)

        self.assertEqual(declared["target_frameworks"], ["net9.0"])
        self.assertEqual(declared["sdk"]["status"], "not_present")
        roslyn = next(
            item for item in declared["packages"]
            if item["id"] == "Microsoft.CodeAnalysis.CSharp.Workspaces"
        )
        self.assertEqual(roslyn["version"], "4.11.0")
        self.assertEqual(len(resolved["packages"]), 2)
        roslyn_resolved = next(
            item for item in resolved["packages"]
            if item["id"] == "Microsoft.CodeAnalysis.CSharp.Workspaces"
        )
        self.assertEqual(roslyn_resolved["version"], "4.11.0")
        self.assertTrue(roslyn_resolved["direct"])

    def test_latest_discovery_can_be_repeated_without_network(self) -> None:
        declared = {"packages": [{"id": "Example", "version": "1.0.0"}]}
        first = discover_latest(declared, network=False)
        second = discover_latest(declared, network=False)
        self.assertEqual(first, second)
        self.assertEqual(first["packages"][0]["status"], "not_queried")

    def test_roslyn_report_queries_only_roslyn_latest_packages(self) -> None:
        queried: list[str] = []

        def fake_latest(package_id: str) -> str:
            queried.append(package_id)
            return "9.9.9"

        report = build_report(
            DEFAULT_PROJECT,
            focus="roslyn",
            latest_fetcher=fake_latest,
        )

        self.assertTrue(queried)
        self.assertTrue(all(package_id.startswith("Microsoft.CodeAnalysis")
                            or package_id.startswith("Microsoft.Net.Compilers")
                            for package_id in queried))
        self.assertEqual(
            queried,
            [package["id"] for package in report["observations"]["latest"]["packages"]],
        )

    def test_roslyn_report_rejects_user_focus_override(self) -> None:
        self.assertEqual(roslyn_report_main(["--focus", "all"]), 2)
        self.assertEqual(roslyn_report_main(["--focus=all"]), 2)
        self.assertEqual(roslyn_report_main(["--foc", "all"]), 2)
        self.assertEqual(roslyn_report_main(["--foc=all"]), 2)

    def test_upgrade_proposal_requires_an_explicit_decision(self) -> None:
        proposal = {
            "id": "roslyn-upgrade",
            "component": "Microsoft.CodeAnalysis",
            "from": "4.11.0",
            "to": "4.14.0",
            "compatibility_evidence": [{"reference": "api-review-1"}],
            "validation": {"command": "dotnet test", "result": "not run"},
            "decision": {"status": "defer", "evidence": "review-1"},
        }
        _validate_proposal(proposal, "proposal")
        proposal.pop("decision")
        with self.assertRaisesRegex(ValueError, "adopt/defer"):
            _validate_proposal(proposal, "proposal")

    def test_compatibility_evidence_entries_must_be_non_empty_mappings(self) -> None:
        proposal = {
            "id": "roslyn-upgrade",
            "component": "Microsoft.CodeAnalysis",
            "from": "4.11.0",
            "to": "4.14.0",
            "compatibility_evidence": [{"reference": "api-review-1"}],
            "validation": {"command": "dotnet test", "result": "not run"},
            "decision": {"status": "defer", "evidence": "review-1"},
        }
        for invalid in ([{}], ["api-review-1"], [None]):
            with self.subTest(invalid=invalid):
                proposal["compatibility_evidence"] = invalid
                with self.assertRaisesRegex(ValueError, "non-empty objects"):
                    _validate_proposal(proposal, "proposal")
