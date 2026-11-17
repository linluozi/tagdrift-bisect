"""Runs one workload module against a checked-out upstream tree.

Executed as a *separate process* per revision so that import state, caches and
allocator behaviour cannot leak from one tag to the next.  Writes one JSON
object per timed sample to ``--out`` (append mode) and echoes them on stdout.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load_workload(name: str):
    path = os.path.join(ROOT, "workloads", name + ".py")
    if not os.path.exists(path):
        path = os.path.join(ROOT, "workloads", name + "_wl.py")
    spec = importlib.util.spec_from_file_location("td_workload_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="path of the upstream checkout")
    ap.add_argument("--workload", required=True)
    ap.add_argument("--scales", required=True, help="comma separated scale names")
    ap.add_argument("--reps", type=int, default=7)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--out", required=True)
    ap.add_argument("--label", default="tag", help="label stored with every sample")
    args = ap.parse_args(argv)

    sys.dont_write_bytecode = True
    # The upstream checkout *must* win over anything installed in site-packages.
    # Insert both the repo root (flat layouts, e.g. tomlkit/) and src/ (e.g.
    # click, packaging) so every supported layout resolves to the checkout.
    for cand in (os.path.join(args.repo, "src"), args.repo):
        if os.path.isdir(cand):
            sys.path.insert(0, cand)

    wl = load_workload(args.workload)
    records = []
    for scale in args.scales.split(","):
        inp = wl.make_input(scale)
        digest = wl.digest(inp)
        for _ in range(args.warmup):
            wl.run_once(inp)
        for i in range(args.reps):
            t0 = time.perf_counter()
            wl.run_once(inp)
            dt = time.perf_counter() - t0
            records.append(
                {
                    "label": args.label,
                    "workload": args.workload,
                    "scale": scale,
                    "rep": i,
                    "seconds": dt,
                    "digest": digest,
                }
            )
    with open(args.out, "a") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
    json.dump(records, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
