"""Binary search for the first commit that introduced a measured step change.

The search is deliberately conservative: it only reports a commit when the
probe's median time lands on the slow side of the midpoint between the two
endpoint medians, and it runs an A/A control first (same revision measured
twice); if the control deviates by more than ``control_tol`` the result is
marked ``unstable`` instead of being reported as a regression.
"""

from __future__ import annotations

import statistics

from .harness import RevisionRunner, git


def commits_between(repo: str, a: str, b: str) -> list[str]:
    out = git(repo, "rev-list", "--first-parent", "--reverse", f"{a}..{b}")
    return [ln for ln in out.splitlines() if ln]


def _median_time(runner: RevisionRunner, rev: str, scale: str, reps: int, warmup: int):
    recs = runner.measure(rev, (scale,), reps=reps, warmup=warmup)
    times = sorted(r["seconds"] for r in recs)
    med = statistics.median(times)
    q1, q3 = times[len(times) // 4], times[(3 * len(times)) // 4]
    rel_iqr = (q3 - q1) / med if med else float("inf")
    return med, rel_iqr, recs


def bisect(
    repo: str,
    workload: str,
    scale: str,
    from_rev: str,
    to_rev: str,
    reps: int = 7,
    warmup: int = 3,
    control_tol: float = 0.02,
    direction: str = "regression",
) -> dict:
    runner = RevisionRunner(repo, workload)
    try:
        fast, fast_iqr, _ = _median_time(runner, from_rev, scale, reps, warmup)
        slow, slow_iqr, _ = _median_time(runner, to_rev, scale, reps, warmup)
        # A/A control: measure the *from* revision a second time.
        ctrl, ctrl_iqr, _ = _median_time(runner, from_rev, scale, reps, warmup)
        control_dev = abs(ctrl - fast) / fast if fast else float("inf")
        # Tolerance is the larger of the requested one and 3x the within-tag
        # robust spread: a 2% gate is meaningless on a workload whose own
        # repeated medians move by more than that.
        eff_tol = max(control_tol, 3.0 * max(fast_iqr, ctrl_iqr))
        result = {
            "repo": repo,
            "workload": workload,
            "scale": scale,
            "from_rev": from_rev,
            "to_rev": to_rev,
            "from_median": fast,
            "to_median": slow,
            "control_median": ctrl,
            "control_deviation": control_dev,
            "effective_tolerance": eff_tol,
            "within_tag_rel_iqr": {"from": fast_iqr, "to": slow_iqr, "control": ctrl_iqr},
            "endpoint_ratio": slow / fast if fast else None,
            "direction": direction,
        }
        if control_dev > eff_tol:
            result["status"] = "unstable"
            result["reason"] = (
                f"A/A control deviated {control_dev:.2%} > {eff_tol:.2%} (effective)"
            )
            return result
        if direction == "regression":
            if not (slow > fast):
                result["status"] = "no-change"
                return result
        else:  # speedup: the later revision is the fast one
            if not (slow < fast):
                result["status"] = "no-change"
                return result

        commits = commits_between(repo, from_rev, to_rev)
        if not commits:
            result["status"] = "no-commits"
            return result
        midpoint = (fast + slow) / 2.0
        lo, hi = 0, len(commits) - 1
        probes = []
        slow_side = (lambda t: t > midpoint) if direction == "regression" else (lambda t: t < midpoint)
        while lo < hi:
            mid = (lo + hi) // 2
            t, _, _ = _median_time(runner, commits[mid], scale, reps, warmup)
            hit = slow_side(t)
            probes.append({"commit": commits[mid], "median": t,
                           "side": ("changed" if hit else "baseline")})
            if hit:
                hi = mid
            else:
                lo = mid + 1
        culprit = commits[lo]
        parent = git(repo, "rev-parse", f"{culprit}^")
        # Attribution gate: a single commit is only reported when the
        # culprit/parent difference is larger than the measured noise floor.
        # A root cause spread over several commits collapses into "diffuse".
        t_parent, _, _ = _median_time(runner, parent, scale, reps, warmup)
        t_culprit, _, _ = _median_time(runner, culprit, scale, reps, warmup)
        separation = abs(t_parent - t_culprit) / max(t_parent, t_culprit)
        attributable = separation > eff_tol
        result.update(
            {
                "status": "found" if attributable else "diffuse",
                "commit": culprit,
                "parent": parent,
                "parent_median": t_parent,
                "culprit_median": t_culprit,
                "separation": separation,
                "attributable": attributable,
                "commits_in_range": len(commits),
                "probes": probes,
                "builds": len(probes) + 5,
                "subject": git(repo, "log", "-1", "--format=%h %s", culprit),
            }
        )
        return result
    finally:
        runner.cleanup()


def _probe_time(probes, commit):
    for p in probes:
        if p["commit"] == commit:
            return p["median"]
    return None


def revert_check(
    repo: str,
    workload: str,
    scale: str,
    later_rev: str,
    culprit: str,
    baseline_median: float,
    reps: int = 7,
    warmup: int = 3,
    tol: float = 0.02,
) -> dict:
    """Check out ``later_rev``, reverse-apply ``culprit``, and re-measure."""
    runner = RevisionRunner(repo, workload)
    try:
        runner.measure(later_rev, (scale,), reps=1, warmup=0)
        wt = runner.worktree
        import subprocess

        reverted = False
        reasons = []
        # Order matters: try the non-destructive reverse patch first on a clean
        # tree, and only then the porcelain revert. Both can legitimately fail
        # when later commits touched the same lines; that is reported, not
        # papered over.
        patch = subprocess.run(
            ["git", "-C", wt, "show", "--format=", culprit],
            capture_output=True, text=True,
        ).stdout
        subprocess.run(["git", "-C", wt, "reset", "--hard", later_rev],
                       capture_output=True, text=True)
        ap = subprocess.run(
            ["git", "-C", wt, "apply", "-R", "--3way", "-"],
            input=patch, capture_output=True, text=True,
        )
        code_only = False
        if ap.returncode == 0:
            reverted = True
        else:
            reasons.append("git apply -R: " + ap.stderr.strip()[-200:])
            # Documentation/changelog files change constantly and are not part
            # of the measured behaviour; retry the reverse patch on code only.
            subprocess.run(["git", "-C", wt, "reset", "--hard", later_rev],
                           capture_output=True, text=True)
            ap2 = subprocess.run(
                ["git", "-C", wt, "apply", "-R", "--3way",
                 "--exclude=CHANGES.rst", "--exclude=CHANGES.md",
                 "--exclude=NEWS.rst", "--exclude=docs/*", "--exclude=*.md", "-"],
                input=patch, capture_output=True, text=True,
            )
            if ap2.returncode == 0:
                reverted = True
                code_only = True
            else:
                reasons.append("git apply -R (code only): " + ap2.stderr.strip()[-200:])
            subprocess.run(["git", "-C", wt, "reset", "--hard", later_rev],
                           capture_output=True, text=True)
            proc = subprocess.run(
                ["git", "-C", wt, "revert", "--no-commit", "--no-edit", culprit],
                capture_output=True, text=True,
            )
            if proc.returncode == 0:
                reverted = True
            else:
                reasons.append("git revert: " + proc.stderr.strip()[-200:])
        if not reverted:
            return {"ok": False, "clean": False, "reason": " | ".join(reasons)}
        # checkout=False: keep the reverted working tree we just produced.
        recs = runner.measure(later_rev, (scale,), reps=reps, warmup=warmup, checkout=False)
        times = sorted(r["seconds"] for r in recs)
        after = statistics.median(times)
        q1, q3 = times[len(times) // 4], times[(3 * len(times)) // 4]
        rel_iqr = (q3 - q1) / after if after else float("inf")
        ratio = after / baseline_median if baseline_median else None
        # Two verdicts are reported: the strict +-2% target, and the
        # noise-aware one (3x this revision's own within-tag relative IQR).
        recruiter = (lambda r: abs(r - 1.0) <= tol)
        return {
            "ok": True,
            "clean": not code_only,
            "code_only_revert": code_only,
            "culprit": culprit,
            "later_rev": later_rev,
            "reverted_median": after,
            "reverted_rel_iqr": rel_iqr,
            "baseline_median": baseline_median,
            "ratio_vs_baseline": ratio,
            "within_tolerance": bool(ratio is not None and abs(ratio - 1.0) <= tol),
            "within_noise_floor": bool(ratio is not None and abs(ratio - 1.0) <= max(tol, 3.0 * rel_iqr)),
        }
    finally:
        runner.cleanup()
