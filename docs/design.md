# Requirements and design

## User and core scenario

Data engineers need to quarantine malformed JSONL without discarding original evidence.

## Architecture

Binary line reader → stricter JSON classifier → two byte streams + offset journal → completion manifest. Reassembly verifies fixed file hashes, contiguous offsets, counts and the original input digest.

## Acceptance criteria

- Every input byte is in exactly one stream and can be reconstructed in order.
- Malformed/duplicate-key/invalid-encoding/oversized lines are retained with a reason.
- Existing paths and the input file are never overwritten.
- Reports/journals do not echo record values; both data streams still contain source data.

## Scope and maintenance

Python standard library; argparse CLI; unittest; no runtime dependency. No schema inference, automatic repair, compressed input, resume or crash durability promise.

No server, database service, paid API, account credential or telemetry is required. CI only verifies/builds; it does not create source commits. See README for actual commands.
