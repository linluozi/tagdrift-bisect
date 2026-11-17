"""Aggregation and drift detection over raw samples."""

from __future__ import annotations

import json
import statistics
from collections import defaultdict


def median(xs):
    return statistics.median(xs)


def pct(xs, q):
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def load_raw(path: str) -> list[dict]:
    out = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def group(records: list[dict]) -> dict:
    g = defaultdict(list)
    for r in records:
        g[(r["workload"], r["scale"], r["label"])].append(r)
    return g


def summarize(records: list[dict], labels: list[str] | None = None) -> dict:
    """Per (workload, scale, label): median/p25/p75, the relative IQR and the
    number of distinct semantic digests seen (a digest change means the
    revisions are not comparable on that workload)."""
    g = group(records)
    scales = sorted({k[1] for k in g}, key=lambda s: ["small", "medium", "large"].index(s) if s in ("small", "medium", "large") else 99)
    workloads = sorted({k[0] for k in g})
    if labels is None:
        labels = []
        for w in workloads:
            for s in scales:
                for k in g:
                    if k[0] == w and k[1] == s and k[2] not in labels:
                        labels.append(k[2])
    out = {"scales": scales, "labels": labels, "cells": {}, "noise_floor": {}}
    for w in workloads:
        for s in scales:
            cell = {}
            for lab in labels:
                rs = g.get((w, s, lab), [])
                if not rs:
                    continue
                secs = [r["seconds"] for r in rs]
                med = median(secs)
                cell[lab] = {
                    "n": len(secs),
                    "median": med,
                    "p25": pct(secs, 0.25),
                    "p75": pct(secs, 0.75),
                    "rel_iqr": (pct(secs, 0.75) - pct(secs, 0.25)) / med if med else None,
                    "digests": sorted({r["digest"] for r in rs}),
                }
            if not cell:
                continue
            # Robust noise floor: median relative IQR across revisions.
            rq = [c["rel_iqr"] for c in cell.values() if c["rel_iqr"] is not None]
            floor = median(rq) if rq else 0.0
            chain = [l for l in labels if not l.endswith("~AA")]
            controls = [l for l in labels if l.endswith("~AA")]
            steps = []
            for i in range(len(chain) - 1):
                a, b = cell.get(chain[i]), cell.get(chain[i + 1])
                if not a or not b:
                    continue
                ratio = b["median"] / a["median"]
                comparable = a["digests"] == b["digests"]
                steps.append(
                    {
                        "from": chain[i],
                        "to": chain[i + 1],
                        "ratio": ratio,
                        "comparable": comparable,
                        "significant": comparable
                        and abs(ratio - 1.0) > max(3.0 * floor, 0.02),
                    }
                )
            ctrl = {}
            for c in controls:
                base = c[: -len("~AA")]
                if base in cell and c in cell:
                    ctrl[c] = {
                        "vs": base,
                        "ratio": cell[c]["median"] / cell[base]["median"],
                        "within_3x_floor": abs(cell[c]["median"] / cell[base]["median"] - 1.0)
                        <= max(3.0 * floor, 0.02),
                    }
            out["cells"][f"{w}/{s}"] = cell
            out["noise_floor"][f"{w}/{s}"] = floor
            out["cells"][f"{w}/{s}"]["_steps"] = steps
            out["cells"][f"{w}/{s}"]["_control"] = ctrl
            out.setdefault("aa_control", {})[f"{w}/{s}"] = ctrl
    return out
