"""Subprocess helper, replaceable in tests."""

from __future__ import annotations

import subprocess


class ToolError(RuntimeError):
    pass


def run(args: list[str], timeout: float = 20) -> str:
    """Run a command and return stdout; raise ToolError on failure."""
    try:
        p = subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=timeout)
    except FileNotFoundError as e:
        raise ToolError(f"{args[0]} not found") from e
    except subprocess.TimeoutExpired as e:
        raise ToolError(f"{args[0]} timed out") from e
    if p.returncode != 0:
        msg = (p.stderr.strip() or p.stdout.strip()).splitlines()
        raise ToolError(f"{args[0]}: {msg[-1] if msg else f'exit {p.returncode}'}")
    return p.stdout
