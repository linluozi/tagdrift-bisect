"""Workload: full argument parsing of a realistic 27-parameter CLI (click).

``Command.parse_args`` is the real hot path used by every ``cli.main()``: type
conversion, default filling, variadic arguments and option normalisation all
run inside it, and it exists unchanged from click 5.x to 8.5.
"""

from __future__ import annotations

import hashlib

SCALES = {"small": 20, "medium": 120, "large": 600}

ARGV = (
    ["--opt-0=alpha"]
    + [f"--opt-{i}=value-{i}" for i in range(1, 12)]
    + ["--flag-1", "--flag-3", "src/a.txt", "src/b.txt", "--", "trailing"]
)


def _make_command():
    import click

    params = []
    for i in range(20):
        params.append(click.Option([f"--opt-{i}"], type=click.STRING, default=None))
    for i in range(5):
        params.append(click.Option([f"--flag-{i}"], is_flag=True, default=False))
    params.append(click.Argument(["paths"], nargs=-1))
    return click.Command("app", params=params)


def make_input(scale: str):
    return list(ARGV) * SCALES[scale]


def run_once(inp):
    # Argument parsing consumes argv one command at a time, as a real CLI does.
    chunks = []
    n = len(ARGV)
    for i in range(0, len(inp), n):
        chunks.append(list(inp[i : i + n]))
    return parse_all(chunks)


def parse_all(chunks):
    cmd = _make_command()
    out = []
    for argv in chunks:
        ctx = _new_context(cmd)
        rest = cmd.parse_args(ctx, list(argv))
        opts = dict(ctx.params)
        out.append((tuple(sorted((k, repr(v)) for k, v in opts.items())), len(rest)))
    return out


def _new_context(cmd):
    import click

    return click.Context(cmd)


def digest(inp) -> str:
    h = hashlib.sha256()
    for shape, nargs in run_once(inp):
        h.update(repr(shape).encode())
        h.update(b"|")
        h.update(str(nargs).encode())
    return h.hexdigest()
