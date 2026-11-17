"""Workload: parse a real ~1.7 KB pyproject.toml (tomlkit, style-preserving)."""

from __future__ import annotations

import hashlib
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus_real.toml")

SCALES = {"small": 1, "medium": 12, "large": 60}


def make_input(scale: str):
    # A TOML document cannot be concatenated with itself (duplicate keys), so
    # the scale is the number of *whole documents* parsed in one timed unit.
    with open(CORPUS) as fh:
        doc = fh.read()
    return [doc] * SCALES[scale]


def run_once(inp):
    import tomlkit

    return [tomlkit.parse(text) for text in inp]


def digest(inp) -> str:
    import tomlkit

    h = hashlib.sha256()
    for doc in run_once(inp):
        h.update(tomlkit.dumps(doc).encode())
    return h.hexdigest()
