"""An executable recovery demonstration using intentionally synthetic input."""

from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path

from jsonl_rescue.core import reassemble, split


def main() -> None:
    source = b'{"id":1}\r\n{"id":2,}\n{"id":3}'
    with tempfile.TemporaryDirectory(prefix="jsonl-rescue-demo-") as directory:
        root = Path(directory)
        report = split(io.BytesIO(source), root / "bundle")
        assert report["accepted"] == 2 and report["rejected"] == 1
        restored = reassemble(root / "bundle", root / "original.bin")
        assert (root / "original.bin").read_bytes() == source
        print(
            json.dumps(
                {
                    "accepted": 2,
                    "rejected": 1,
                    "round_trip": "byte-identical",
                    "source_sha256": restored["sha256"],
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
