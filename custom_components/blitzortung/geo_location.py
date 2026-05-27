"""Support for Blitzortung geo location events."""

import asyncio
import bisect
import logging
import time
import uuid
from datetime import timedelta
from typing import Any

from homeassistant.components.geo_location import DOMAIN as GEO_LOCATION_PLATFORM
from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.components.recorder import get_instance as recorder_get_instance
from homeassistant.components.recorder.db_schema import StatesMeta
from homeassistant.components.recorder.history import get_significant_states
from homeassistant.components.recorder.util import session_scope
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE, UnitOfLength
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util
from homeassistant.util.dt import utc_from_timestamp
from homeassistant.util.unit_system import IMPERIAL_SYSTEM
from sqlalchemy import text

from . import BlitzortungConfigEntry
from .const import ATTR_EXTERNAL_ID, ATTR_PUBLICATION_DATE, ATTRIBUTION, DOMAIN

_LOGGER = logging.getLogger(__name__)

SIGNAL_DELETE_ENTITY = "blitzortung_delete_entity_{0}"

STRIKE_ENTITY_ID_PREFIX = f"{GEO_LOCATION_PLATFORM}.lightning_strike_"
RECORDER_DOMAIN = "recorder"
RECONCILE_INTERVAL = timedelta(days=1)

# When the DB has more orphan rows than this threshold, the rebuild path
# becomes prohibitive (the categorise loop is O(N) on the main thread, and
# a >2M-entity WHERE IN query into the recorder can hang its executor for
# minutes). For such DBs we drain via chunked recorder.purge_entities
# service calls instead of fetching state for rebuild.
RECONCILE_REBUILD_THRESHOLD = 10000

# Service-based cleanup tuning. Each chunk is a small explicit entity_id
# list passed to recorder.purge_entities — the recorder handles FK chains,
# transactions, and schema portability correctly. Sleeping between chunks
# lets the recorder's executor drain its queue and keeps the event loop
# responsive.
#
# PURGE_CHUNK_SIZE is bounded by the recorder's MAX_EVENT_DATA_BYTES
# (32 KB at HA 2026.5). The call_service event carries our entity_id
# list as JSON; at ~67 bytes/entity_id, 350 lands around 24 KB with
# comfortable margin. Going over the limit doesn't break the call
# (the in-memory event still reaches the handler), but the recorder
# logs a noisy warning per call and refuses to persist the event row.
PURGE_CHUNK_SIZE = 350
PURGE_CHUNK_DELAY = 1.0

# Portable LIKE-with-ESCAPE pattern. '!' avoids the backslash-doubling
# pain that MySQL and SQLite handle differently.
_STRIKE_LIKE_PATTERN = "geo!_location.lightning!_strike!_%"
_ESCAPE_CHAR = "!"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BlitzortungConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Blitzortung geo location platform from a config entry."""
    coordinator = config_entry.runtime_data
    if not coordinator.max_tracked_lightnings:
        return

    # This block of code can be removed in some time. For now it has to stay to clean up
    # user registry after https://github.com/mrk-its/homeassistant-blitzortung/pull/128
    entity_reg = er.async_get(hass)
    if entities := er.async_entries_for_config_entry(entity_reg, config_entry.entry_id):
        for entity in entities:
            if not entity.entity_id.startswith(GEO_LOCATION_PLATFORM):
                continue
            entity_reg.async_remove(entity.entity_id)

    manager = BlitzortungEventManager(
        hass,
        async_add_entities,
        coordinator.max_tracked_lightnings,
        coordinator.time_window_seconds,
    )

    # Reconcile DB state with the empty in-memory cache: strikes still within
    # the time window come back to life on the map; strikes past their window
    # (orphaned by a previous HA reboot mid-storm) get precisely purged.
    #
    # Run as a background task — on a production DB with tens of thousands of
    # orphan rows, the bulk state-history fetch can easily take longer than
    # HA's 60-second platform-setup deadline. Live strikes arriving from MQTT
    # during the reconcile are safe: each one goes through Strikes.insort,
    # which handles concurrent insertion correctly. The reconcile then skips
    # whatever the live cache already contains.
    config_entry.async_create_background_task(
        hass,
        _async_reconcile_strikes(hass, config_entry, manager),
        name="blitzortung_reconcile_strikes_initial",
    )

    # Daily backstop. Defensive against rare orphan accumulation during a
    # long-running HA process. Unregistered automatically on unload.
    async def _periodic_reconcile(_now: Any) -> None:
        await _async_reconcile_strikes(hass, config_entry, manager)

    config_entry.async_on_unload(
        async_track_time_interval(hass, _periodic_reconcile, RECONCILE_INTERVAL)
    )

    coordinator.register_lightning_receiver(manager.lightning_cb)
    coordinator.register_on_tick(manager.tick)


async def _async_reconcile_strikes(
    hass: HomeAssistant,
    config_entry: BlitzortungConfigEntry,
    manager: "BlitzortungEventManager",
) -> None:
    """Reconcile recorder-persisted strikes with the in-memory cache.

    The integration's strike entities are short-lived (max 24 h) but the
    recorder DB outlives them: rows for a strike active when HA stopped
    sit in the DB until normal retention purges them (often 6 months on
    user configs). With a national-scale cache (5000+ strikes), that's
    hundreds of thousands of orphan rows across reboots.

    Strategy:

    1. Enumerate every ``lightning_strike_*`` entity_id in the DB.
    2. Bulk-fetch their last state within the configured time window.
    3. For entities with state inside the window: reconstruct them as live
       events, insert into the in-memory cache up to capacity (newest first),
       register with HA. Normal ``tick()`` evicts them as time runs out,
       producing proper removal records — no special-case purge needed.
    4. For entities outside the window (orphans), and any rebuild overflow,
       call recorder.purge_entities with the precise entity_id list.

    Skipped entirely when a sibling Blitzortung config entry is already
    loaded: strike entity_ids carry only a UUID, so we can't tell our
    orphans from a sibling's live strikes.
    """
    others_loaded = any(
        entry.entry_id != config_entry.entry_id
        and entry.state == ConfigEntryState.LOADED
        for entry in hass.config_entries.async_entries(DOMAIN)
    )
    if others_loaded:
        _LOGGER.debug(
            "Skipping strike reconcile: another Blitzortung entry is loaded"
        )
        return

    if RECORDER_DOMAIN not in hass.config.components:
        return

    instance = recorder_get_instance(hass)
    if instance is None:
        return

    db_entity_ids = await _async_enumerate_strike_entity_ids(instance)
    if not db_entity_ids:
        return

    window_minutes = manager._window_seconds // 60  # noqa: SLF001
    _LOGGER.info(
        "Strike reconcile: found %d lightning_strike_* entries in recorder DB"
        " (time window: %d min)",
        len(db_entity_ids),
        window_minutes,
    )

    if len(db_entity_ids) > RECONCILE_REBUILD_THRESHOLD:
        # Skip rebuild and drain via chunked recorder.purge_entities calls.
        # The rebuild path's categorise loop is O(N) on the main thread,
        # and a single glob purge at multi-million scale has been observed
        # to hang or drop the SQL connection. Chunked service calls keep
        # each recorder task small and let the main loop stay responsive.
        # The cleanup function re-enumerates states_meta via cursor paging,
        # so the count above (db_entity_ids) is only used for the log line.
        await _async_batched_service_purge(hass, instance, manager, len(db_entity_ids))
        return

    start_time = dt_util.utcnow() - timedelta(seconds=manager._window_seconds)  # noqa: SLF001
    states_dict = await _async_fetch_strike_states(
        hass, instance, db_entity_ids, start_time
    )

    rebuild_candidates, purge_ids = _categorise_strikes(
        db_entity_ids, states_dict, manager, start_time.timestamp()
    )

    # Snapshot counts at the categorisation boundary so we can break them out
    # in the final log line. After this point, _cap_rebuild_to_capacity may
    # move overflow from rebuild → purge, which would otherwise hide the
    # "how many were actually outside the window" signal.
    live_skipped = (
        len(db_entity_ids) - len(rebuild_candidates) - len(purge_ids)
    )
    outside_window = len(purge_ids)
    within_window = len(rebuild_candidates)

    rebuild_candidates, purge_ids = _cap_rebuild_to_capacity(
        rebuild_candidates, purge_ids, manager
    )
    overflow = within_window - len(rebuild_candidates)

    to_register: list[BlitzortungEvent] = []
    for event in rebuild_candidates:
        # insort returns None only if at-capacity-and-older-than-oldest,
        # which can't happen here (we just cleared against capacity), but
        # handle defensively.
        if manager._strikes.insort(event) is None:  # noqa: SLF001
            purge_ids.append(event.entity_id)
            continue
        to_register.append(event)

    if to_register:
        manager._async_add_entities(to_register)  # noqa: SLF001

    if purge_ids:
        await _async_purge_entity_ids(hass, purge_ids)

    _LOGGER.info(
        "Strike reconcile complete: rebuilt %d (within window), "
        "purged %d (outside window: %d, overflow past capacity: %d), "
        "skipped %d already-live",
        len(to_register),
        len(purge_ids),
        outside_window,
        overflow,
        live_skipped,
    )


async def _async_enumerate_strike_entity_ids(instance: Any) -> list[str]:
    """Return all lightning_strike_* entity_ids known to the recorder.

    Uses the same StatesMeta query the recorder runs internally for
    purge_entities — there is no public glob-enumeration API.
    """

    def _query() -> list[str]:
        with session_scope(session=instance.get_session(), read_only=True) as session:
            return [
                eid
                for (eid,) in session.query(StatesMeta.entity_id)
                .filter(StatesMeta.entity_id.like(f"{STRIKE_ENTITY_ID_PREFIX}%"))
                .all()
            ]

    try:
        return await instance.async_add_executor_job(_query)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Failed to enumerate strike entity_ids", exc_info=True)
        return []


async def _async_fetch_strike_states(
    hass: HomeAssistant,
    instance: Any,
    entity_ids: list[str],
    start_time: Any,
) -> dict[str, list[State]]:
    """Bulk-fetch the last state inside the time window for each entity_id."""
    try:
        return await instance.async_add_executor_job(
            get_significant_states,
            hass,
            start_time,
            None,  # end_time
            entity_ids,
            None,  # filters
            False,  # include_start_time_state — only changes within window
        )
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Failed to fetch strike state history", exc_info=True)
        return {}


def _categorise_strikes(
    db_entity_ids: list[str],
    states_dict: dict[str, list[State]],
    manager: "BlitzortungEventManager",
    start_ts: float,
) -> tuple[list["BlitzortungEvent"], list[str]]:
    """Split DB entity_ids into rebuild candidates and purge-bound orphans."""
    live_entity_ids = {ev.entity_id for ev in manager._strikes}  # noqa: SLF001
    rebuild_candidates: list[BlitzortungEvent] = []
    purge_ids: list[str] = []

    for entity_id in db_entity_ids:
        if entity_id in live_entity_ids:
            continue
        states = states_dict.get(entity_id, [])
        if not states:
            purge_ids.append(entity_id)
            continue
        event = BlitzortungEvent.from_recorder_state(states[-1], manager._unit)  # noqa: SLF001
        if event is None or event._publication_date < start_ts:  # noqa: SLF001
            purge_ids.append(entity_id)
            continue
        rebuild_candidates.append(event)

    return rebuild_candidates, purge_ids


def _cap_rebuild_to_capacity(
    rebuild_candidates: list["BlitzortungEvent"],
    purge_ids: list[str],
    manager: "BlitzortungEventManager",
) -> tuple[list["BlitzortungEvent"], list[str]]:
    """Trim rebuild list to remaining cache capacity; overflow joins purge."""
    remaining = manager._strikes._capacity - len(manager._strikes)  # noqa: SLF001
    if remaining <= 0:
        purge_ids.extend(e.entity_id for e in rebuild_candidates)
        return [], purge_ids
    if len(rebuild_candidates) > remaining:
        rebuild_candidates.sort(key=lambda e: e._publication_date, reverse=True)  # noqa: SLF001
        purge_ids.extend(e.entity_id for e in rebuild_candidates[remaining:])
        rebuild_candidates = rebuild_candidates[:remaining]
    return rebuild_candidates, purge_ids


async def _async_purge_entity_ids(hass: HomeAssistant, entity_ids: list[str]) -> None:
    """Call recorder.purge_entities with an explicit entity_id list."""
    try:
        await hass.services.async_call(
            RECORDER_DOMAIN,
            "purge_entities",
            {"entity_id": entity_ids},
            blocking=False,
        )
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Recorder purge_entities failed", exc_info=True)


async def _async_batched_service_purge(
    hass: HomeAssistant,
    instance: Any,
    manager: "BlitzortungEventManager",
    initial_found_count: int,
) -> None:
    """Drain orphan strike rows via chunked recorder.purge_entities calls.

    Used when the DB has too many entries for the rebuild path. A single
    glob purge on a multi-million-entity DB has been observed to:
      * hang the recorder executor for very long stretches, since the
        recorder's purge_entity_data enumerates the full states_meta
        table in Python on every iteration; and
      * raise operational errors (dropped SQL connection) on some
        backends at this scale.

    The fix is the same official service — recorder.purge_entities,
    which handles FK chains, transactions, and schema portability
    correctly — but called repeatedly with small explicit entity_id
    chunks. Each chunk is a short, bounded task in the recorder's
    executor; the asyncio.sleep between chunks yields the event loop
    and lets the recorder drain its queue.

    Each iteration re-enumerates the next slice of states_meta via
    cursor paging (metadata_id > last_seen). This adapts to concurrent
    external cleanup (a user running the SQL script alongside us) and
    terminates naturally when the table is empty — no stale snapshot
    to grind through.

    keep_days is derived from the integration's own time_window — no
    extra margin. For sub-day windows, keep_days = 0, which purges
    everything for the matched entity_ids regardless of age; the
    rebuild path (under threshold) is where map continuity for live
    strikes is preserved.
    """
    window_seconds = manager._window_seconds  # noqa: SLF001
    keep_days = window_seconds // 86400

    _LOGGER.warning(
        "Strike reconcile: %d entries exceeds the rebuild threshold of %d. "
        "Draining via chunked recorder.purge_entities (chunk=%d, "
        "delay=%.1fs, keep_days=%d). The map will not show pre-restart "
        "strikes during this boot.",
        initial_found_count,
        RECONCILE_REBUILD_THRESHOLD,
        PURGE_CHUNK_SIZE,
        PURGE_CHUNK_DELAY,
        keep_days,
    )

    started = time.monotonic()
    cursor = 0
    total_queued = 0
    failed_chunks = 0
    chunk_idx = 0

    while True:
        chunk_data = await _async_enumerate_strike_chunk(
            instance, cursor, PURGE_CHUNK_SIZE
        )
        if not chunk_data:
            break

        entity_ids = [eid for (_mid, eid) in chunk_data]
        cursor = max(mid for (mid, _eid) in chunk_data)

        try:
            await hass.services.async_call(
                RECORDER_DOMAIN,
                "purge_entities",
                {"entity_id": entity_ids, "keep_days": keep_days},
                blocking=False,
            )
        except Exception:  # noqa: BLE001
            failed_chunks += 1
            _LOGGER.debug(
                "Strike cleanup: chunk %d failed; continuing", chunk_idx,
                exc_info=True,
            )

        total_queued += len(entity_ids)
        chunk_idx += 1
        if chunk_idx % 100 == 0:
            elapsed = time.monotonic() - started
            _LOGGER.info(
                "Strike cleanup: queued %d entries across %d chunks "
                "(%.0fs elapsed, cursor=%d)",
                total_queued, chunk_idx, elapsed, cursor,
            )

        await asyncio.sleep(PURGE_CHUNK_DELAY)

    elapsed = time.monotonic() - started
    if failed_chunks:
        _LOGGER.warning(
            "Strike cleanup: queued %d entries in %.0fs (%d chunks failed; "
            "those entries will be retried by the next daily reconcile)",
            total_queued, elapsed, failed_chunks,
        )
    else:
        _LOGGER.info(
            "Strike cleanup: drained all entries in %.0fs (%d queued)",
            elapsed, total_queued,
        )


async def _async_enumerate_strike_chunk(
    instance: Any, after_metadata_id: int, limit: int
) -> list[tuple[int, str]]:
    """Return up to `limit` (metadata_id, entity_id) pairs above a cursor.

    Cursor paging by metadata_id ensures forward progress: even if a
    queued purge task hasn't actually deleted the row from states_meta
    yet, we won't revisit it on the next iteration. The states_meta
    table has an index on entity_id (ix_states_meta_entity_id) and
    primary key on metadata_id, so the LIKE prefix + ORDER BY filter
    is fast even on millions of rows.
    """
    def _query() -> list[tuple[int, str]]:
        with session_scope(session=instance.get_session(), read_only=True) as session:
            rows = session.execute(
                text(
                    # _ESCAPE_CHAR is a literal module constant, not user input.
                    "SELECT metadata_id, entity_id FROM states_meta "  # noqa: S608
                    f"WHERE entity_id LIKE :pat ESCAPE '{_ESCAPE_CHAR}' "
                    "AND metadata_id > :after "
                    "ORDER BY metadata_id "
                    "LIMIT :limit"
                ),
                {
                    "pat": _STRIKE_LIKE_PATTERN,
                    "after": after_metadata_id,
                    "limit": limit,
                },
            )
            return [(row[0], row[1]) for row in rows]

    try:
        return await instance.async_add_executor_job(_query)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Strike cleanup: cursor enumerate failed", exc_info=True)
        return []


class BlitzortungEvent(GeolocationEvent):
    """Define a lightning strike event."""

    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:flash"
    _attr_name = "Lightning Strike"
    _attr_should_poll = False
    _attr_source = DOMAIN

    def __init__(
        self,
        distance: float,
        latitude: float,
        longitude: float,
        unit: str,
        time: int,
        status: int,
        region: int,
        strike_id: str | None = None,
    ) -> None:
        """Initialize entity with data provided.

        ``strike_id`` is normally generated fresh per strike; the optional
        argument exists so the reconcile path can reconstruct an event with
        the original entity_id after an HA restart, preserving recorder
        history continuity.
        """
        self._time = time
        self._status = status
        self._region = region
        self._publication_date = time / 1e9
        self._remove_signal_delete = None
        self._strike_id = strike_id or str(uuid.uuid4()).replace("-", "")
        self.entity_id = f"{STRIKE_ENTITY_ID_PREFIX}{self._strike_id}"
        self._attr_distance = distance
        self._attr_latitude = latitude
        self._attr_longitude = longitude
        self._attr_extra_state_attributes = {
            ATTR_EXTERNAL_ID: self._strike_id,
            ATTR_PUBLICATION_DATE: utc_from_timestamp(self._publication_date),
        }
        self._attr_unit_of_measurement = unit

    @classmethod
    def from_recorder_state(cls, state: State, unit: str) -> "BlitzortungEvent | None":
        """Reconstruct a strike from a recorder-persisted state row.

        Returns None if the row's shape is unexpected (corrupt attributes,
        missing fields). Defensive — recorder schema changes or partial
        writes shouldn't break setup.
        """
        try:
            strike_id = state.attributes[ATTR_EXTERNAL_ID]
            pub_date_raw = state.attributes[ATTR_PUBLICATION_DATE]
            if isinstance(pub_date_raw, str):
                pub_date = dt_util.parse_datetime(pub_date_raw)
            else:
                pub_date = pub_date_raw
            if pub_date is None:
                return None
            distance = float(state.state)
            latitude = float(state.attributes[ATTR_LATITUDE])
            longitude = float(state.attributes[ATTR_LONGITUDE])
        except (KeyError, ValueError, TypeError):
            return None
        # status/region aren't preserved in state attributes; default to 0.
        return cls(
            distance=distance,
            latitude=latitude,
            longitude=longitude,
            unit=unit,
            time=int(pub_date.timestamp() * 1e9),
            status=0,
            region=0,
            strike_id=strike_id,
        )

    @callback
    def _delete_callback(self) -> None:
        """Remove this entity."""
        self._remove_signal_delete()
        self.hass.async_create_task(self.async_remove(force_remove=True))

    async def async_added_to_hass(self) -> None:
        """Call when entity is added to hass."""
        self._remove_signal_delete = async_dispatcher_connect(
            self.hass,
            SIGNAL_DELETE_ENTITY.format(self._strike_id),
            self._delete_callback,
        )


class Strikes(list):
    """Define a list of lightning strikes, keeping it sorted by publication date."""

    def __init__(self, capacity: int) -> None:
        """Initialize."""
        self._keys = []
        self._key_fn = lambda strike: strike._publication_date  # noqa: SLF001
        self._max_key = 0
        self._capacity = capacity
        super().__init__()

    def insort(self, item: BlitzortungEvent) -> tuple[BlitzortungEvent, ...] | None:
        """Insert item into the list, keeping it sorted by key.

        Returns the tuple of evicted items (possibly empty), or None if the item
        was rejected because it's older than every retained strike and the cache
        is already at capacity. Rejection avoids a race in which the caller
        registers the new entity with HA and then immediately fires the
        eviction signal — before the entity's delete-listener has been
        attached in async_added_to_hass — leaving a ghost entity that never
        gets removed.
        """
        k = self._key_fn(item)
        if (
            len(self) >= self._capacity
            and self._keys
            and k <= self._keys[0]
        ):
            return None
        if k > self._max_key:
            self._max_key = k
            self._keys.append(k)
            self.append(item)
        else:
            i = bisect.bisect_right(self._keys, k)
            self._keys.insert(i, k)
            self.insert(i, item)
        n = len(self) - self._capacity
        if n > 0:
            del self._keys[0:n]
            to_delete = self[0:n]
            self[0:n] = []
            return tuple(to_delete)
        return ()

    def cleanup(self, k: float) -> tuple[BlitzortungEvent]:
        """Remove all strikes older than k."""
        if not self._keys or self._keys[0] > k:
            return ()

        i = bisect.bisect_right(self._keys, k)
        if not i:
            return ()

        del self._keys[0:i]
        to_delete = self[0:i]
        self[0:i] = []
        return to_delete


class BlitzortungEventManager:
    """Define a class to handle Blitzortung events."""

    def __init__(
        self,
        hass: HomeAssistant,
        async_add_entities: AddConfigEntryEntitiesCallback,
        max_tracked_lightnings: int,
        window_seconds: int,
    ) -> None:
        """Initialize."""
        self._async_add_entities = async_add_entities
        self._hass = hass
        self._strikes = Strikes(max_tracked_lightnings)
        self._window_seconds = window_seconds

        if hass.config.units == IMPERIAL_SYSTEM:
            self._unit = UnitOfLength.MILES
        else:
            self._unit = UnitOfLength.KILOMETERS

    async def lightning_cb(self, lightning: dict[str, Any]) -> None:
        """Handle incoming lightning strike data."""
        _LOGGER.debug("geo_location lightning: %s", lightning)
        event = BlitzortungEvent(
            lightning["distance"],
            lightning["lat"],
            lightning["lon"],
            self._unit,
            lightning["time"],
            lightning["status"],
            lightning["region"],
        )
        to_delete = self._strikes.insort(event)
        if to_delete is None:
            _LOGGER.debug(
                "Dropping late strike at %s (older than oldest tracked)",
                event._publication_date,  # noqa: SLF001
            )
            return
        self._async_add_entities([event])
        if to_delete:
            self._remove_events(to_delete)
        _LOGGER.debug("tracked lightnings: %s", len(self._strikes))

    @callback
    def _remove_events(self, events: tuple[BlitzortungEvent]) -> None:
        """Remove old geo location events."""
        _LOGGER.debug("Going to remove %s", events)
        for event in events:
            async_dispatcher_send(
                self._hass,
                SIGNAL_DELETE_ENTITY.format(event._strike_id),  # noqa: SLF001
            )

    def tick(self) -> None:
        """Handle tick."""
        to_delete = self._strikes.cleanup(time.time() - self._window_seconds)
        if to_delete:
            self._remove_events(to_delete)
