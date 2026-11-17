"""Measure 2 real upstreams across >=15 release tags each.

Produces benchmark/raw/<lib>.jsonl (every timed sample) and
benchmark/summary.json (medians, p25/p75, drift steps, noise floors).

Run with:  python benchmark/run_real.py --src /tmp/src_<lib> ...
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tagdrift.harness import RevisionRunner  # noqa: E402
from tagdrift.summary import load_raw, summarize  # noqa: E402

LIBS = {
    "packaging": {
        "tags": ["21.1", "21.2", "21.3", "22.0", "23.0", "23.1", "23.2", "24.0",
                 "24.1", "24.2", "25.0", "26.0", "26.1", "26.2", "26.3"],
        "url": "https://github.com/pypa/packaging",
    },
    "click": {
        "tags": ["8.1.6", "8.1.7", "8.1.8", "8.2.0", "8.2.1", "8.2.2", "8.3.0",
                 "8.3.1", "8.3.2", "8.3.3", "8.4.0", "8.4.1", "8.4.2", "8.5.0",
                 "8.5.1"],
        "url": "https://github.com/pallets/click",
    },
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=7)
    ap.add_argument("--warmup", type=int, default=3)
    ap.add_argument("--src", default="/tmp", help="directory holding src_<lib> clones")
    ap.add_argument("--only", default="")
    ap.add_argument("--summary-only", action="store_true")
    ap.add_argument("--outdir", default=os.path.join(ROOT, "benchmark"))
    args = ap.parse_args()

    rawdir = os.path.join(args.outdir, "raw")
    os.makedirs(rawdir, exist_ok=True)
    report = {"reps": args.reps, "warmup": args.warmup, "libs": {}}
    for lib, meta in LIBS.items():
        if args.only and lib != args.only:
            continue
        repo = os.path.join(args.src, f"src_{lib}")
        raw = os.path.join(rawdir, f"{lib}.jsonl")
        if args.summary_only:
            if os.path.exists(raw):
                report["libs"][lib] = {"url": meta["url"], "repo": repo,
                                       "tags_ok": [], "tags_failed": [],
                                       "summary": summarize(load_raw(raw))}
            continue
        if os.path.exists(raw):
            os.remove(raw)
        runner = RevisionRunner(repo, lib, worktree=f"/tmp/td-wt-{lib}")
        ok, failed = [], []
        try:
            for tag in meta["tags"]:
                try:
                    runner.measure(tag, reps=args.reps, warmup=args.warmup, raw_path=raw)
                    ok.append(tag)
                    print(f"[{lib}] {tag} ok", flush=True)
                except Exception as exc:  # noqa: BLE001
                    failed.append({"tag": tag, "error": str(exc)[-300:]})
                    print(f"[{lib}] {tag} FAIL {str(exc)[:160]}", flush=True)
            # A/A control: the first tag measured a second time under a
            # distinct label. Any step tag0 -> tag0~AA is pure measurement
            # error and must stay inside the noise floor.
            ctrl_label = meta["tags"][0] + "~AA"
            runner.measure(meta["tags"][0], reps=args.reps, warmup=args.warmup,
                           raw_path=raw, label=ctrl_label)
            print(f"[{lib}] A/A control {ctrl_label} ok", flush=True)
        finally:
            runner.cleanup()
        recs = load_raw(raw) if os.path.exists(raw) else []
        if not recs:
            raise RuntimeError(f"{lib}: no samples produced; see log above")
        s = summarize(recs)
        report["libs"][lib] = {
            "url": meta["url"],
            "repo": repo,
            "tags_ok": ok,
            "tags_failed": failed,
            "summary": s,
        }
    with open(os.path.join(args.outdir, "summary.json"), "w") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
    print("wrote", os.path.join(args.outdir, "summary.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
