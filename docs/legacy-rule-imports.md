# Legacy rule payload imports

`rulesdb/imports/legacy-csharp-rules-v1.json` is a bounded import of exactly
the tracked `rulesdb/rules/*.json` payloads. Regenerate it with:

```sh
python3 scripts/import_legacy_rules.py
```

Each record preserves its source path, byte SHA-256, original JSON payload,
source repository and revision, explicit layer/classification, and
`unvalidated-legacy-import` status. This is provenance, not target validation:
the importer performs no semantic assessment of rules or conversion output.
