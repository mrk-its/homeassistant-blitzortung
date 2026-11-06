"""Live client sessions, log cursor and bans, persisted as one JSON file."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import shutil
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .area import HELLO_TOPIC, ip_usage
from .logparse import Connect, End, Event, Subscribe, Unsubscribe

STATE_VERSION = 1


class StateError(Exception):
    """The state file exists but cannot be used."""


class LockBusyError(Exception):
    """Another instance holds the lock."""


@dataclass
class Session:
    """One connected client."""

    ip: str
    topics: set[str] = field(default_factory=set)
    ha: bool = False


@dataclass
class Peak:
    """Largest area an IP had at once, with and without its HA clients."""

    all: float = 0.0
    non_ha: float = 0.0
    families: dict[str, int] = field(default_factory=dict)


@dataclass
class Cursor:
    """Position in the log; ``head`` identifies the file after rotation."""

    inode: int
    offset: int
    head: str


@dataclass
class State:
    """Everything the tool remembers between runs."""

    broker_start: int | None = None
    cursor: Cursor | None = None
    sessions: dict[str, Session] = field(default_factory=dict)
    bans: dict[str, int] = field(default_factory=dict)  # ip -> expiry, epoch seconds
    peaks: dict[str, Peak] = field(default_factory=dict)
    _by_ip: dict[str, set[str]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        """Index sessions by IP."""
        for cid, session in self.sessions.items():
            self._by_ip.setdefault(session.ip, set()).add(cid)

    def __eq__(self, other: object) -> bool:
        """Compare persisted fields only."""
        if not isinstance(other, State):
            return NotImplemented
        return self.to_json() == other.to_json()

    __hash__ = None  # type: ignore[assignment]

    def reset_sessions(self, broker_start: int) -> None:
        """Forget all sessions: the broker (re)started at ``broker_start``."""
        for ip in list(self._by_ip):
            self.record_peak(ip)
        self.sessions.clear()
        self._by_ip.clear()
        self.broker_start = broker_start

    def record_peak(self, ip: str) -> None:
        """Remember the IP's current area if it is the largest since the last run."""
        clients = {cid: self.sessions[cid] for cid in self._by_ip.get(ip, ())}
        every = ip_usage(clients, exclude_ha=False).get(ip)
        if every is None or every.area <= 0:
            return
        non_ha = ip_usage(clients, exclude_ha=True)[ip]
        peak = self.peaks.setdefault(ip, Peak())
        if every.area > peak.all:
            peak.all = every.area
            peak.families = dict(every.families)
        peak.non_ha = max(peak.non_ha, non_ha.area)

    def _end(self, cid: str) -> None:
        # Clients that reconnect every minute are rarely connected when the daily run
        # looks, so their area is taken when each session ends.
        session = self.sessions.get(cid)
        if session is None:
            return
        self.record_peak(session.ip)
        del self.sessions[cid]
        self._by_ip[session.ip].discard(cid)
        if not self._by_ip[session.ip]:
            del self._by_ip[session.ip]

    def apply(self, event: Event) -> None:
        """Apply one log event; events from before the broker start are stale."""
        if self.broker_start is not None and event.ts < self.broker_start:
            return
        match event:
            case Connect(client_id=cid, ip=ip):
                self._end(cid)
                self.sessions[cid] = Session(ip)
                self._by_ip.setdefault(ip, set()).add(cid)
            case End(client_id=cid):
                self._end(cid)
            case Subscribe(client_id=cid, topic=topic):
                if session := self.sessions.get(cid):
                    session.topics.add(topic)
                    session.ha = session.ha or topic == HELLO_TOPIC
            case Unsubscribe(client_id=cid, topic=topic):
                if session := self.sessions.get(cid):
                    session.topics.discard(topic)

    def drop_expired_bans(self, now: float) -> None:
        """Remove bans whose timeout has passed."""
        self.bans = {ip: exp for ip, exp in self.bans.items() if exp > now}

    def to_json(self) -> dict:
        """Serialize to plain JSON types."""
        return {
            "version": STATE_VERSION,
            "broker_start": self.broker_start,
            "cursor": None if self.cursor is None else vars(self.cursor),
            "sessions": {
                cid: {"ip": s.ip, "topics": sorted(s.topics), "ha": s.ha}
                for cid, s in self.sessions.items()
            },
            "bans": self.bans,
            "peaks": {ip: vars(p) for ip, p in self.peaks.items()},
        }

    @classmethod
    def from_json(cls, data: dict) -> State:
        """Build from ``to_json`` output; raises StateError on anything unexpected."""
        try:
            if data["version"] != STATE_VERSION:
                raise StateError(f"unsupported state version {data['version']!r}")
            cursor = data["cursor"]
            return cls(
                broker_start=None
                if data["broker_start"] is None
                else int(data["broker_start"]),
                cursor=None
                if cursor is None
                else Cursor(
                    int(cursor["inode"]), int(cursor["offset"]), str(cursor["head"])
                ),
                sessions={
                    str(cid): Session(str(s["ip"]), set(s["topics"]), bool(s["ha"]))
                    for cid, s in data["sessions"].items()
                },
                bans={str(ip): int(exp) for ip, exp in data["bans"].items()},
                peaks={
                    str(ip): Peak(
                        float(p["all"]),
                        float(p["non_ha"]),
                        {str(k): int(v) for k, v in p["families"].items()},
                    )
                    for ip, p in data["peaks"].items()
                },
            )
        except (KeyError, TypeError, ValueError, AttributeError) as err:
            raise StateError(f"malformed state: {err!r}") from err


def load_state(path: Path) -> State:
    """Read the state; missing file = empty state, broken file = StateError."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return State()
    except OSError as err:
        raise StateError(f"cannot read {path}: {err}") from err
    try:
        data = json.loads(text)
    except json.JSONDecodeError as err:
        raise StateError(f"{path} is not valid JSON: {err}") from err
    if not isinstance(data, dict):
        raise StateError(f"{path} does not hold a JSON object")
    return State.from_json(data)


def save_state(path: Path, state: State) -> None:
    """Write atomically, keeping the previous good file as ``.bak``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state.to_json(), f, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    if path.exists():
        bak_tmp = path.with_name(path.name + ".bak.tmp")
        shutil.copyfile(path, bak_tmp)
        bak_tmp.replace(path.with_name(path.name + ".bak"))
    tmp.replace(path)
    dir_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


@contextlib.contextmanager
def state_lock(path: Path, timeout: float = 10.0) -> Iterator[None]:
    """Hold an exclusive lock; raise LockBusyError after ``timeout`` seconds."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LockBusyError(f"{path} is held by another run") from None
                time.sleep(0.2)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
