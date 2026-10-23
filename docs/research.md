# Selection research

Research date: 2026-10-23. Public, bounded comparison; not a claim that no other similar tool exists.

### 1. JSONL quarantine and reassembly

- **Problem/users:** data engineers receiving a mostly valid line-delimited feed need to isolate bad records without silently discarding source evidence.
- **Evidence:** [Hugging Face datasets #5053](https://github.com/huggingface/datasets/issues/5053) records a parse failure interrupting long processing; the issue includes a suggestion to ignore bad chunks. [NDJSON specification](https://github.com/ndjson/ndjson-spec) defines per-line parsing and explicitly documents invalid/empty-line behavior. A [Hugging Face forum thread](https://discuss.huggingface.co/t/json-parse-error-when-load-dataset/101778) shows another ingestion failure (type drift; not a problem this MVP claims to solve).
- **Alternatives:** [jsonlines](https://jsonlines.readthedocs.io/en/latest/) is a capable library with `skip_invalid`; [jsonl-check](https://github.com/naotohayashi1991/jsonl-check) is a syntax validator; [ndjson.js](https://github.com/ndjson/ndjson.js) can discard invalid messages in non-strict mode. DataSieve adds training-data-specific validation.
- **Improvement:** a standalone tool with bounded physical-line reads, exact source-byte preservation in accepted/rejected streams, an offset journal, hash verification, and an explicit reassembly command. No auto-repair or invented replacement data.
- **Feasibility/maintenance:** Python standard library; binary fixtures, corrupt journals, oversized lines, privacy-safe diagnostics, and byte-for-byte round trips can be tested locally. Small format boundary. JSON syntax/type checks are not a dataset schema.
