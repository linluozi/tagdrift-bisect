"""Workload: the two operations pip does on every candidate (packaging)."""

from __future__ import annotations

import hashlib
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus_versions.txt")

# scale -> how many passes over the real corpus of 95 installed-distribution
# version strings (post/dev/epoch/local segments are all present).
SCALES = {"small": 1, "medium": 10, "large": 50}


def _corpus():
    with open(CORPUS) as fh:
        return [ln.strip() for ln in fh if ln.strip()]


def make_input(scale: str):
    return _corpus() * SCALES[scale]


def run_once(inp):
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version

    spec = SpecifierSet(">=1.0,<30.0,!=2.1.*")
    return [spec.contains(Version(v)) for v in inp]


def digest(inp) -> str:
    out = run_once(inp)
    h = hashlib.sha256()
    h.update(("".join("1" if b else "0" for b in out)).encode())
    return h.hexdigest()
