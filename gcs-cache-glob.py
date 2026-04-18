#!/usr/bin/env python3
"""Populate the gcs response cache for many files matched from the current directory."""

from __future__ import annotations

import glob
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Sequence, Tuple


USAGE = """Usage:
  gcs-cache-glob [--keep-going] <pattern> [gcs args...]

Examples:
  gcs-cache-glob "*.cpp" --mode request
  gcs-cache-glob --keep-going "**/*.cpp" --mode request --refresh
"""

BAR_WIDTH = 24


def terminal_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def parse_args(argv: Sequence[str]) -> Tuple[bool, str, List[str]]:
    keep_going = False
    pattern = None
    forwarded: List[str] = []

    index = 0
    while index < len(argv):
        arg = argv[index]
        if pattern is None and arg == "--keep-going":
            keep_going = True
        elif pattern is None and arg == "--fail-fast":
            keep_going = False
        elif pattern is None and arg in {"-h", "--help"}:
            print(USAGE.strip())
            raise SystemExit(0)
        elif pattern is None:
            pattern = arg
        else:
            forwarded.append(arg)
        index += 1

    if pattern is None:
        print(USAGE.strip(), file=sys.stderr)
        raise SystemExit(2)

    return keep_going, pattern, forwarded


def resolve_matches(pattern: str) -> List[Path]:
    matches: List[Path] = []
    cwd = Path.cwd()
    for raw_match in glob.glob(pattern, recursive=True):
        candidate = (cwd / raw_match).resolve()
        if candidate.is_file():
            matches.append(candidate)
    unique_matches = sorted(set(matches))
    return unique_matches


def format_progress(current: int, total: int, path: Path) -> str:
    percentage = 100 if total == 0 else int((current / total) * 100)
    filled = BAR_WIDTH if total == 0 else int((current / total) * BAR_WIDTH)
    bar = "#" * filled + "-" * (BAR_WIDTH - filled)
    return f"[{bar}] {current}/{total} [{percentage:3d}%] {path}"


def print_progress(current: int, total: int, path: Path) -> None:
    line = format_progress(current, total, path)
    if sys.stdout.isatty():
        width = terminal_width()
        truncated = line[: max(1, width - 1)]
        print(f"\r{truncated:<{max(1, width - 1)}}", end="", flush=True)
    else:
        print(line, flush=True)


def clear_progress_line() -> None:
    if not sys.stdout.isatty():
        return
    width = terminal_width()
    print(f"\r{' ' * max(1, width - 1)}\r", end="", flush=True)


def main(argv: Sequence[str]) -> int:
    keep_going, pattern, forwarded_args = parse_args(argv)
    matches = resolve_matches(pattern)

    if not matches:
        print(f"No files matched pattern: {pattern}", file=sys.stderr)
        return 1

    script_path = Path(__file__).with_name("summarize-file.py")
    python_executable = sys.executable or "python3"

    failures: List[Tuple[Path, int, str]] = []
    total = len(matches)

    for index, file_path in enumerate(matches, start=1):
        relative_path = file_path.relative_to(Path.cwd())
        print_progress(index, total, relative_path)
        command = [python_executable, str(script_path), str(relative_path), *forwarded_args]
        completed = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        if completed.returncode == 0:
            continue

        error_text = completed.stderr.strip() or f"exit code {completed.returncode}"
        failures.append((relative_path, completed.returncode, error_text))
        if not keep_going:
            clear_progress_line()
            print(
                f"Failed at {index}/{total}: {relative_path} ({completed.returncode})",
                file=sys.stderr,
            )
            print(error_text, file=sys.stderr)
            return completed.returncode

    clear_progress_line()
    if failures:
        print(
            f"Completed with failures: {total - len(failures)}/{total} succeeded, "
            f"{len(failures)} failed.",
            file=sys.stderr,
        )
        for failed_path, return_code, error_text in failures:
            print(f"- {failed_path} ({return_code})", file=sys.stderr)
            print(f"  {error_text}", file=sys.stderr)
        return 1

    print(f"Completed: {total}/{total} files processed.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
