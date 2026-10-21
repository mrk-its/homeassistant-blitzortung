"""Compact in-memory history of recent strikes for map cards."""

from array import array
from collections.abc import Iterator

# Micro-degree ints and millisecond times: 16 bytes per strike, against ~500
# for the parsed JSON dict. Live and buffered records share this quantization,
# so a card can deduplicate on [lat, lon, time].
_SCALE = 1_000_000
# The proxy repeats about a fifth of strikes, at most 6 messages later.
_DUPLICATE_LOOKBACK = 32

type StrikeRecord = list[float | int]


class StrikeBuffer:
    """Recent strikes in arrival order, bounded by age and count."""

    def __init__(self, max_age_ms: int | None, capacity: int) -> None:
        """Initialize."""
        self._max_age_ms = max_age_ms
        self._capacity = capacity
        self._coords = array("i")
        self._times = array("q")

    def __len__(self) -> int:
        """Return the number of buffered strikes."""
        return len(self._times)

    def append(self, lat: float, lon: float, time_ms: int) -> StrikeRecord | None:
        """Add a strike and return it as served, or None for a repeat."""
        lat_q = round(lat * _SCALE)
        lon_q = round(lon * _SCALE)
        coords = self._coords
        times = self._times
        for i in range(
            len(times) - 1, max(len(times) - _DUPLICATE_LOOKBACK, 0) - 1, -1
        ):
            if (
                times[i] == time_ms
                and coords[2 * i] == lat_q
                and coords[2 * i + 1] == lon_q
            ):
                return None
        coords.extend((lat_q, lon_q))
        times.append(time_ms)
        if (overflow := len(times) - self._capacity) > 0:
            # Drop an extra tenth so the array shift doesn't run on every strike.
            self._drop(overflow + self._capacity // 10)
        return [lat_q / _SCALE, lon_q / _SCALE, time_ms]

    def expire(self, now_ms: int) -> None:
        """Drop strikes older than the maximum age."""
        if self._max_age_ms is None:
            return
        cutoff = now_ms - self._max_age_ms
        times = self._times
        count = 0
        # Arrival order is only roughly time order, so stop at the first strike
        # still in the window rather than bisecting.
        while count < len(times) and times[count] < cutoff:
            count += 1
        if count:
            self._drop(count)

    def chunks(self, now_ms: int, size: int) -> Iterator[list[StrikeRecord]]:
        """Yield the strikes still in the window, oldest first, in chunks."""
        cutoff = None if self._max_age_ms is None else now_ms - self._max_age_ms
        coords = self._coords
        times = self._times
        chunk: list[StrikeRecord] = []
        for i, time_ms in enumerate(times):
            if cutoff is not None and time_ms < cutoff:
                continue
            chunk.append([coords[2 * i] / _SCALE, coords[2 * i + 1] / _SCALE, time_ms])
            if len(chunk) == size:
                yield chunk
                chunk = []
        if chunk:
            yield chunk

    def _drop(self, count: int) -> None:
        """Drop the oldest strikes."""
        del self._times[:count]
        del self._coords[: 2 * count]
