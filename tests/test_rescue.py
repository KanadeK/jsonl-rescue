from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonl_rescue.cli import main
from jsonl_rescue.core import FILES, RescueError, classify, reassemble, split


class ClassificationTests(unittest.TestCase):
    def test_standard_values_and_line_endings(self):
        for value in (
            b"{}\n",
            b' {"x":1}\r\n',
            b"null",
            b"[]\n",
            b"1e9999\n",
            b'"hello\\nworld"\n',
            '"你好"\n'.encode(),
        ):
            with self.subTest(value=value):
                self.assertEqual(classify(value), "accepted")

    def test_bad_records(self):
        cases = {
            b"\n": "blank_line",
            b" \r\n": "blank_line",
            b"{}\r": "bare_carriage_return",
            b"{}\r{}\n": "bare_carriage_return",
            b"\xef\xbb\xbf{}\n": "bom",
            b"{bad}\n": "invalid_json",
            b"\xff\n": "invalid_utf8",
            b'{"a":1,"a":2}\n': "duplicate_key",
            b"NaN\n": "non_finite_number",
            b'{"x":Infinity}\n': "non_finite_number",
            b'{"a":{"x":1,"x":2}}': "duplicate_key",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(classify(raw), expected)

    def test_object_and_required_key_policy(self):
        self.assertEqual(classify(b"[]", objects_only=True), "object_required")
        self.assertEqual(classify(b"null", required=("id",)), "object_required")
        self.assertEqual(classify(b"{}", required=("id",)), "missing_required_key")
        self.assertEqual(classify(b'{"id":null}', required=("id",)), "accepted")

    def test_excessive_nesting_is_quarantined(self):
        self.assertEqual(classify(b"[" * 2000 + b"]" * 2000), "nesting_limit")

    def test_depth_boundary_and_string_brackets(self):
        self.assertEqual(classify(b"[" * 128 + b"0" + b"]" * 128), "accepted")
        self.assertEqual(classify(b"[" * 129 + b"0" + b"]" * 129), "nesting_limit")
        self.assertEqual(classify(json.dumps("[" * 2000 + '\\"').encode()), "accepted")

    def test_large_integer_is_quarantined(self):
        self.assertEqual(classify(b"9" * 10000), "number_limit")


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / "bundle"

    def make(self, raw=b'{"id":1}\nBAD\n{"id":2}'):
        return split(io.BytesIO(raw), self.bundle)

    def rewrite_journal(self, entries):
        path = self.bundle / "records.jsonl"
        path.write_bytes(b"".join(json.dumps(entry).encode() + b"\n" for entry in entries))
        report_path = self.bundle / "report.json"
        report = json.loads(report_path.read_text())
        data = path.read_bytes()
        report["files"]["records.jsonl"] = {
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        report_path.write_text(json.dumps(report))

    def test_mixed_round_trip_preserves_every_byte(self):
        original = b'{"id":1}\r\n\xff\n{"a":1,"a":2}\n\n[4,5]\n{"last":true}'
        report = self.make(original)
        self.assertEqual((report["accepted"], report["rejected"]), (3, 3))
        self.assertEqual(
            (self.bundle / "accepted.jsonl").read_bytes(), b'{"id":1}\r\n[4,5]\n{"last":true}'
        )
        self.assertEqual((self.bundle / "rejected.bin").read_bytes(), b'\xff\n{"a":1,"a":2}\n\n')
        result = reassemble(self.bundle, self.root / "restored")
        self.assertTrue(result["reassembled"])
        self.assertEqual((self.root / "restored").read_bytes(), original)
        self.assertEqual(report["source"]["sha256"], hashlib.sha256(original).hexdigest())

    def test_empty_input_is_valid_and_reassembles(self):
        report = self.make(b"")
        self.assertEqual(report["records"], 0)
        reassemble(self.bundle, self.root / "empty")
        self.assertEqual((self.root / "empty").read_bytes(), b"")

    def test_oversize_record_does_not_consume_following_record(self):
        original = b"x" * 200000 + b"\r\n{}\n"

        class BoundedInput(io.BytesIO):
            def readline(self, size=-1):
                if size <= 0 or size > 65536:
                    raise AssertionError("unbounded read")
                return super().readline(size)

        report = split(BoundedInput(original), self.bundle, max_line_bytes=10)
        self.assertEqual(report["reasons"], {"line_too_large": 1})
        self.assertEqual(report["accepted"], 1)
        reassemble(self.bundle, self.root / "large")
        self.assertEqual((self.root / "large").read_bytes(), original)

    def test_line_limit_includes_newline(self):
        result = split(io.BytesIO(b"{}\n{}"), self.bundle, max_line_bytes=2)
        self.assertEqual((result["accepted"], result["rejected"]), (1, 1))

    def test_oversize_final_record_without_lf(self):
        result = split(io.BytesIO(b"x" * 100), self.bundle, max_line_bytes=2)
        self.assertEqual(result["source"]["bytes"], 100)
        reassemble(self.bundle, self.root / "original")
        self.assertEqual((self.root / "original").read_bytes(), b"x" * 100)

    def test_invalid_limits_leave_no_output(self):
        for limit in (0, -1, 2**30, True):
            with self.subTest(limit=limit), self.assertRaises(RescueError):
                split(io.BytesIO(b"{}"), self.bundle, max_line_bytes=limit)
            self.assertFalse(self.bundle.exists())

    def test_existing_directory_is_never_adopted(self):
        self.bundle.mkdir()
        sentinel = self.bundle / "keep.txt"
        sentinel.write_text("preserve")
        with self.assertRaises(FileExistsError):
            self.make()
        self.assertEqual(sentinel.read_text(), "preserve")

    def test_existing_reassembly_target_is_preserved(self):
        self.make()
        output = self.root / "keep"
        output.write_bytes(b"preserve")
        with self.assertRaises(FileExistsError):
            reassemble(self.bundle, output)
        self.assertEqual(output.read_bytes(), b"preserve")

    def test_midstream_read_failure_cleans_only_new_bundle(self):
        class BrokenInput(io.BytesIO):
            def readline(self, size=-1):
                if self.tell():
                    raise OSError("simulated read error")
                return super().readline(size)

        with self.assertRaises(OSError):
            split(BrokenInput(b"{}\n{}\n"), self.bundle)
        self.assertFalse(self.bundle.exists())

    def test_member_tampering_is_rejected_before_output(self):
        self.make()
        (self.bundle / "accepted.jsonl").write_bytes(b"{}\n")
        with self.assertRaisesRegex(RescueError, "bundle_hash_mismatch"):
            reassemble(self.bundle, self.root / "out")
        self.assertFalse((self.root / "out").exists())

    def test_metadata_has_no_source_values(self):
        canary = b"private-value-canary"
        self.make(b'{"private":"' + canary + b'",}\n')
        for name in ("records.jsonl", "report.json"):
            self.assertNotIn(canary, (self.bundle / name).read_bytes())

    def test_invalid_journal_offsets_clean_partial_output(self):
        self.make()
        entries = [
            json.loads(line) for line in (self.bundle / "records.jsonl").read_text().splitlines()
        ]
        entries[1]["stream_offset"] = -1
        self.rewrite_journal(entries)
        with self.assertRaisesRegex(RescueError, "invalid_journal"):
            reassemble(self.bundle, self.root / "out")
        self.assertFalse((self.root / "out").exists())

    def test_invalid_journal_types_or_streams_are_refused(self):
        self.make()
        entries = [
            json.loads(line) for line in (self.bundle / "records.jsonl").read_text().splitlines()
        ]
        original = dict(entries[0])
        for key, value in (
            ("stream", "../../outside"),
            ("bytes", True),
            ("line", 0),
            ("bytes", 10**9),
        ):
            entries[0] = {**original, key: value}
            self.rewrite_journal(entries)
            with self.subTest(key=key, value=value), self.assertRaises(RescueError):
                reassemble(self.bundle, self.root / "out")
            self.assertFalse((self.root / "out").exists())

    def test_missing_records_cannot_silently_drop_input(self):
        self.make()
        self.rewrite_journal([])
        with self.assertRaisesRegex(RescueError, "reassembly_mismatch"):
            reassemble(self.bundle, self.root / "out")

    def test_report_schema_and_types_are_checked(self):
        self.make()
        path = self.bundle / "report.json"
        good = json.loads(path.read_text())
        cases = [
            {},
            [],
            {**good, "schema": "future"},
            {**good, "records": True},
            {**good, "records": 100},
            {**good, "source": {"bytes": -1}},
        ]
        for report in cases:
            path.write_text(json.dumps(report))
            with self.subTest(report=report), self.assertRaises(RescueError):
                reassemble(self.bundle, self.root / "out")

    def test_report_size_limit(self):
        self.make()
        (self.bundle / "report.json").write_bytes(b" " * 70000)
        with self.assertRaisesRegex(RescueError, "report_too_large"):
            reassemble(self.bundle, self.root / "out")

    def test_directory_bundle_member_is_refused(self):
        self.make()
        member = self.bundle / FILES[0]
        member.unlink()
        member.mkdir()
        with self.assertRaisesRegex(RescueError, "bundle_member_not_regular"):
            reassemble(self.bundle, self.root / "out")


class CLITests(unittest.TestCase):
    def test_full_cli_workflow_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input"
            source.write_bytes(b"{}\nBAD\n")
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["split", str(source), "--output", str(root / "bundle")]), 1)
                self.assertEqual(json.loads(output.getvalue())["rejected"], 1)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(["reassemble", str(root / "bundle"), "--output", str(root / "out")]), 0
                )
            self.assertEqual(source.read_bytes(), (root / "out").read_bytes())

    def test_stdin_objects_and_required_key(self):
        with tempfile.TemporaryDirectory() as directory:
            stdin = io.TextIOWrapper(io.BytesIO(b'{"id":1}\n[]\n{}\n'), encoding="utf-8")
            with patch("sys.stdin", stdin), contextlib.redirect_stdout(io.StringIO()) as output:
                result = main(
                    [
                        "split",
                        "-",
                        "--output",
                        str(Path(directory) / "bundle"),
                        "--objects-only",
                        "--require-key",
                        "id",
                    ]
                )
            self.assertEqual(result, 1)
            self.assertEqual(json.loads(output.getvalue())["accepted"], 1)

    def test_errors_do_not_echo_source_paths_or_values(self):
        with contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(main(["split", "private-path-canary", "--output", "unused"]), 2)
        self.assertNotIn("private-path-canary", error.getvalue())

    def test_invalid_policy_returns_two(self):
        with tempfile.TemporaryDirectory() as directory:
            stdin = io.TextIOWrapper(io.BytesIO(b"{}"), encoding="utf-8")
            with patch("sys.stdin", stdin), contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(
                    main(
                        [
                            "split",
                            "-",
                            "--output",
                            str(Path(directory) / "new"),
                            "--max-line-bytes",
                            "0",
                        ]
                    ),
                    2,
                )
            self.assertIn("invalid_line_limit", error.getvalue())

    def test_success_without_rejections_returns_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            stdin = io.TextIOWrapper(io.BytesIO(b"{}\n"), encoding="utf-8")
            with patch("sys.stdin", stdin), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["split", "-", "--output", str(Path(directory) / "new")]), 0)


if __name__ == "__main__":
    unittest.main()
