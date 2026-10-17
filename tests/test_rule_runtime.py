"""Focused checks for the pack-declared generic C# rule-runtime boundary."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "packs" / "rule_runtime" / "runtime.py"
FIXTURE = ROOT / "packs" / "rule_runtime" / "fixtures" / "smoke-request.json"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "packs"))

from rule_runtime.runtime import identify, run_request


class RuleRuntimeTests(unittest.TestCase):
    def fixture_request(self) -> dict[str, object]:
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_fixture_executes_through_the_json_contract(self) -> None:
        result = run_request(self.fixture_request())

        self.assertEqual(result["status"], "executed")
        self.assertEqual(result["value"], "value {0:08X} then {1} and {0:x}")
        self.assertEqual(result["provenance"]["classification"], "imported")

    def test_identify_exposes_only_imported_generic_rules(self) -> None:
        profile = self.fixture_request()["resolved_profile"]
        result = identify(profile)  # type: ignore[arg-type]

        self.assertEqual(result["status"], "identified")
        self.assertEqual(
            {rule["id"] for rule in result["rules"]},
            {
                "explicit-interface-method-name-lowering",
                "composite-format-index-preservation",
                "composite-format-unsupported-shapes",
            },
        )
        self.assertTrue(
            all(
                "plugins/" not in rule["provenance"]["source"]["path"]
                for rule in result["rules"]
            )
        )
        self.assertEqual(
            {item["rule_id"] for item in result["blocked"]},
            {
                "renode-log-argument-selection",
                "nested-base-call-gap-lowering",
                "generated-corpus-and-ratcheting-updates",
            },
        )

    def test_explicit_interface_name_lowering_is_executable(self) -> None:
        request = self.fixture_request()
        request.update(
            {
                "rule_id": "explicit-interface-method-name-lowering",
                "input": {"method_name": "Example.Contracts.IReader.get_Value"},
            }
        )

        result = run_request(request)

        self.assertEqual(result["status"], "executed")
        self.assertEqual(result["value"], "value")

    def test_unsupported_shape_is_blocked_and_counted(self) -> None:
        request = self.fixture_request()
        request["input"] = {"text": "value {0,8:X}"}

        result = run_request(request)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "unsupported-composite-format")
        self.assertEqual(result["unhandled"], {"format:unsupported-composite": 1})

    def test_renode_profile_and_replacement_directive_are_blocked(self) -> None:
        request = self.fixture_request()
        profile = request["resolved_profile"]
        profile["project_id"] = "renode"  # type: ignore[index]
        request["resolved_profile"] = profile

        result = run_request(request)

        self.assertEqual(result["status"], "blocked")
        self.assertIn("Renode", result["reason"])

        request = self.fixture_request()
        request["resolved_profile"]["rule_overrides"] = [  # type: ignore[index]
            {"rule_key": request["rule_id"], "directive": "replace"}
        ]
        result = run_request(request)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "unsupported-directive")

    def test_unknown_rule_and_directive_are_visible(self) -> None:
        request = self.fixture_request()
        request["rule_id"] = "renode-log-argument-selection"
        result = run_request(request)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "unsupported-rule")

        request = self.fixture_request()
        request["directive"] = "project-plugin"
        result = run_request(request)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "unsupported-directive")

    def test_entrypoint_smoke_returns_json(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(RUNTIME), "--request", str(FIXTURE)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "executed")


if __name__ == "__main__":
    unittest.main()
