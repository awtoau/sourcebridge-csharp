Sourcebridge C# pack adapter — minimal test harness

This folder contains a minimal, standalone adapter and fixtures to exercise
C# source-side validation for the Sourcebridge C# pack. It is intentionally
small and does not depend on Renode.

Usage:
  python3 packs/adapter/adapter.py --list        # list known fixtures
  python3 packs/adapter/adapter.py --run ALL     # run all fixtures

Behavior:
- If the host has the `dotnet` SDK available, adapter will attempt to `dotnet build`
  each fixture in a temporary workspace under tmp/adapter.
- If `dotnet` is not available, the adapter records an explicit blocked target
  evidence message ("dotnet SDK missing") for each fixture. This is honest —
  it does not fake conversion or compilation success.

Purpose:
- Provide a minimal reusable pack adapter interface that downstream tests and
  Sourcebridge core can call to drive differential tests independent of Renode.
