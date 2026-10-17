"""Regression tests for the bounded, provenance-preserving legacy rule import."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from import_legacy_rules import (  # noqa: E402
    CLASSIFICATIONS,
    OUTPUT,
    STATUS,
    tracked_rule_paths,
)


class LegacyRuleImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(OUTPUT.read_text(encoding="utf-8"))
        cls.records = {
            record["source_path"]: record for record in cls.manifest["records"]
        }

    def test_every_tracked_rule_payload_is_imported(self) -> None:
        paths = [path.relative_to(ROOT).as_posix() for path in tracked_rule_paths(ROOT)]
        self.assertEqual(paths, list(self.records))

    def test_digests_and_original_payloads_match_sources(self) -> None:
        for source_path, record in self.records.items():
            with self.subTest(source_path=source_path):
                raw = (ROOT / source_path).read_bytes()
                self.assertEqual(record["sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(record["original_payload"], json.loads(raw))
                self.assertEqual(record["status"], STATUS)

    def test_layers_and_classifications_are_explicit(self) -> None:
        self.assertEqual(set(self.records), set(CLASSIFICATIONS))
        for source_path, (layer, classification) in CLASSIFICATIONS.items():
            with self.subTest(source_path=source_path):
                record = self.records[source_path]
                self.assertEqual((record["layer"], record["classification"]),
                                 (layer, classification))
                self.assertTrue(record["classification"])
                self.assertNotEqual(record["status"], "target-validated")

        for source_path in (
            "rulesdb/rules/bug_rules.json",
            "rulesdb/rules/offset_switch.json",
            "rulesdb/rules/register_dsl.json",
        ):
            self.assertTrue(self.records[source_path]["classification"].startswith("renode-"))
