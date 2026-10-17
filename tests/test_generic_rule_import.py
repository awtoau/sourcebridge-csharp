"""Minimal regressions for imported generic C# to Rust rules."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from core.csharp_emitter import Emitter  # noqa: E402
from emitter.lang.expressions import Expressions  # noqa: E402


class _FormatEmitter(Expressions):
    def __init__(self) -> None:
        self.language = {
            "format_strings": {
                "specs": {"x": "x", "X": "X"},
                "padded_hex": "0{width}{spec}",
            },
        }
        self.unhandled: dict[str, int] = {}


class GenericRuleImportTests(unittest.TestCase):
    def test_explicit_interface_name_uses_terminal_member(self) -> None:
        emitter = Emitter.__new__(Emitter)
        emitter.project = {
            "peripheral_methods": {
                "accessor_names": {"strip_prefixes": ["get_", "set_"]},
            },
        }

        self.assertEqual(
            emitter.fn_name("Example.Contracts.IReader.get_Value"),
            "value",
        )
        self.assertEqual(
            emitter.fn_name("Example.Contracts.IReader.ReadValue"),
            "read_value",
        )

    def test_composite_format_preserves_argument_indexes(self) -> None:
        emitter = _FormatEmitter()

        self.assertEqual(
            emitter.csharp_format("value {0:X8} then {1} and {0:x}"),
            "value {0:08X} then {1} and {0:x}",
        )
        self.assertEqual(emitter.unhandled, {})

    def test_unsupported_composite_format_is_counted(self) -> None:
        emitter = _FormatEmitter()

        self.assertEqual(
            emitter.csharp_format("value {0,8:X}"),
            "value {{GAP: unsupported C# composite format}}",
        )
        self.assertEqual(emitter.unhandled, {"format:unsupported-composite": 1})
