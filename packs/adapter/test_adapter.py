from __future__ import annotations

import unittest

import adapter


class AdapterTargetTests(unittest.TestCase):
    def test_emits_registered_fixture_shapes(self) -> None:
        self.assertIn(
            "1i32 + 2i32",
            adapter._emit_fixture_rust("Console.WriteLine(1 + 2);") or "",
        )
        self.assertIn(
            "fn add(left: i32, right: i32)",
            adapter._emit_fixture_rust(
                "static int Add(int left, int right) => left + right;"
                "Console.WriteLine(Add(40, 2));"
            )
            or "",
        )
        self.assertIn(
            "values.len()",
            adapter._emit_fixture_rust(
                "int[] values = new int[] {1, 2, 3}; Console.WriteLine(values.Length);"
            )
            or "",
        )

    def test_blocks_unrecognised_csharp(self) -> None:
        self.assertIsNone(adapter._emit_fixture_rust("Console.WriteLine(DateTime.Now);"))


if __name__ == "__main__":
    unittest.main()
