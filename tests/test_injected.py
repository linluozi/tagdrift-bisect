"""Ground-truth test: an injected, purely-timing regression must be located to
exactly one commit by the bisect and neutralised by the revert check."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tagdrift.bisect import bisect, revert_check  # noqa: E402
from tagdrift.fixture import build_injected_repo  # noqa: E402

REPS = int(os.environ.get("TAGDRIFT_TEST_REPS", "7"))


class TestInjectedRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="tagdrift-test-")
        cls.fx = build_injected_repo(os.path.join(cls.tmp, "repo"), n_commits=12,
                                     bad_index=7)
        # A/A instability is an artefact of a loaded/shared machine, not of the
        # tool: re-measure up to 3 times before reporting 'unstable'.
        for _ in range(3):
            cls.res = bisect(cls.fx["repo"], "injected", "medium",
                             cls.fx["first"], cls.fx["last"], reps=REPS, warmup=3)
            if cls.res.get("status") != "unstable":
                break

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_aa_control_stable(self):
        self.assertLessEqual(self.res["control_deviation"], self.res["effective_tolerance"])
        self.assertNotEqual(self.res.get("status"), "unstable")

    def test_endpoint_ratio_is_real(self):
        # The fixture injects a 6x inner loop; require a visible endpoint step.
        self.assertGreater(self.res["endpoint_ratio"], 2.0)

    def test_locates_exact_commit(self):
        self.assertEqual(self.res["status"], "found")
        self.assertEqual(self.res["commit"], self.fx["culprit"])
        self.assertEqual(self.res["parent"], self.fx["parent"])

    def test_build_count_logarithmic(self):
        # bisect must not be a linear scan: probes <= ceil(log2(11)) and the
        # fixed overhead is 5 measurements (2 endpoints, 1 A/A control,
        # parent + culprit verification).
        self.assertLessEqual(len(self.res["probes"]), 4)
        self.assertLessEqual(self.res["builds"], 9)

    def test_revert_returns_to_baseline(self):
        rev = revert_check(self.fx["repo"], "injected", "medium", self.fx["last"],
                           self.fx["culprit"], self.res["from_median"], reps=REPS,
                           warmup=3)
        self.assertTrue(rev["ok"], rev)
        self.assertTrue(rev["within_tolerance"], rev)
        self.assertLess(abs(rev["ratio_vs_baseline"] - 1.0), 0.02)


if __name__ == "__main__":
    unittest.main()
