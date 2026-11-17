"""Workload for the synthetic ground-truth fixture (see tagdrift/fixture.py)."""

from __future__ import annotations

import hashlib

SCALES = {"small": 1, "medium": 2, "large": 4}
BASE = 800_000


def make_input(scale: str):
    return BASE * SCALES[scale]


def run_once(n):
    import slowlib

    return slowlib.work(n)


def digest(inp) -> str:
    return hashlib.sha256(str(run_once(inp)).encode()).hexdigest()
