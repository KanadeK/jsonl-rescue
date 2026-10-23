"""A bundle is complete only when report.json has been written successfully."""

from __future__ import annotations

import hashlib
import json
import stat
from collections import Counter
from contextlib import ExitStack
from decimal import Decimal
from pathlib import Path
from typing import BinaryIO

CHUNK = 64 * 1024
MAX_LINE_BYTES = 64 * 1024 * 1024
FILES = ("accepted.jsonl", "rejected.bin", "records.jsonl")
SCHEMA = "jsonl-rescue/v1"


class RescueError(ValueError):
    """An expected error with a code that contains no source values."""


def _duplicate_safe(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise RescueError("duplicate_key")
        result[key] = value
    return result


def _constant(_: str) -> None:
    raise RescueError("non_finite_number")


def _depth_exceeded(text: str) -> bool:
    depth = 0
    quoted = escaped = False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > 128:
                return True
        elif char in "]}":
            depth -= 1
    return False


def classify(raw: bytes, *, objects_only: bool = False, required: tuple[str, ...] = ()) -> str:
    """Return 'accepted' or a reason code. Never include source values in diagnostics."""
    payload = raw[:-1].removesuffix(b"\r") if raw.endswith(b"\n") else raw
    if payload.startswith(b"\xef\xbb\xbf"):
        return "bom"
    if b"\r" in payload:
        return "bare_carriage_return"
    if not payload.strip():
        return "blank_line"
    try:
        text = payload.decode("utf-8")
        if _depth_exceeded(text):
            return "nesting_limit"
        value = json.loads(
            text,
            object_pairs_hook=_duplicate_safe,
            parse_constant=_constant,
            parse_float=Decimal,
        )
    except UnicodeDecodeError:
        return "invalid_utf8"
    except RescueError as exc:
        return str(exc)
    except json.JSONDecodeError:
        return "invalid_json"
    except RecursionError:
        return "nesting_limit"
    except ValueError:
        return "number_limit"
    if (objects_only or required) and not isinstance(value, dict):
        return "object_required"
    if required and any(key not in value for key in required):
        return "missing_required_key"
    return "accepted"


def _fingerprint(path: Path) -> dict:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK):
            digest.update(chunk)
            size += len(chunk)
    return {"bytes": size, "sha256": digest.hexdigest()}


def split(
    stream: BinaryIO,
    output: Path,
    *,
    max_line_bytes: int = 1024 * 1024,
    objects_only: bool = False,
    required: tuple[str, ...] = (),
) -> dict:
    """Split LF-delimited binary input. max_line_bytes includes the line terminator."""
    if type(max_line_bytes) is not int or not 1 <= max_line_bytes <= MAX_LINE_BYTES:
        raise RescueError("invalid_line_limit")
    output = Path(output)
    output.mkdir(mode=0o700)  # Exclusive: never adopt or overwrite an existing directory.
    complete = False
    try:
        digest = hashlib.sha256()
        offset = line = accepted = rejected = 0
        reasons: Counter = Counter()
        with ExitStack() as stack:
            good = stack.enter_context((output / FILES[0]).open("xb"))
            bad = stack.enter_context((output / FILES[1]).open("xb"))
            journal = stack.enter_context(
                (output / FILES[2]).open("x", encoding="utf-8", newline="\n")
            )
            while head := stream.readline(max_line_bytes + 1):
                line += 1
                digest.update(head)
                length = len(head)
                oversized = length > max_line_bytes
                code = (
                    "line_too_large"
                    if oversized
                    else classify(head, objects_only=objects_only, required=required)
                )
                target = good if code == "accepted" else bad
                target_offset = target.tell()
                target.write(head)
                if oversized:
                    # Drain through LF in fixed chunks, preserving every byte without a huge buffer.
                    while not head.endswith(b"\n"):
                        head = stream.readline(CHUNK)
                        if not head:
                            break
                        digest.update(head)
                        target.write(head)
                        length += len(head)
                if code == "accepted":
                    accepted += 1
                else:
                    rejected += 1
                    reasons[code] += 1
                record = {
                    "line": line,
                    "source_offset": offset,
                    "bytes": length,
                    "stream": "accepted" if code == "accepted" else "rejected",
                    "stream_offset": target_offset,
                    "code": code,
                }
                journal.write(json.dumps(record, sort_keys=True) + "\n")
                offset += length
        report = {
            "schema": SCHEMA,
            "source": {"bytes": offset, "sha256": digest.hexdigest()},
            "records": line,
            "accepted": accepted,
            "rejected": rejected,
            "reasons": dict(sorted(reasons.items())),
            "policy": {
                "max_line_bytes": max_line_bytes,
                "objects_only": objects_only,
                "required_keys": list(required),
            },
            "files": {name: _fingerprint(output / name) for name in FILES},
        }
        with (output / "report.json").open("x", encoding="utf-8", newline="\n") as report_file:
            report_file.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
        complete = True
        return report
    finally:
        if not complete:
            # Remove only the fixed filenames created by this operation; no recursive deletion.
            for name in (*FILES, "report.json"):
                (output / name).unlink(missing_ok=True)
            output.rmdir()


def _regular(path: Path) -> None:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise RescueError("bundle_member_not_regular")


def _load_report(bundle: Path) -> dict:
    for name in (*FILES, "report.json"):
        _regular(bundle / name)
    with (bundle / "report.json").open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise RescueError("report_too_large")
    try:
        report = json.loads(raw, object_pairs_hook=_duplicate_safe, parse_constant=_constant)
        if not isinstance(report, dict) or report.get("schema") != SCHEMA:
            raise RescueError("unsupported_bundle")
        for name in FILES:
            if _fingerprint(bundle / name) != report["files"][name]:
                raise RescueError("bundle_hash_mismatch")
        for key in ("records", "accepted", "rejected"):
            if type(report[key]) is not int or report[key] < 0:
                raise RescueError("invalid_report")
        if report["records"] != report["accepted"] + report["rejected"]:
            raise RescueError("invalid_report")
        if type(report["source"]["bytes"]) is not int or report["source"]["bytes"] < 0:
            raise RescueError("invalid_report")
        return report
    except (KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        raise RescueError("invalid_report") from exc


def reassemble(bundle: Path, output: Path) -> dict:
    """Verify fixed bundle members and reconstruct the original byte stream to a new file."""
    bundle, output = Path(bundle), Path(output)
    report = _load_report(bundle)
    created = complete = False
    try:
        with ExitStack() as stack:
            sources = {
                "accepted": stack.enter_context((bundle / FILES[0]).open("rb")),
                "rejected": stack.enter_context((bundle / FILES[1]).open("rb")),
            }
            journal = stack.enter_context((bundle / FILES[2]).open("rb"))
            destination = stack.enter_context(output.open("xb"))
            created = True
            digest = hashlib.sha256()
            offset = count = 0
            seen: Counter = Counter()
            while raw := journal.readline(4097):
                if len(raw) > 4096:
                    raise RescueError("invalid_journal")
                try:
                    entry = json.loads(raw, object_pairs_hook=_duplicate_safe)
                    kind = entry["stream"]
                    if kind not in sources:
                        raise RescueError("invalid_journal")
                    source = sources[kind]
                    for key in ("line", "source_offset", "stream_offset", "bytes"):
                        if type(entry[key]) is not int:
                            raise RescueError("invalid_journal")
                    if (
                        entry["line"] != count + 1
                        or entry["source_offset"] != offset
                        or entry["stream_offset"] != source.tell()
                        or entry["bytes"] <= 0
                    ):
                        raise RescueError("invalid_journal")
                    remaining = entry["bytes"]
                    if remaining > report["source"]["bytes"] - offset:
                        raise RescueError("invalid_journal")
                except (ValueError, TypeError, KeyError, UnicodeDecodeError, RecursionError) as exc:
                    raise RescueError("invalid_journal") from exc
                while remaining:
                    chunk = source.read(min(CHUNK, remaining))
                    if not chunk:
                        raise RescueError("truncated_stream")
                    destination.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
                count += 1
                seen[kind] += 1
                offset += entry["bytes"]
            if (
                count != report["records"]
                or seen["accepted"] != report["accepted"]
                or seen["rejected"] != report["rejected"]
                or any(source.read(1) for source in sources.values())
                or {"bytes": offset, "sha256": digest.hexdigest()} != report["source"]
            ):
                raise RescueError("reassembly_mismatch")
        complete = True
        return {"schema": SCHEMA, "reassembled": True, **report["source"]}
    finally:
        if created and not complete:
            output.unlink(missing_ok=True)
