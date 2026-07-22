"""Portable, minimal filesystem lock for M2 local checkpoints."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional


if os.name == "nt":  # pragma: no cover - platform specific branch
    import msvcrt

    _LOCK_BLOCK = True
else:  # pragma: no cover - platform specific branch
    import fcntl

    _LOCK_BLOCK = False


class FileLock:
    """Exclusive cross-process lock with best-effort nonblocking retries."""

    def __init__(self, path: Path, timeout: float = 5.0, retry_interval: float = 0.05) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if retry_interval <= 0:
            raise ValueError("retry_interval must be positive")
        self.path = Path(path)
        self.timeout = timeout
        self.retry_interval = retry_interval
        self._handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout

        while True:
            handle = open(self.path, "a+b")
            try:
                handle.seek(0)
                if os.name == "nt":
                    handle.seek(0, os.SEEK_END)
                    if handle.tell() == 0:
                        handle.write(b"\0")
                        handle.flush()
                        os.fsync(handle.fileno())
                    handle.seek(0)

                if _LOCK_BLOCK:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                handle.close()
                if time.monotonic() >= deadline:
                    raise RuntimeError("unable to acquire lock") from exc
                time.sleep(self.retry_interval)
                continue
            else:
                self._handle = handle
                return

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            self._handle.seek(0)
            if _LOCK_BLOCK:
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            try:
                self._handle.close()
            finally:
                self._handle = None

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()
