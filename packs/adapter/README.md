# C# source-side adapter

Run the standalone fixture adapter through the canonical development entry
point:

```text
python3 scripts/dev.py adapter-test --run ALL --json
```

The adapter builds and runs three small C# fixtures when `dotnet` is
installed.  It records source compilation and execution evidence only.  It
never invokes the C#-to-Rust converter, so every result has
`target_status: "blocked"` with an explicit reason.  If the SDK is absent,
the result records a blocked compile observation instead of treating the
missing tool as a successful conversion.

This adapter is intentionally independent of the Renode corpus and is useful
as a smoke test for the Sourcebridge C# pack contract.
