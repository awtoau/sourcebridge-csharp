# Generic C# rule runtime

`runtime.py` is the `rule_runtime` entrypoint declared by
`sourcebridge-csharp.pack.json`. It is a JSON request/response adapter for the
Sourcebridge resolved-profile contract, not a general C# converter.

The request has this shape:

```json
{
  "schema_version": 1,
  "action": "execute",
  "rule_id": "composite-format-index-preservation",
  "input": {"text": "value {0:X8}"},
  "resolved_profile": {}
}
```

The profile must identify `sourcebridge-csharp` and `sourcebridge-rust` and
must not select a corpus or Renode project. Only the provenance-pinned imported
rules in `docs/rule-runtime-boundary.json` can be identified or executed.
Unknown rules, project plugins, unsupported directives, and unsupported
composite-format shapes return a structured `"status": "blocked"` response.

For a local smoke run:

```text
python3 packs/rule_runtime/runtime.py \
  --request packs/rule_runtime/fixtures/smoke-request.json
```
