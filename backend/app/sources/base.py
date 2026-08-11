"""Base class for detection sources.

Every source runs its own blocking ``run()`` loop in a daemon thread and pushes
Detection objects through the thread-safe ``emit`` callable it is given. This
keeps hardware libraries (scapy, pyrtlsdr) — which are blocking — uniform with
the pure-Python simulator.
"""
from __future__ import annotations
import threading
from typing import Callable

from ..models import Detection

EmitFn = Callable[[Detection], None]


class Source:
    name = "base"

    def __init__(self, config: dict, emit: EmitFn) -> None:
        self.config = config
        self.emit = emit
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._guarded_run,
                                        name=f"src-{self.name}", daemon=True)
        self._thread.start()

    def _guarded_run(self) -> None:
        try:
            self.run()
        except Exception as exc:  # never let one source kill the process
            import logging
            logging.getLogger("dronedingo").exception(
                "source %s crashed: %s", self.name, exc)

    def run(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def stop(self) -> None:
        self._stop.set()

    def sleep(self, seconds: float) -> None:
        """Interruptible sleep that returns early when stopping."""
        self._stop.wait(seconds)
