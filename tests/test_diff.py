"""Differential tests.

Two independent claims are checked:

1. ``TestSemanticsPreservingFixture`` - the injected regression changes timing
   only: on >=1000 *distinct* inputs (sha256-deduplicated) the fast and slow
   implementations return byte-identical strings.  Without this, attributing
   the timing change to that commit would be meaningless.
2. ``TestRealCorpusDigests`` - on the three real upstreams, every measured
   release tag produced the same semantic digest for the same corpus, i.e. the
   timing comparison is between semantically identical revisions.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tagdrift.fixture import FAST, SLOW  # noqa: E402

N_SAMPLES = 1200


def _run_source(source: str, n: int) -> str:
    ns: dict = {}
    exec(compile(source, "<fixture>", "exec"), ns)  # noqa: S102 - fixture code
    return str(ns["work"](n))


class TestSemanticsPreservingFixture(unittest.TestCase):
    def test_unique_input_count(self):
        inputs = [1000 + i for i in range(N_SAMPLES)]
        digests = {hashlib.sha256(str(i).encode()).hexdigest() for i in inputs}
        self.assertEqual(len(digests), N_SAMPLES, "inputs are not distinct")

    def test_1200_unique_inputs_byte_identical(self):
        mismatches = []
        seen = set()
        for i in range(N_SAMPLES):
            n = 1000 + i
            key = hashlib.sha256(str(n).encode()).hexdigest()
            if key in seen:  # pragma: no cover - guard, never taken
                continue
            seen.add(key)
            fast = _run_source(FAST, n)
            slow = _run_source(SLOW, n)
            if fast != slow:
                mismatches.append(n)
        self.assertEqual(mismatches, [])
        self.assertEqual(len(seen), N_SAMPLES)

    def test_values_actually_vary(self):
        vals = {_run_source(FAST, 1000 + i) for i in range(40)}
        self.assertGreater(len(vals), 30)


class TestRealCorpusDigests(unittest.TestCase):
    RAWDIR = os.path.join(ROOT, "benchmark", "raw")

    def _digests(self, lib):
        path = os.path.join(self.RAWDIR, f"{lib}.jsonl")
        if not os.path.exists(path):
            self.skipTest(f"raw samples for {lib} absent")
        per_cell = {}
        labels = set()
        with open(path) as fh:
            for line in fh:
                r = json.loads(line)
                if r["label"].endswith("~AA"):
                    continue
                labels.add(r["label"])
                per_cell.setdefault((r["scale"], r["digest"]), set()).add(r["label"])
        return per_cell, labels

    def test_digest_identical_across_all_tags(self):
        for lib in ("packaging", "click", "tomlkit"):
            per_cell, labels = self._digests(lib)
            if not labels:
                self.skipTest("no raw data")
            by_scale = {}
            for (scale, digest), labs in per_cell.items():
                by_scale.setdefault(scale, set()).add(digest)
            for scale, digests in by_scale.items():
                self.assertEqual(
                    len(digests), 1,
                    f"{lib}/{scale}: {len(digests)} distinct digests across "
                    f"{len(labels)} tags -> revisions are not comparable",
                )


if __name__ == "__main__":
    unittest.main()
