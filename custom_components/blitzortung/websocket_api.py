"""Websocket stream of lightning strikes for map cards."""

import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.components import websocket_api
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN, STREAM_FLUSH_INTERVAL, STREAM_SNAPSHOT_CHUNK

if TYPE_CHECKING:
    from collections.abc import Iterator

    from . import BlitzortungCoordinator
    from .strike_buffer import StrikeRecord

STRIKE_STREAM: HassKey["StrikeStream"] = HassKey(f"{DOMAIN}_strike_stream")


@callback
def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register the websocket commands."""
    websocket_api.async_register_command(hass, ws_subscribe_strikes)


@callback
def async_get_strike_stream(hass: HomeAssistant) -> "StrikeStream":
    """Return the strike stream, creating it on first use."""
    if (stream := hass.data.get(STRIKE_STREAM)) is None:
        stream = hass.data[STRIKE_STREAM] = StrikeStream(hass)
    return stream


@websocket_api.websocket_command(
    {
        probatio.Required("type"): "blitzortung/subscribe_strikes",
        probatio.Optional("entry_id"): str,
    }
)
@callback
def ws_subscribe_strikes(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Send buffered strikes, then new strikes once per second."""
    connection.send_result(msg["id"])
    connection.subscriptions[msg["id"]] = async_get_strike_stream(hass).async_subscribe(
        connection, msg["id"], msg.get("entry_id")
    )


@dataclass(slots=True)
class _Subscriber:
    """A websocket subscription and the time window it was last sent."""

    connection: websocket_api.ActiveConnection
    msg_id: int
    entry_id: str | None
    time_window: int | None = None


class StrikeStream:
    """Batch strikes from all config entries and send them to subscribers."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize."""
        self._hass = hass
        # Subscriptions live here, not on a coordinator, so they survive the
        # coordinator being replaced when an entry reloads.
        self._sources: dict[str, BlitzortungCoordinator] = {}
        self._subscribers: list[_Subscriber] = []
        self._pending: list[tuple[str, StrikeRecord]] = []
        self._unsub_flush: CALLBACK_TYPE | None = None

    @callback
    def async_add_source(
        self, entry_id: str, coordinator: "BlitzortungCoordinator"
    ) -> CALLBACK_TYPE:
        """Add a coordinator whose strikes are streamed; return a remover."""
        self._sources[entry_id] = coordinator
        # Tell subscribers about a changed time window after an options reload.
        self._schedule_flush()

        @callback
        def remove() -> None:
            if self._sources.get(entry_id) is coordinator:
                del self._sources[entry_id]

        return remove

    @callback
    def async_subscribe(
        self,
        connection: websocket_api.ActiveConnection,
        msg_id: int,
        entry_id: str | None,
    ) -> CALLBACK_TYPE:
        """Send the buffered strikes and stream new ones; return an unsubscriber."""
        subscriber = _Subscriber(
            connection, msg_id, entry_id, self._time_window(entry_id)
        )
        self._subscribers.append(subscriber)

        header: dict[str, Any] = {}
        if subscriber.time_window is not None:
            header["time_window"] = subscriber.time_window
        # Chunked so Python lists (~170 B a strike) exist for one chunk at a
        # time: a snapshot at the buffer cap peaks at 3.8 MB, 10.5 MB unchunked.
        first = True
        for chunk in self._snapshot_chunks(entry_id):
            self._send(
                subscriber,
                {**header, "strikes": chunk} if first else {"strikes": chunk},
            )
            first = False
        if first:
            self._send(subscriber, {**header, "strikes": []})

        @callback
        def unsubscribe() -> None:
            self._subscribers.remove(subscriber)
            if not self._subscribers:
                self._pending.clear()

        return unsubscribe

    @callback
    def publish(self, entry_id: str, record: "StrikeRecord") -> None:
        """Queue a strike for the next batch."""
        if not self._subscribers:
            return
        self._pending.append((entry_id, record))
        self._schedule_flush()

    @callback
    def _schedule_flush(self) -> None:
        if self._unsub_flush is None and self._subscribers:
            self._unsub_flush = async_call_later(
                self._hass, STREAM_FLUSH_INTERVAL, self._flush
            )

    @callback
    def _flush(self, _now: datetime) -> None:
        self._unsub_flush = None
        pending, self._pending = self._pending, []
        for subscriber in self._subscribers:
            event: dict[str, Any] = {}
            time_window = self._time_window(subscriber.entry_id)
            if time_window is not None and time_window != subscriber.time_window:
                event["time_window"] = subscriber.time_window = time_window
            if strikes := [
                record
                for entry_id, record in pending
                if subscriber.entry_id in (None, entry_id)
            ]:
                event["strikes"] = strikes
            if event:
                self._send(subscriber, event)

    def _snapshot_chunks(self, entry_id: str | None) -> "Iterator[list[StrikeRecord]]":
        now_ms = int(time.time() * 1000)
        for source_id, coordinator in self._sources.items():
            if entry_id in (None, source_id):
                yield from coordinator.strikes.chunks(now_ms, STREAM_SNAPSHOT_CHUNK)

    def _time_window(self, entry_id: str | None) -> int | None:
        """Return the longest time window, in seconds, of the matching entries."""
        return max(
            (
                coordinator.time_window_seconds
                for source_id, coordinator in self._sources.items()
                if entry_id in (None, source_id)
            ),
            default=None,
        )

    @staticmethod
    def _send(subscriber: _Subscriber, event: dict[str, Any]) -> None:
        subscriber.connection.send_message(
            websocket_api.event_message(subscriber.msg_id, event)
        )
