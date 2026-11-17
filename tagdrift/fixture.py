"""Synthetic ground-truth fixture: a repo whose commits are all semantically
identical and exactly one of which is a pure performance regression."""

from __future__ import annotations

import os
import subprocess

FAST = """\
def work(n):
    total = 0
    for i in range(n):
        total += i % 7
    return total
"""

SLOW = """\
def work(n):
    total = 0
    for i in range(n):
        for _ in range(6):  # injected regression: 6x the inner work
            total += i % 7
        total -= 5 * (i % 7)  # ... with the identical return value
    return total
"""


def _git(repo, *args):
    proc = subprocess.run(
        ["git", "-C", repo, "-c", "user.email=fixture@example.invalid",
         "-c", "user.name=fixture", *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {args} failed: {proc.stderr}")
    return proc.stdout.strip()


def build_injected_repo(path: str, n_commits: int = 12, bad_index: int = 7) -> dict:
    """Create ``path`` with ``n_commits`` commits; commit ``bad_index`` (1-based)
    changes only the constant factor of ``slowlib.work``."""
    os.makedirs(os.path.join(path, "slowlib"), exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    commits = []
    for i in range(1, n_commits + 1):
        if i == 1:
            with open(os.path.join(path, "slowlib", "__init__.py"), "w") as fh:
                fh.write(FAST)
        if i >= bad_index:
            with open(os.path.join(path, "slowlib", "__init__.py"), "w") as fh:
                fh.write(SLOW)
        if i != bad_index:
            # The injected regression touches code only, so that reverting it
            # on a later revision is unambiguous (docs keep changing).
            with open(os.path.join(path, "CHANGELOG.txt"), "a") as fh:
                fh.write(f"release {i}: no behaviour change\n")
        _git(path, "add", "-A")
        _git(path, "commit", "-q", "-m", f"commit {i}: docs {i}")
        commits.append(_git(path, "rev-parse", "HEAD"))
    return {
        "repo": path,
        "commits": commits,
        "bad_index": bad_index,
        "culprit": commits[bad_index - 1],
        "parent": commits[bad_index - 2],
        "first": commits[0],
        "last": commits[-1],
    }
