from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("renode_pipeline", ROOT / "renode_pipeline.py")
assert SPEC is not None and SPEC.loader is not None
renode_pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renode_pipeline)
EMITTER_SPEC = importlib.util.spec_from_file_location(
    "csharp_emitter", ROOT.parents[1] / "scripts" / "core" / "csharp_emitter.py"
)
assert EMITTER_SPEC is not None and EMITTER_SPEC.loader is not None
csharp_emitter = importlib.util.module_from_spec(EMITTER_SPEC)
EMITTER_SPEC.loader.exec_module(csharp_emitter)


class RenodePipelineTests(unittest.TestCase):
    def test_gate_statuses_reads_full_gate_summary(self) -> None:
        statuses = renode_pipeline.gate_statuses(
            """
check_ingest                             ok                2.2s
check_generated                          ok                9.3s
compile_check --ratchet --jobs 15        FAILED (1)       98.5s
gap_census --jobs 15                     ok               82.6s
"""
        )

        self.assertEqual(
            statuses,
            {
                "check_ingest": "passed",
                "check_generated": "passed",
                "compile_check": "failed",
                "gap_census": "passed",
            },
        )

    def test_load_fixture_rejects_unsupported_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "fixture.json"
            fixture.write_text('{"schema_version": 1}', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "unsupported pipeline fixture shape"):
                renode_pipeline.load_fixture(fixture)

    def test_method_identifier_uses_declared_interface_member_segment(self) -> None:
        self.assertEqual(
            csharp_emitter.method_identifier(
                "Antmicro.Renode.Peripherals.SPI.ISPIPeripheral.FinishTransmission",
                "declared-member-segment-snake-case",
            ),
            "finish_transmission",
        )
        with self.assertRaisesRegex(ValueError, "unsupported method identifier"):
            csharp_emitter.method_identifier("Method", "unknown"),
