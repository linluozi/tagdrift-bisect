"""Console entry point: run / summarize / bisect / selftest."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

from .bisect import bisect, revert_check
from .fixture import build_injected_repo
from .harness import RevisionRunner
from .summary import load_raw, summarize


def cmd_run(args) -> int:
    scales = tuple(args.scales.split(","))
    runner = RevisionRunner(args.repo, args.workload, worktree=args.worktree)
    failed = []
    try:
        for tag in args.tags.split(","):
            try:
                runner.measure(
                    tag, scales=scales, reps=args.reps,
                    warmup=args.warmup, raw_path=args.out,
                )
                print(f"[ok]   {tag}", file=sys.stderr)
            except Exception as exc:  # noqa: BLE001 - recorded, never hidden
                failed.append({"tag": tag, "error": str(exc)[-300:]})
                print(f"[fail] {tag}: {str(exc)[:200]}", file=sys.stderr)
    finally:
        runner.cleanup()
    if failed:
        with open(args.out + ".errors.json", "w") as fh:
            json.dump(failed, fh, indent=2)
    return 0 if len(failed) < len(args.tags.split(",")) else 1


def cmd_summarize(args) -> int:
    recs = load_raw(args.raw)
    labels = args.labels.split(",") if args.labels else None
    s = summarize(recs, labels)
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(s, fh, indent=2, sort_keys=True)
    for key, cell in sorted(s["cells"].items()):
        if key.endswith("_steps"):
            continue
        print(f"== {key}  noise_floor={s['noise_floor'][key]:.3%}")
        for lab in s["labels"]:
            if lab in cell:
                c = cell[lab]
                print(f"   {lab:>9} median={c['median']*1e3:8.3f} ms "
                      f"p25={c['p25']*1e3:8.3f} p75={c['p75']*1e3:8.3f} n={c['n']}")
        for st in cell.get("_steps", []):
            flag = "SIGNIFICANT" if st["significant"] else ("incomparable" if not st["comparable"] else "-")
            print(f"   step {st['from']} -> {st['to']}: {st['ratio']:.4f}x {flag}")
    return 0


def cmd_bisect(args) -> int:
    res = bisect(
        args.repo, args.workload, args.scale, args.from_rev, args.to_rev,
        reps=args.reps, warmup=args.warmup, direction=args.direction,
    )
    if res.get("status") == "found" and res.get("attributable"):
        res["revert"] = revert_check(
            args.repo, args.workload, args.scale, args.to_rev, res["commit"],
            res["from_median"], reps=args.reps, warmup=args.warmup,
        )
    print(json.dumps(res, indent=2))
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(res, fh, indent=2)
    return 0


def cmd_selftest(args) -> int:
    tmp = tempfile.mkdtemp(prefix="tagdrift-fixture-")
    fx = build_injected_repo(os.path.join(tmp, "repo"), n_commits=12, bad_index=7)
    res = bisect(fx["repo"], "injected", "medium", fx["first"], fx["last"],
                 reps=args.reps, warmup=args.warmup)
    res["expected_commit"] = fx["culprit"]
    res["located_exactly"] = res.get("commit") == fx["culprit"]
    if res.get("status") == "found" and res.get("attributable"):
        res["revert"] = revert_check(
            fx["repo"], "injected", "medium", fx["last"], res["commit"],
            res["from_median"], reps=args.reps, warmup=args.warmup,
        )
    print(json.dumps(res, indent=2))
    return 0 if res.get("located_exactly") else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="tagdrift")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--reps", type=int, default=7)
        p.add_argument("--warmup", type=int, default=3)

    p = sub.add_parser("run")
    p.add_argument("--repo", required=True)
    p.add_argument("--workload", required=True)
    p.add_argument("--tags", required=True)
    p.add_argument("--scales", default="small,medium,large")
    p.add_argument("--out", required=True)
    p.add_argument("--worktree")
    common(p)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("summarize")
    p.add_argument("--raw", required=True)
    p.add_argument("--json")
    p.add_argument("--labels")
    p.set_defaults(func=cmd_summarize)

    p = sub.add_parser("bisect")
    p.add_argument("--repo", required=True)
    p.add_argument("--workload", required=True)
    p.add_argument("--scale", default="medium")
    p.add_argument("--from-rev", required=True)
    p.add_argument("--to-rev", required=True)
    p.add_argument("--direction", choices=("regression", "speedup"),
                   default="regression")
    p.add_argument("--json")
    common(p)
    p.set_defaults(func=cmd_bisect)

    p = sub.add_parser("selftest")
    common(p)
    p.set_defaults(func=cmd_selftest)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
