Sourcebridge C# pack adapter — minimal test harness

This folder contains a minimal, standalone adapter and fixtures to exercise
C# source-side validation for the Sourcebridge C# pack. It is intentionally
small and does not depend on Renode.

Usage:
  python3 packs/adapter/adapter.py --list        # list known fixtures
  python3 packs/adapter/adapter.py --run ALL     # run all fixtures

Sourcebridge imports [`engine-tests.json`](./engine-tests.json)
through [`sourcebridge-csharp.pack.json`](../../sourcebridge-csharp.pack.json).
The catalogue assigns stable IDs 434-436 while this adapter remains responsible
for source-side execution and explicit target-blocked evidence.

Behavior:
- If the host has the `dotnet` SDK available, adapter will attempt to `dotnet build`
  each fixture in a temporary workspace under tmp/adapter_runs.
- After a successful build the adapter runs the fixture (source-side execution)
  and records its exit code, stdout and stderr. The adapter does NOT invoke the
  converter/emitter; it will always return `target_status: blocked` with an
  explicit reason indicating the converter was not invoked. If `dotnet` is not
  available, the adapter records an explicit blocked target evidence message
  ("dotnet SDK missing") for each fixture.

Purpose:
- Provide a minimal reusable pack adapter interface that downstream tests and
  Sourcebridge core can call to drive differential tests independent of Renode.
