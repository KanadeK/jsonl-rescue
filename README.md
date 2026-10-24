# jsonl-rescue

Quarantine broken JSONL records, keep the original bytes, and prove you can put them back.

This offline CLI splits a feed into accepted and rejected byte streams, records the original
order in an offset journal, and verifies hashes before reassembling the exact original input.
It helps investigate ingestion failures without silently dropping bad records or rewriting good ones.

[中文说明](README.zh-CN.md) · [Bundle format](docs/format.md) · [Contributing](CONTRIBUTING.md)

## Install

Python 3.11 or newer. No runtime dependencies or service accounts.
From a downloaded or cloned source checkout:

```console
git clone https://github.com/KanadeK/jsonl-rescue.git
cd jsonl-rescue
python -m venv .venv
```

Activate the environment (`.venv\Scripts\Activate.ps1` on PowerShell,
`source .venv/bin/activate` on POSIX), then:

```console
python -m pip install .
jsonl-rescue --version
python scripts/demo.py
```

The demo generates synthetic input in a temporary directory, checks two accepted records and one
rejection, verifies a byte-identical round trip, then cleans up. It requires no downloaded dataset.

## Use

```console
jsonl-rescue split incoming.jsonl --output recovery
jsonl-rescue split incoming.jsonl --output object-recovery --objects-only --require-key id
jsonl-rescue reassemble recovery --output original-copy.bin
```

`--output` must not exist. Its parent must exist. Use `-` as the split input to read binary stdin.
The input is never changed. Split returns **1 when any record was quarantined**; the bundle is
still complete and usable. Reassembly verifies all three bundle files, validates journal offsets
and counts, and checks the final source hash. Existing output files/directories are refused.

| Output | Contents |
|---|---|
| `accepted.jsonl` | Original accepted record bytes, including original LF/CRLF endings |
| `rejected.bin` | Original rejected bytes; may contain invalid UTF-8 and is not necessarily JSONL |
| `records.jsonl` | Every record's line number, offsets, length, stream and reason; no record values |
| `report.json` | Completion manifest, counts, policy, byte sizes and SHA-256 hashes |

Both data streams retain source content, including any private data. Keep the bundle private.
Console reports and the journal do not include source paths or record values. Required-key names
are recorded in the policy. Hashes detect accidental corruption; they are not signatures and do
not authenticate a bundle against someone who can replace the entire bundle.

## Validation policy

Records are separated only at LF bytes; CRLF is accepted. A final record without LF is accepted.
Blank lines, UTF-8 BOMs, bare CR, invalid UTF-8/JSON, duplicate object keys (at any nesting level),
and NaN/Infinity constants are quarantined. Duplicate-key rejection is deliberately stricter than
JSON syntax. JSON scalars and null are accepted unless `--objects-only` or `--require-key` is used.
Required keys must exist at the top level; null values are allowed. This is not JSON Schema.

`--max-line-bytes` defaults to 1 MiB and includes line-ending bytes (range 1 byte–64 MiB).
Oversized records are drained into quarantine in 64 KiB chunks. Parsing memory is proportional
to the configured maximum record size and the decoded JSON object; the entire file is never loaded.
A fixed maximum of 128 nested arrays/objects is enforced, ignoring brackets inside strings.
Python's integer-digit limit also applies. Decimal JSON numbers are parsed without
converting large exponents to floating-point Infinity. Accepted bytes are never reserialized.

## Exit codes and cleanup

- `0`: split has no rejections, or reassembly succeeded.
- `1`: split completed with quarantined records.
- `2`: usage, input, I/O, policy, corruption or bundle error.
- `130`: interrupted.

Uninstall with `python -m pip uninstall jsonl-rescue`. Remove only the recovery directories and
copies you no longer need; the tool creates no global state. Ordinary failed operations remove
their newly created partial outputs. A hard process termination can leave an incomplete directory:
do not use it unless `report.json` exists and reassembly verifies it. No crash/power-loss durability
guarantee is made. Use trusted local filesystem parents and avoid concurrent edits while processing.

## Alternatives and limits

[jsonlines](https://jsonlines.readthedocs.io/en/latest/) is preferable for application-level readers
and writers; it can skip invalid lines. [ndjson.js](https://github.com/ndjson/ndjson.js) supports
stream parsing. This tool focuses on a self-contained, reversible quarantine workflow with a byte
journal. It does not repair records, infer schemas, decompress archives, resume partial runs,
scan for secrets, or provide a security sandbox. The journal uses disk space proportional to the
number of records; reassembly performs an additional hash pass.

Run the checks in [CONTRIBUTING.md](CONTRIBUTING.md). The test suite covers invalid encodings,
oversized records, corrupted bundles, existing-output protection and full CLI workflows.
See [SECURITY.md](SECURITY.md) for private reporting. MIT © 2026 KanadeK.
