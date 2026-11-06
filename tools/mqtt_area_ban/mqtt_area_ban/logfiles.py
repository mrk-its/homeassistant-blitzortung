"""Read the mosquitto log incrementally across logrotate's rotations."""

from __future__ import annotations

import gzip
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import IO

from .state import Cursor

_LOGGER = logging.getLogger(__name__)
HEAD_BYTES = 200
MAX_ROTATIONS = 9


class NeedsReplayError(Exception):
    """The cursor's file is gone; sessions must be rebuilt from scratch."""


def _open(path: Path) -> IO[bytes]:
    return gzip.open(path, "rb") if path.suffix == ".gz" else path.open("rb")


def _head(path: Path) -> str:
    with _open(path) as f:
        return f.read(HEAD_BYTES).decode("latin-1")


def _same_file(path: Path, cursor: Cursor) -> bool:
    # The head was saved when the file may have been shorter, so compare as a prefix.
    return bool(cursor.head) and _head(path).startswith(cursor.head)


def _rotated(log: Path, n: int) -> Path | None:
    for candidate in (
        log.with_name(f"{log.name}.{n}"),
        log.with_name(f"{log.name}.{n}.gz"),
    ):
        if candidate.exists():
            return candidate
    return None


class LogFollower:
    """Yields new log lines; then ``cursor`` points past the last complete one."""

    def __init__(self, log: Path) -> None:
        """Follow ``log``; rotated files are ``log.1``, ``log.2.gz``, ..."""
        self.log = log
        self.cursor: Cursor | None = None

    def _read_rotated(self, path: Path, offset: int) -> Iterator[str]:
        with _open(path) as f:
            f.seek(offset)
            for raw in f:
                yield raw.decode("utf-8", "replace")

    def _read_live(self, offset: int) -> Iterator[str]:
        with self.log.open("rb") as f:
            inode = self.log.stat().st_ino
            f.seek(offset)
            pos = offset
            for raw in f:
                if not raw.endswith(b"\n"):
                    break  # mosquitto is still writing this line; read it next time
                pos += len(raw)
                yield raw.decode("utf-8", "replace")
            f.seek(0)
            head = f.read(HEAD_BYTES).decode("latin-1")
        self.cursor = Cursor(inode, pos, head)

    def incremental(self, cursor: Cursor) -> Iterator[str]:
        """Lines written since ``cursor``; NeedsReplayError if some are gone."""
        st = self.log.stat()
        if st.st_ino == cursor.inode:
            if st.st_size < cursor.offset:
                _LOGGER.warning(
                    "%s shrank below the saved offset, reading it from the start",
                    self.log,
                )
                return self._read_live(0)
            # After two rotations the new log can reuse the inode of the gzipped one.
            if not cursor.head or _same_file(self.log, cursor):
                return self._read_live(cursor.offset)
        return self._after_rotation(cursor)

    def _after_rotation(self, cursor: Cursor) -> Iterator[str]:
        first = _rotated(self.log, 1)
        if (
            first is not None
            and first.suffix != ".gz"
            and first.stat().st_ino == cursor.inode
        ):
            return self._chain(first, cursor.offset)
        # Two rotations since the last run: the file was gzipped into a new inode, so
        # recognise it by its first bytes.
        second = _rotated(self.log, 2)
        if first is not None and second is not None and _same_file(second, cursor):
            return self._chain(second, cursor.offset, first)
        raise NeedsReplayError(
            f"the log file at the saved cursor is no longer next to {self.log}"
        )

    def _chain(
        self, older: Path, offset: int, newer: Path | None = None
    ) -> Iterator[str]:
        yield from self._read_rotated(older, offset)
        if newer is not None:
            yield from self._read_rotated(newer, 0)
        yield from self._read_live(0)

    def replay(self, since: int) -> Iterator[str]:
        """All lines, oldest file first, skipping files older than ``since``."""
        for n in range(MAX_ROTATIONS, 0, -1):
            path = _rotated(self.log, n)
            # A rotated file's mtime is its last write: if that predates the
            # broker start, every line in it does.
            if path is not None and path.stat().st_mtime >= since:
                yield from self._read_rotated(path, 0)
        yield from self._read_live(0)
