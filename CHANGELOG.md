# Changelog

## 0.1.0 — 2026-10-24

- Split original bytes into accepted/rejected streams with an offset journal and SHA-256 manifest.
- Reassemble only after file, offset, count and source-digest verification.
- Enforce UTF-8, duplicate-key, numeric, 128-level nesting and bounded-line policies.
- Refuse occupied output paths; preserve malformed/oversized bytes without auto-repair.

Supported scope and current limits are documented in README.md.
