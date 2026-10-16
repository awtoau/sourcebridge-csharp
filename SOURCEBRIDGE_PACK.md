# Sourcebridge C# pack

This repository is the history-preserving C# to Rust pack for Sourcebridge.
It was imported as a complete Git mirror from
`https://github.com/awtoau/csharp2rust.git`, with the canonical pack branch
anchored at `ea6d9b26cc563f65c199bc6be6b909037d2fb6b3`. Every reachable source
ref was retained. The import provenance is also recorded in the Sourcebridge
migration ledger.

## Current status

The imported snapshot is clean and remains the baseline for reproducibility
checks. It includes a Roslyn C# frontend, a Rust emitter, Renode-derived corpus
and oracle tooling, rule data, and generated artifacts. Its existing
project-specific implementation is deliberately retained here rather than
moved into Sourcebridge core.

The generic Sourcebridge engine owns neutral execution, evidence, review, and
profile contracts. This pack owns C# language facts, C# to Rust mappings, its
corpus adapters, and any target-specific rules. A generic capability may move
to core only after it has an evidence-backed, language-neutral contract.

## Operating contract

- Use `python3 scripts/dev.py` as the supported project entry point.
- Treat emitted Rust as generated output; change the extractor, rules, or
  emitter rather than editing generated files.
- Preserve source variant, corpus revision, and oracle evidence for every
  claimed conversion result.
- Do not redirect or retire the original repository until this pack has
  reproduced its validation and regeneration gates from the imported history.

This is an import baseline, not a claim that every C# construct or corpus
component has already been validated by Sourcebridge.
