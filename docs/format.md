# Bundle format v1

`report.json` has schema `jsonl-rescue/v1`. It is written last. `files` maps the three fixed
filenames to `{bytes, sha256}`. `source` has the original byte size and SHA-256. Counts distinguish
accepted and rejected records. The original input pathname is not recorded.

Each line of `records.jsonl` is an object with integer fields `line` (one based), `source_offset`,
`bytes`, `stream_offset`, plus `stream` (`accepted` or `rejected`) and `code`. Offsets are zero based
byte offsets, not Unicode character offsets. Records are in source order; offsets in each target
stream are contiguous. Reassembly does not trust a pathname supplied by a manifest.

Example metadata for a three-byte accepted line (`{}\n`):

```json
{"line":1,"source_offset":0,"bytes":3,"stream":"accepted","stream_offset":0,"code":"accepted"}
```

Reason codes: `invalid_json`, `invalid_utf8`, `blank_line`, `bom`, `bare_carriage_return`,
`duplicate_key`, `non_finite_number`, `line_too_large`, `object_required`, `missing_required_key`,
`nesting_limit`, `number_limit`. The journal is intentionally metadata-only. Source values remain
in the byte streams. Unknown future schemas are rejected; bundle metadata should not be edited
to force verification to pass.
