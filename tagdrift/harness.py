"""Revision harness: check out an upstream revision and measure it in isolation.

All measurements happen inside a throwaway ``git worktree`` under ``/tmp``; the
only artefacts written into this project are the raw JSONL samples.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CHILD = os.path.join(HERE, "bench_child.py")


def git(repo: str, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def prune_pycache(tree: str) -> int:
    """Byte-code caches must never survive a revision switch."""
    n = 0
    for dirpath, dirnames, _ in os.walk(tree):
        for d in list(dirnames):
            if d == "__pycache__":
                shutil.rmtree(os.path.join(dirpath, d), ignore_errors=True)
                dirnames.remove(d)
                n += 1
    return n


class RevisionRunner:
    """Reuses one worktree and switches revisions inside it."""

    def __init__(self, repo: str, workload: str, worktree: str | None = None):
        self.repo = os.path.abspath(repo)
        self.workload = workload
        self.worktree = worktree or tempfile.mkdtemp(prefix=f"tagdrift-wt-{workload}-")
        self._attached = False

    def _attach(self, rev: str) -> None:
        if not self._attached:
            git(self.repo, "worktree", "add", "--detach", self.worktree, rev)
            self._attached = True
        else:
            git(self.worktree, "checkout", "-q", "--detach", rev)

    def measure(
        self,
        rev: str,
        scales: tuple[str, ...] = ("small", "medium", "large"),
        reps: int = 7,
        warmup: int = 3,
        raw_path: str | None = None,
        checkout: bool = True,
        label: str | None = None,
    ) -> list[dict]:
        if checkout:
            self._attach(rev)
        prune_pycache(self.worktree)
        out = raw_path or os.path.join(
            tempfile.gettempdir(), f"tagdrift-{self.workload}-{abs(hash(rev))}.jsonl"
        )
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        cmd = [
            sys.executable,
            CHILD,
            "--repo",
            self.worktree,
            "--workload",
            self.workload,
            "--scales",
            ",".join(scales),
            "--reps",
            str(reps),
            "--warmup",
            str(warmup),
            "--out",
            out,
            "--label",
            label or rev,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            raise RuntimeError(
                f"bench_child failed for {rev}:\n{proc.stderr.strip()[-2000:]}"
            )
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def cleanup(self) -> None:
        if self._attached:
            git(self.repo, "worktree", "remove", "--force", self.worktree, check=False)
            self._attached = False
        shutil.rmtree(self.worktree, ignore_errors=True)
