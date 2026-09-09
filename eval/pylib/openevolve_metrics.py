"""Standard reporting contract for projects evaluated by eval/harness.py:
one line of JSON on stdout, {"status": "ok"|"error", "metrics": {...}}.
Handles the JSON-building and exception-safety so each project doesn't have
to re-derive it (and re-risk the escaping bugs that motivated this module).

Available to any project without an import path hassle -- harness.py puts
this directory on PYTHONPATH automatically. Usage:

    from openevolve_metrics import Timer, report, guarded

    def solve():
        ...  # the @evolve-tagged code

    def main():
        with Timer() as t:
            result = solve()
        correct = check(result)
        report(
            status="ok" if correct else "error",
            metrics={"duration_ms": t.elapsed_ms},
            message=None if correct else "result did not match expected value",
        )

    if __name__ == "__main__":
        guarded(main)
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from typing import Any, Callable, Dict, Optional


class Timer:
    """Stopwatch context manager. `elapsed_ms` is set on __exit__.

        with Timer() as t:
            do_work()
        print(t.elapsed_ms)
    """

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        self.elapsed_ms: Optional[float] = None
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000
        return False


def report(status: str = "ok", metrics: Optional[Dict[str, float]] = None, message: Optional[str] = None) -> None:
    """Prints the one-JSON-line-on-stdout contract eval/harness.py parses.
    Call this exactly once, as the last thing your program does."""
    payload: Dict[str, Any] = {"status": status, "metrics": metrics or {}}
    if message is not None:
        payload["message"] = message
    print(json.dumps(payload))


def guarded(main_fn: Callable[[], None]) -> None:
    """Runs main_fn(); an uncaught exception becomes a clean status="error"
    report instead of a crash with no stdout at all. main_fn should call
    report() itself on success -- guarded() only catches what it didn't."""
    try:
        main_fn()
    except Exception as e:  # noqa: BLE001 -- last-resort handler, deliberately broad
        report(
            status="error",
            metrics={},
            message=f"unhandled {type(e).__name__}: {e}\n{traceback.format_exc()}",
        )
        sys.exit(1)
