"""Tests for the packed strike buffer."""

import tracemalloc

from custom_components.blitzortung.strike_buffer import StrikeBuffer


def _flatten(buffer: StrikeBuffer, now_ms: int, size: int = 1000) -> list:
    return [record for chunk in buffer.chunks(now_ms, size) for record in chunk]


def test_append_returns_quantized_record() -> None:
    """Records are quantized to micro-degrees, the same as buffered strikes."""
    buffer = StrikeBuffer(max_age_ms=None, capacity=10)

    record = buffer.append(50.1234567, -10.7654321, 1_700_000_000_123)

    assert record == [50.123457, -10.765432, 1_700_000_000_123]
    assert len(buffer) == 1


def test_snapshot_matches_live_records() -> None:
    """A card can deduplicate a strike seen in both a snapshot and a live batch."""
    buffer = StrikeBuffer(max_age_ms=None, capacity=10)
    live = [
        buffer.append(lat, lon, 1_000 + i)
        for i, (lat, lon) in enumerate(
            [(27.9506, -82.4572), (-33.868820, 151.209295), (64.1265, -21.8174)]
        )
    ]

    assert _flatten(buffer, now_ms=2_000) == live


def test_repeated_strike_skipped() -> None:
    """A strike the proxy repeats a few messages later is stored once."""
    buffer = StrikeBuffer(max_age_ms=None, capacity=100)
    buffer.append(45.5, 12.25, 1_000)
    for i in range(5):
        buffer.append(40.0 + i, 10.0, 1_001 + i)

    assert buffer.append(45.5, 12.25, 1_000) is None
    assert len(buffer) == 6


def test_same_time_other_place_kept() -> None:
    """Two strikes in the same millisecond at different places are both kept."""
    buffer = StrikeBuffer(max_age_ms=None, capacity=10)
    buffer.append(45.5, 12.25, 1_000)

    assert buffer.append(45.5, 12.26, 1_000) == [45.5, 12.26, 1_000]
    assert len(buffer) == 2


def test_capacity_drops_oldest_tenth() -> None:
    """Going over capacity drops the overflow plus a tenth of the capacity."""
    buffer = StrikeBuffer(max_age_ms=None, capacity=10)
    for i in range(11):
        buffer.append(0.0, 0.0, i)

    assert len(buffer) == 9
    assert [record[2] for record in _flatten(buffer, now_ms=0)] == list(range(2, 11))


def test_expire_drops_strikes_older_than_max_age() -> None:
    """Expire removes the strikes before the first one still in the window."""
    buffer = StrikeBuffer(max_age_ms=1_000, capacity=10)
    for time_ms in (100, 500, 1_500, 1_200):
        buffer.append(1.0, 2.0, time_ms)

    buffer.expire(now_ms=2_000)

    assert [record[2] for record in _flatten(buffer, now_ms=2_000)] == [1_500, 1_200]


def test_expire_without_max_age_keeps_everything() -> None:
    """A zero time window keeps strikes until the capacity is reached."""
    buffer = StrikeBuffer(max_age_ms=None, capacity=10)
    buffer.append(1.0, 2.0, 0)

    buffer.expire(now_ms=10**12)

    assert len(buffer) == 1


def test_chunks_skip_expired_and_split() -> None:
    """Chunks leave out strikes past the window that expire() hasn't dropped yet."""
    buffer = StrikeBuffer(max_age_ms=1_000, capacity=10)
    for time_ms in (0, 1_500, 1_600, 1_700, 1_800, 1_900):
        buffer.append(1.0, 2.0, time_ms)

    chunks = list(buffer.chunks(now_ms=2_000, size=2))

    assert [[record[2] for record in chunk] for chunk in chunks] == [
        [1_500, 1_600],
        [1_700, 1_800],
        [1_900],
    ]


def test_chunks_of_empty_buffer() -> None:
    """An empty buffer yields no chunks."""
    assert list(StrikeBuffer(max_age_ms=1_000, capacity=10).chunks(0, 5)) == []


def test_memory_per_strike() -> None:
    """Each buffered strike costs about 16 bytes, not a dict's ~500."""
    strikes = 20_000
    tracemalloc.start()
    buffer = StrikeBuffer(max_age_ms=None, capacity=strikes)
    for i in range(strikes):
        buffer.append(40.0 + i / strikes, -100.0 - i / strikes, 1_700_000_000_000 + i)
    used, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert used / strikes < 20
