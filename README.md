# csharp2rust

A general C#-to-Rust source translator: reads C# through Roslyn, emits Rust,
driven by a reviewable database of mapping rules rather than by per-file
hand-editing.

**This is the home of the generic capability built in `awto-renode-rs`.** That
project translates Renode's C# codebase (~448k lines) to Rust; everything it
learns that is *not* about Renode belongs here. The split:

| stays in `awto-renode-rs` | lives here |
|---|---|
| the Renode corpus and its `.repl` platform | Roslyn extraction — reading what the compiler exposes |
| trace-replay oracle and the firmware under test | the C#-to-Rust language mapping, as data |
| peripheral shapes, the register DSL, project idioms | the rule-database engine, tiering and metrics |

**Status: name claimed, nothing built here yet.** The implementation still
lives in `awto-renode-rs` and moves across once the language mapping separates
cleanly from the project idioms.

## Why this exists

There is no C#-to-Rust source translator. That was checked properly, not
assumed — GitHub, GitLab, Codeberg, SourceForge, Software Heritage, grep.app,
crates.io, NuGet, Hacker News, Stack Overflow, the Rust users forum, and Google
Scholar's exact-phrase index. What exists is:

- **C-to-Rust** translators (`c2rust` and relatives) — a different source
  language, and the model this project follows for how a translator should be
  structured
- **LLM converters** — web forms and one abandoned GitHub project that calls a
  model once per declaration and grades with `cargo check`. That cost model is
  what this project rejects
- **One commercial web form** (CodePorting), whose published caveats are the
  useful part

The full prior-art survey lives in `awto-renode-rs` under
`docs/research/prior-art.md` and moves here when the code does.

## The shape of it

Three layers, and keeping them apart is the whole design:

| layer | what it is | where it belongs |
|---|---|---|
| **Extraction** | reading what Roslyn exposes | transpiler source — a bug here is a transpiler bug, fixed once for every corpus |
| **Language mapping** | `ConditionalOr` → `\|\|`, overflow semantics, LINQ | data — generic to C# and Rust, reviewable without touching code |
| **Project idioms** | a specific codebase's DSLs and shapes | data — never reaches the transpiler source |

Nothing project-specific may reach the source. That boundary is what makes the
translator reusable and keeps the per-project rule set small.

## The rules that make it not-a-pile-of-hand-edits

- **The translator reads only from the corpus database.** No code path opens a
  `.cs` file directly, so skipping ingestion is impossible rather than merely
  discouraged.
- **A rule is not a rule until it has three validated instances.** Below that
  it is recorded as a *patch* and counted against the project.
- **Patches must trend to zero.** A hand-edited output file is one that will not
  regenerate, and the ability to regenerate is the asset.
- **The headline metric is instances-per-rule, not files translated.** A fall
  toward 1 means the process has drifted into per-file work.
- **Correctness is certified by trace replay, never by "it compiled".** Breadth
  across a large tree proves a rule *emits*; it can never prove the output is
  *right*.

## Licence

Not yet chosen.
