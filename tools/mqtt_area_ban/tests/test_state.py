"""Tests for session tracking, log following and state persistence."""

from __future__ import annotations

import gzip
import json
import threading
from pathlib import Path

import pytest
from conftest import BROKER_START, connect, globe_client, sub

from mqtt_area_ban.logfiles import LogFollower, NeedsReplayError
from mqtt_area_ban.logparse import End, Unsubscribe, parse_line
from mqtt_area_ban.state import (
    Cursor,
    LockBusyError,
    Session,
    State,
    StateError,
    load_state,
    save_state,
    state_lock,
)

T = BROKER_START + 10


def _feed(state: State, lines: str) -> None:
    for line in lines.splitlines(keepends=True):
        if event := parse_line(line):
            state.apply(event)


def test_session_lifecycle() -> None:
    """Connect, subscribe, unsubscribe and end."""
    state = State(broker_start=BROKER_START)
    _feed(
        state,
        connect(T, "c", "203.0.113.1")
        + sub(T, "c", "component/hello")
        + sub(T, "c", "a/#"),
    )
    assert state.sessions == {
        "c": Session("203.0.113.1", {"component/hello", "a/#"}, ha=True)
    }
    state.apply(Unsubscribe(T, "c", "a/#"))
    assert state.sessions["c"].topics == {"component/hello"}
    state.apply(End(T, "c"))
    assert state.sessions == {}


def test_reconnect_with_same_id_starts_clean() -> None:
    """A new connect replaces the old session, IP and topics."""
    state = State(broker_start=BROKER_START)
    _feed(
        state, globe_client(T, "c", "203.0.113.1") + connect(T + 1, "c", "203.0.113.2")
    )
    assert state.sessions["c"] == Session("203.0.113.2")


def test_events_before_broker_start_are_ignored() -> None:
    """Lines from the previous broker run don't create sessions."""
    state = State(broker_start=BROKER_START)
    _feed(state, globe_client(BROKER_START - 5, "old", "203.0.113.1"))
    assert state.sessions == {}


def test_subscribe_without_session_is_ignored() -> None:
    """A subscribe line for a client whose connect we never saw is dropped."""
    state = State(broker_start=BROKER_START)
    _feed(state, sub(T, "ghost", "blitzortung/1.1/#"))
    assert state.sessions == {}


def _write(path: Path, text: str, mode: str = "a") -> None:
    with path.open(mode, encoding="utf-8") as f:
        f.write(text)


def test_incremental_read_and_partial_line(tmp_path: Path) -> None:
    """Only complete lines are consumed; the rest is read next time."""
    log = tmp_path / "mosquitto.log"
    _write(log, "1: a 0 x\n2: b 0 y", "w")
    follower = LogFollower(log)
    assert list(follower.replay(0)) == ["1: a 0 x\n"]
    cursor = follower.cursor
    assert cursor is not None
    _write(log, "\n3: c 0 z\n")
    follower = LogFollower(log)
    assert list(follower.incremental(cursor)) == ["2: b 0 y\n", "3: c 0 z\n"]


def test_rotation_finishes_old_file(tmp_path: Path) -> None:
    """After one rotation the rest of .1 is read, then the new file from the start."""
    log = tmp_path / "mosquitto.log"
    _write(log, "1: a 0 x\n", "w")
    follower = LogFollower(log)
    list(follower.replay(0))
    cursor = follower.cursor
    assert cursor is not None
    _write(log, "2: b 0 y\n")
    log.rename(tmp_path / "mosquitto.log.1")
    _write(log, "3: c 0 z\n", "w")
    follower = LogFollower(log)
    assert list(follower.incremental(cursor)) == ["2: b 0 y\n", "3: c 0 z\n"]
    assert follower.cursor is not None
    assert follower.cursor.offset == len("3: c 0 z\n")


def test_two_rotations_read_gzip(tmp_path: Path) -> None:
    """With two rotations the cursor's file is .2.gz and is recognised by its head."""
    log = tmp_path / "mosquitto.log"
    _write(log, "1: a 0 x\n", "w")
    follower = LogFollower(log)
    list(follower.replay(0))
    cursor = follower.cursor
    assert cursor is not None
    with gzip.open(tmp_path / "mosquitto.log.2.gz", "wt") as f:
        f.write("1: a 0 x\n2: b 0 y\n")
    log.unlink()
    _write(tmp_path / "mosquitto.log.1", "3: c 0 z\n", "w")
    _write(log, "4: d 0 w\n", "w")
    follower = LogFollower(log)
    assert list(follower.incremental(cursor)) == [
        "2: b 0 y\n",
        "3: c 0 z\n",
        "4: d 0 w\n",
    ]


def test_reused_inode_is_not_mistaken_for_the_old_file(tmp_path: Path) -> None:
    """A new log reusing the cursor's inode is handled as a rotation."""
    log = tmp_path / "mosquitto.log"
    _write(log, "5: new 0 x\n6: new 0 y\n", "w")
    with gzip.open(tmp_path / "mosquitto.log.2.gz", "wt") as f:
        f.write("1: a 0 x\n2: b 0 y\n")
    _write(tmp_path / "mosquitto.log.1", "3: c 0 z\n", "w")
    cursor = Cursor(log.stat().st_ino, len("1: a 0 x\n"), "1: a 0 x\n")
    assert list(LogFollower(log).incremental(cursor)) == [
        "2: b 0 y\n", "3: c 0 z\n", "5: new 0 x\n", "6: new 0 y\n",
    ]  # fmt: skip


def test_lost_cursor_needs_replay(tmp_path: Path) -> None:
    """If the cursor's file is gone, the caller must rebuild."""
    log = tmp_path / "mosquitto.log"
    _write(log, "1: a 0 x\n", "w")
    follower = LogFollower(log)
    list(follower.replay(0))
    cursor = follower.cursor
    assert cursor is not None
    log.unlink()
    _write(log, "9: z 0 q\n", "w")
    with pytest.raises(NeedsReplayError):
        list(LogFollower(log).incremental(cursor))


def test_truncated_log_is_reread(tmp_path: Path) -> None:
    """A file shorter than the offset is read from the start."""
    log = tmp_path / "mosquitto.log"
    _write(log, "1: a 0 x\n2: b 0 y\n", "w")
    follower = LogFollower(log)
    list(follower.replay(0))
    cursor = follower.cursor
    assert cursor is not None
    _write(log, "3: c 0 z\n", "w")  # same inode, shorter
    assert list(LogFollower(log).incremental(cursor)) == ["3: c 0 z\n"]


def test_replay_reads_rotated_files_oldest_first(tmp_path: Path) -> None:
    """Replay goes .N.gz ... .1, then the live file."""
    log = tmp_path / "mosquitto.log"
    with gzip.open(tmp_path / "mosquitto.log.3.gz", "wt") as f:
        f.write("1: a 0 x\n")
    with gzip.open(tmp_path / "mosquitto.log.2.gz", "wt") as f:
        f.write("2: b 0 y\n")
    _write(tmp_path / "mosquitto.log.1", "3: c 0 z\n", "w")
    _write(log, "4: d 0 w\n", "w")
    assert list(LogFollower(log).replay(0)) == [
        "1: a 0 x\n",
        "2: b 0 y\n",
        "3: c 0 z\n",
        "4: d 0 w\n",
    ]


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    """State survives a save/load cycle, and the previous file becomes .bak."""
    path = tmp_path / "state.json"
    state = State(
        broker_start=5,
        sessions={"c": Session("203.0.113.1", {"t"}, ha=True)},
        bans={"203.0.113.9": 99},
    )
    save_state(path, state)
    assert load_state(path) == state
    state.bans["203.0.113.10"] = 100
    save_state(path, state)
    assert load_state(path) == state
    assert json.loads((tmp_path / "state.json.bak").read_text())["bans"] == {
        "203.0.113.9": 99
    }
    assert not (tmp_path / "state.json.tmp").exists()


def test_failed_write_keeps_old_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash before the replace leaves the previous state intact."""
    path = tmp_path / "state.json"
    save_state(path, State(bans={"203.0.113.9": 99}))

    def boom(*_args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("mqtt_area_ban.state.os.fsync", boom)
    with pytest.raises(OSError, match="disk full"):
        save_state(path, State(bans={}))
    assert load_state(path).bans == {"203.0.113.9": 99}


def test_missing_state_is_empty(tmp_path: Path) -> None:
    """No file yet means a fresh state."""
    assert load_state(tmp_path / "nope.json") == State()


@pytest.mark.parametrize(
    "content",
    ["{not json", "[]", '{"version": 99}', '{"version": 1, "broker_start": null}', ""],
)
def test_corrupt_state_raises(tmp_path: Path, content: str) -> None:
    """Anything unusable is reported, never silently replaced."""
    path = tmp_path / "state.json"
    path.write_text(content)
    with pytest.raises(StateError):
        load_state(path)


def test_lock_refuses_second_instance(tmp_path: Path) -> None:
    """While one run holds the lock, another gives up after its timeout."""
    lock = tmp_path / "lock"
    held = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with state_lock(lock):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=holder)
    thread.start()
    held.wait(5)
    try:
        with pytest.raises(LockBusyError), state_lock(lock, timeout=0.3):
            pass
    finally:
        release.set()
        thread.join()
    with state_lock(lock, timeout=0.3):
        pass


def test_peak_recorded_when_session_ends() -> None:
    """A client that disconnects before the run still leaves its area behind."""
    state = State(broker_start=BROKER_START)
    _feed(
        state,
        globe_client(T, "shtff7daa9d1", "203.0.113.1")
        + globe_client(T, "shtfe49d9f10", "203.0.113.1")
        + f"{T + 60}: Client shtff7daa9d1 closed its connection.\n"
        + f"{T + 61}: Client shtfe49d9f10 has exceeded timeout, disconnecting.\n",
    )
    assert state.sessions == {}
    assert state.peaks["203.0.113.1"].all == pytest.approx(2.0)
    assert state.peaks["203.0.113.1"].families == {"sht": 2}


def test_peak_keeps_ha_split() -> None:
    """The non-HA peak ignores HA clients behind the same IP."""
    state = State(broker_start=BROKER_START)
    _feed(
        state,
        globe_client(T, "bot", "203.0.113.1")
        + connect(T, "ha", "203.0.113.1")
        + sub(T, "ha", "component/hello")
        + sub(T, "ha", "blitzortung/1.1/#")
        + f"{T + 5}: Client bot disconnected.\n",
    )
    peak = state.peaks["203.0.113.1"]
    assert (peak.all, peak.non_ha) == (pytest.approx(2.0), pytest.approx(1.0))


def test_takeover_and_broker_restart_record_peaks() -> None:
    """A reconnect with the same ID and a broker restart both end sessions."""
    state = State(broker_start=BROKER_START)
    _feed(
        state, globe_client(T, "c", "203.0.113.1") + connect(T + 1, "c", "203.0.113.2")
    )
    assert state.peaks["203.0.113.1"].all == pytest.approx(1.0)
    _feed(state, sub(T + 2, "c", "blitzortung/1.1/u/#"))
    state.reset_sessions(T + 100)
    assert state.peaks["203.0.113.2"].all == pytest.approx(1 / 32)


def test_peaks_survive_save_and_load(tmp_path: Path) -> None:
    """Peaks are part of the persisted state."""
    state = State(broker_start=BROKER_START)
    _feed(state, globe_client(T, "c", "203.0.113.1") + f"{T}: Client c disconnected.\n")
    save_state(tmp_path / "s.json", state)
    assert load_state(tmp_path / "s.json").peaks == state.peaks
