"""Tests for the Strikes cache, recorder reconcile, and BlitzortungEvent."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_NAME,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.blitzortung.const import (
    ATTR_EXTERNAL_ID,
    ATTR_PUBLICATION_DATE,
    CONF_CONFIG_TYPE,
    CONF_MAX_TRACKED_LIGHTNINGS,
    CONF_RADIUS,
    CONF_TIME_WINDOW,
    CONFIG_TYPE_COORDINATES,
    DOMAIN,
)
from custom_components.blitzortung.geo_location import (
    PURGE_CHUNK_SIZE,
    RECONCILE_INTERVAL,
    RECONCILE_REBUILD_THRESHOLD,
    STRIKE_ENTITY_ID_PREFIX,
    BlitzortungEvent,
    BlitzortungEventManager,
    Strikes,
    _async_batched_service_purge,
    _async_reconcile_strikes,
    _cap_rebuild_to_capacity,
    _categorise_strikes,
)


@dataclass
class StrikeStub:
    """Minimal duck-typed strike: only the _publication_date attr is read."""

    _publication_date: float


def _strike(t: float) -> StrikeStub:
    return StrikeStub(_publication_date=t)


# ---------------------------------------------------------------------------
# Strikes capacity- and time-bounded cache
# ---------------------------------------------------------------------------


def test_insort_below_capacity_returns_empty() -> None:
    """Adding strikes below capacity evicts nothing."""
    s = Strikes(capacity=3)
    assert s.insort(_strike(1.0)) == ()
    assert s.insort(_strike(2.0)) == ()
    assert len(s) == 2


def test_insort_at_capacity_with_newer_evicts_oldest() -> None:
    """Once full, a strictly-newer strike evicts the oldest one."""
    s = Strikes(capacity=2)
    s.insort(_strike(1.0))
    s.insort(_strike(2.0))
    evicted = s.insort(_strike(3.0))
    assert tuple(e._publication_date for e in evicted) == (1.0,)
    assert [e._publication_date for e in s] == [2.0, 3.0]


def test_insort_at_capacity_with_too_old_strike_is_rejected() -> None:
    """A strike older than every retained one must not be inserted-then-evicted.

    This is the ghost-entity fix: if we accepted then evicted, the caller
    would register the entity with HA and immediately fire its delete signal
    before the entity's listener was attached — leaking the entity forever.
    """
    s = Strikes(capacity=2)
    s.insort(_strike(10.0))
    s.insort(_strike(20.0))
    result = s.insort(_strike(5.0))  # older than oldest (10.0)
    assert result is None
    # Cache unchanged.
    assert [e._publication_date for e in s] == [10.0, 20.0]


def test_insort_at_capacity_equal_to_oldest_is_rejected() -> None:
    """Tie with the oldest still gets rejected — no room and not strictly newer."""
    s = Strikes(capacity=2)
    s.insort(_strike(10.0))
    s.insort(_strike(20.0))
    assert s.insort(_strike(10.0)) is None
    assert [e._publication_date for e in s] == [10.0, 20.0]


def test_insort_at_capacity_with_in_between_key_still_inserts() -> None:
    """A late strike newer than the oldest still fits — evict oldest, insert."""
    s = Strikes(capacity=2)
    s.insort(_strike(10.0))
    s.insort(_strike(30.0))
    evicted = s.insort(_strike(20.0))  # newer than 10, older than 30
    assert tuple(e._publication_date for e in evicted) == (10.0,)
    assert [e._publication_date for e in s] == [20.0, 30.0]


def test_insort_below_capacity_with_out_of_order_key_inserts() -> None:
    """When there's room, even an out-of-order key is accepted."""
    s = Strikes(capacity=5)
    s.insort(_strike(10.0))
    s.insort(_strike(30.0))
    assert s.insort(_strike(20.0)) == ()
    assert [e._publication_date for e in s] == [10.0, 20.0, 30.0]


def test_cleanup_removes_strikes_older_than_threshold() -> None:
    """cleanup(k) evicts every strike with key <= k."""
    s = Strikes(capacity=10)
    for t in (1.0, 2.0, 3.0, 4.0, 5.0):
        s.insort(_strike(t))
    evicted = s.cleanup(3.0)
    assert tuple(e._publication_date for e in evicted) == (1.0, 2.0, 3.0)
    assert [e._publication_date for e in s] == [4.0, 5.0]


def test_cleanup_with_no_matching_strikes_returns_empty() -> None:
    """Cleanup below the oldest strike's key returns nothing."""
    s = Strikes(capacity=10)
    s.insort(_strike(10.0))
    s.insort(_strike(20.0))
    assert s.cleanup(5.0) == ()
    assert len(s) == 2


def test_cleanup_on_empty_returns_empty() -> None:
    """Cleanup on an empty cache is a no-op."""
    s = Strikes(capacity=5)
    assert s.cleanup(100.0) == ()


# ---------------------------------------------------------------------------
# BlitzortungEvent.from_recorder_state
# ---------------------------------------------------------------------------


def _make_recorder_state(
    *,
    entity_id: str = f"{STRIKE_ENTITY_ID_PREFIX}abc123",
    distance: str = "42.5",
    latitude: float = 50.0,
    longitude: float = 10.0,
    strike_id: str = "abc123",
    publication_date: datetime | None = None,
) -> State:
    pub_date = publication_date or datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)
    return State(
        entity_id=entity_id,
        state=distance,
        attributes={
            ATTR_LATITUDE: latitude,
            ATTR_LONGITUDE: longitude,
            ATTR_EXTERNAL_ID: strike_id,
            ATTR_PUBLICATION_DATE: pub_date,
        },
    )


def test_from_recorder_state_reconstructs_event() -> None:
    """A well-formed recorder state must round-trip into an Event."""
    state = _make_recorder_state(strike_id="deadbeef")
    event = BlitzortungEvent.from_recorder_state(state, unit="km")
    assert event is not None
    assert event._strike_id == "deadbeef"
    assert event.entity_id == f"{STRIKE_ENTITY_ID_PREFIX}deadbeef"
    assert event._attr_distance == 42.5
    assert event._attr_latitude == 50.0
    assert event._attr_longitude == 10.0
    assert event._attr_unit_of_measurement == "km"


def test_from_recorder_state_parses_iso_publication_date() -> None:
    """publication_date may have been serialised to ISO string by recorder."""
    state = State(
        entity_id=f"{STRIKE_ENTITY_ID_PREFIX}x",
        state="10.0",
        attributes={
            ATTR_LATITUDE: 50.0,
            ATTR_LONGITUDE: 10.0,
            ATTR_EXTERNAL_ID: "x",
            ATTR_PUBLICATION_DATE: "2026-05-26T12:00:00+00:00",
        },
    )
    event = BlitzortungEvent.from_recorder_state(state, unit="km")
    assert event is not None
    assert event._publication_date > 0


def test_from_recorder_state_returns_none_on_missing_attrs() -> None:
    """Corrupt/incomplete state must not raise — just return None."""
    state = State(
        entity_id=f"{STRIKE_ENTITY_ID_PREFIX}x",
        state="unknown",
        attributes={},
    )
    assert BlitzortungEvent.from_recorder_state(state, unit="km") is None


def test_from_recorder_state_returns_none_on_unparseable_state() -> None:
    """Non-numeric state value must not raise."""
    state = _make_recorder_state(distance="not-a-number")
    assert BlitzortungEvent.from_recorder_state(state, unit="km") is None


# ---------------------------------------------------------------------------
# Categorise + capacity helpers (pure functions)
# ---------------------------------------------------------------------------


def _make_manager(
    capacity: int = 10, window_seconds: int = 7200
) -> BlitzortungEventManager:
    return BlitzortungEventManager(
        hass=MagicMock(),
        async_add_entities=MagicMock(),
        max_tracked_lightnings=capacity,
        window_seconds=window_seconds,
    )


def test_categorise_skips_live_entries() -> None:
    """Entities already in the live cache are left alone (daily backstop case)."""
    manager = _make_manager()
    live_ev = BlitzortungEvent(
        distance=10.0,
        latitude=50.0,
        longitude=10.0,
        unit="km",
        time=int(dt_util.utcnow().timestamp() * 1e9),
        status=0,
        region=0,
        strike_id="live",
    )
    manager._strikes.insort(live_ev)

    rebuild, purge = _categorise_strikes(
        db_entity_ids=[live_ev.entity_id],
        states_dict={},
        manager=manager,
        start_ts=0.0,
    )
    assert rebuild == []
    assert purge == []


def test_categorise_purges_entries_with_no_state_in_window() -> None:
    """An entity_id absent from the recent-states dict is an orphan."""
    manager = _make_manager()
    orphan_id = f"{STRIKE_ENTITY_ID_PREFIX}orphan"
    rebuild, purge = _categorise_strikes(
        db_entity_ids=[orphan_id],
        states_dict={},
        manager=manager,
        start_ts=0.0,
    )
    assert rebuild == []
    assert purge == [orphan_id]


def test_categorise_rebuilds_entries_with_state_in_window() -> None:
    """A valid state inside the window produces a rebuild candidate."""
    manager = _make_manager()
    pub_date = dt_util.utcnow() - timedelta(minutes=10)
    state = _make_recorder_state(
        entity_id=f"{STRIKE_ENTITY_ID_PREFIX}fresh",
        strike_id="fresh",
        publication_date=pub_date,
    )
    rebuild, purge = _categorise_strikes(
        db_entity_ids=[state.entity_id],
        states_dict={state.entity_id: [state]},
        manager=manager,
        start_ts=(dt_util.utcnow() - timedelta(hours=2)).timestamp(),
    )
    assert len(rebuild) == 1
    assert rebuild[0].entity_id == state.entity_id
    assert purge == []


def test_cap_rebuild_to_capacity_respects_remaining_room() -> None:
    """Overflow rebuild candidates (newest kept) get queued for purge."""
    manager = _make_manager(capacity=2)
    now = dt_util.utcnow().timestamp()
    events = [
        BlitzortungEvent(
            distance=1.0,
            latitude=50.0,
            longitude=10.0,
            unit="km",
            time=int((now - i) * 1e9),
            status=0,
            region=0,
            strike_id=f"e{i}",
        )
        for i in range(5)
    ]
    # All five want to come back but capacity is 2; keep the newest two (e0, e1).
    rebuild, purge = _cap_rebuild_to_capacity(events, [], manager)
    rebuild_ids = {e.entity_id for e in rebuild}
    assert len(rebuild) == 2
    # Newest are at the end of the input list (i=0 is newest in our construction)
    assert f"{STRIKE_ENTITY_ID_PREFIX}e0" in rebuild_ids
    assert f"{STRIKE_ENTITY_ID_PREFIX}e1" in rebuild_ids
    assert len(purge) == 3


def test_cap_rebuild_to_capacity_dumps_all_when_cache_already_full() -> None:
    """If the live cache is at capacity, every candidate goes to purge."""
    manager = _make_manager(capacity=1)
    manager._strikes.insort(
        BlitzortungEvent(
            distance=1.0,
            latitude=50.0,
            longitude=10.0,
            unit="km",
            time=int(dt_util.utcnow().timestamp() * 1e9),
            status=0,
            region=0,
            strike_id="live",
        )
    )
    candidate = BlitzortungEvent(
        distance=2.0,
        latitude=50.0,
        longitude=10.0,
        unit="km",
        time=int(dt_util.utcnow().timestamp() * 1e9),
        status=0,
        region=0,
        strike_id="extra",
    )
    rebuild, purge = _cap_rebuild_to_capacity([candidate], [], manager)
    assert rebuild == []
    assert purge == [candidate.entity_id]


# ---------------------------------------------------------------------------
# _async_reconcile_strikes — integration with mocked recorder
# ---------------------------------------------------------------------------


def _make_entry(entry_id: str = "test_entry") -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id=entry_id,
        data={
            CONF_NAME: "Test",
            CONF_LATITUDE: 50.0,
            CONF_LONGITUDE: 10.0,
            CONF_CONFIG_TYPE: CONFIG_TYPE_COORDINATES,
        },
        unique_id=f"50.0-10.0-{entry_id}",
        version=6,
        options={
            CONF_RADIUS: 100,
            CONF_MAX_TRACKED_LIGHTNINGS: 100,
            CONF_TIME_WINDOW: 120,
        },
    )


@pytest.mark.asyncio
async def test_reconcile_skipped_when_other_entry_loaded(
    hass: HomeAssistant,
) -> None:
    """A sibling Blitzortung entry being loaded must short-circuit reconcile."""
    entry_a = _make_entry("a")
    entry_b = _make_entry("b")
    entry_a.add_to_hass(hass)
    entry_b.add_to_hass(hass)
    entry_a.mock_state(hass, ConfigEntryState.LOADED)

    manager = _make_manager()
    with patch(
        "custom_components.blitzortung.geo_location."
        "_async_enumerate_strike_entity_ids",
        new=AsyncMock(),
    ) as enumerate_mock:
        await _async_reconcile_strikes(hass, entry_b, manager)
    enumerate_mock.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_skipped_when_recorder_not_loaded(
    hass: HomeAssistant,
) -> None:
    """Without recorder, reconcile cannot fetch state; must short-circuit."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    manager = _make_manager()
    with patch(
        "custom_components.blitzortung.geo_location."
        "_async_enumerate_strike_entity_ids",
        new=AsyncMock(),
    ) as enumerate_mock:
        await _async_reconcile_strikes(hass, entry, manager)
    enumerate_mock.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_purges_orphans_with_explicit_entity_id_list(
    hass: HomeAssistant,
) -> None:
    """Orphans (in DB, no state inside window) get purged precisely by ID list."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    manager = _make_manager()

    orphan_a = f"{STRIKE_ENTITY_ID_PREFIX}aaa"
    orphan_b = f"{STRIKE_ENTITY_ID_PREFIX}bbb"

    purge_mock = AsyncMock()
    hass.services.async_register("recorder", "purge_entities", purge_mock)

    with (
        patch.object(hass.config, "components", {*hass.config.components, "recorder"}),
        patch(
            "custom_components.blitzortung.geo_location.recorder_get_instance",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.blitzortung.geo_location."
            "_async_enumerate_strike_entity_ids",
            new=AsyncMock(return_value=[orphan_a, orphan_b]),
        ),
        patch(
            "custom_components.blitzortung.geo_location._async_fetch_strike_states",
            new=AsyncMock(return_value={}),
        ),
    ):
        await _async_reconcile_strikes(hass, entry, manager)

    purge_mock.assert_called_once()
    call_data = purge_mock.call_args.args[0].data
    assert set(call_data["entity_id"]) == {orphan_a, orphan_b}


@pytest.mark.asyncio
async def test_reconcile_rebuilds_within_window_strikes(
    hass: HomeAssistant,
) -> None:
    """Strikes with state inside the window get reconstructed and registered."""
    entry = _make_entry()
    entry.add_to_hass(hass)
    add_entities_mock = MagicMock()
    manager = BlitzortungEventManager(
        hass=hass,
        async_add_entities=add_entities_mock,
        max_tracked_lightnings=10,
        window_seconds=7200,
    )

    fresh_id = f"{STRIKE_ENTITY_ID_PREFIX}fresh"
    fresh_state = _make_recorder_state(
        entity_id=fresh_id,
        strike_id="fresh",
        publication_date=dt_util.utcnow() - timedelta(minutes=5),
    )

    purge_mock = AsyncMock()
    hass.services.async_register("recorder", "purge_entities", purge_mock)

    with (
        patch.object(hass.config, "components", {*hass.config.components, "recorder"}),
        patch(
            "custom_components.blitzortung.geo_location.recorder_get_instance",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.blitzortung.geo_location."
            "_async_enumerate_strike_entity_ids",
            new=AsyncMock(return_value=[fresh_id]),
        ),
        patch(
            "custom_components.blitzortung.geo_location._async_fetch_strike_states",
            new=AsyncMock(return_value={fresh_id: [fresh_state]}),
        ),
    ):
        await _async_reconcile_strikes(hass, entry, manager)

    # Strike is in the live cache after reconcile.
    assert any(ev.entity_id == fresh_id for ev in manager._strikes)
    # Entity was registered with HA.
    add_entities_mock.assert_called_once()
    registered = add_entities_mock.call_args.args[0]
    assert any(ev.entity_id == fresh_id for ev in registered)
    # Nothing to purge.
    purge_mock.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_fast_path_when_db_exceeds_threshold(
    hass: HomeAssistant,
) -> None:
    """Huge DBs must skip rebuild and drain via chunked purge_entities calls.

    The rebuild path's categorise loop is O(N) on the main thread and the
    bulk state fetch can hang the recorder executor at scale. Chunked
    service calls keep each recorder task small and let the main loop
    stay responsive while the orphans drain in the background.
    """
    entry = _make_entry()
    entry.add_to_hass(hass)
    manager = _make_manager(window_seconds=7200)

    huge_id_list = [
        f"{STRIKE_ENTITY_ID_PREFIX}{i:08x}"
        for i in range(RECONCILE_REBUILD_THRESHOLD + 1)
    ]

    fetch_mock = AsyncMock(return_value={})
    purge_mock = AsyncMock()

    with (
        patch.object(hass.config, "components", {*hass.config.components, "recorder"}),
        patch(
            "custom_components.blitzortung.geo_location.recorder_get_instance",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.blitzortung.geo_location."
            "_async_enumerate_strike_entity_ids",
            new=AsyncMock(return_value=huge_id_list),
        ),
        patch(
            "custom_components.blitzortung.geo_location._async_fetch_strike_states",
            new=fetch_mock,
        ),
        patch(
            "custom_components.blitzortung.geo_location."
            "_async_batched_service_purge",
            new=purge_mock,
        ),
    ):
        await _async_reconcile_strikes(hass, entry, manager)

    # Bulk state fetch (the heavy O(N) categorise input) was NOT called.
    fetch_mock.assert_not_called()
    # Service-based batched purge was invoked with the full ID list.
    purge_mock.assert_called_once()
    hass_arg, instance_arg, manager_arg, found_count = purge_mock.call_args.args
    assert hass_arg is hass
    assert manager_arg is manager
    assert instance_arg is not None
    assert found_count == len(huge_id_list)


@pytest.mark.asyncio
async def test_batched_service_purge_drains_via_cursor_until_empty(
    hass: HomeAssistant,
) -> None:
    """Cleanup loops cursor-paged enumerations until the table is empty."""
    manager = _make_manager(window_seconds=7200)
    instance = MagicMock()

    # 2.5 chunks worth of strike entities; cursor enumerator returns slices.
    total = int(PURGE_CHUNK_SIZE * 2.5)
    all_rows = [
        (i + 1, f"{STRIKE_ENTITY_ID_PREFIX}{i:08x}") for i in range(total)
    ]

    call_log: list[list[str]] = []

    async def fake_enumerate(_inst: object, after: int, limit: int) -> list:
        # Return rows with metadata_id > after, up to limit.
        return [r for r in all_rows if r[0] > after][:limit]

    purge_mock = AsyncMock(
        side_effect=lambda call: call_log.append(list(call.data["entity_id"])),
    )
    hass.services.async_register("recorder", "purge_entities", purge_mock)
    sleep_mock = AsyncMock()

    with (
        patch(
            "custom_components.blitzortung.geo_location."
            "_async_enumerate_strike_chunk",
            new=fake_enumerate,
        ),
        patch(
            "custom_components.blitzortung.geo_location.asyncio.sleep",
            new=sleep_mock,
        ),
    ):
        await _async_batched_service_purge(hass, instance, manager, total)

    # 3 chunks (350, 350, 175). Then a 4th enumerate returns empty → terminate.
    assert purge_mock.call_count == 3
    assert sleep_mock.call_count == 3
    chunk_sizes = [len(ids) for ids in call_log]
    assert chunk_sizes == [
        PURGE_CHUNK_SIZE,
        PURGE_CHUNK_SIZE,
        total - 2 * PURGE_CHUNK_SIZE,
    ]
    # keep_days is derived from time_window (7200s = 0 days, since < 1 day).
    for call in purge_mock.call_args_list:
        data = call.args[0].data
        assert "entity_id" in data
        assert "entity_globs" not in data
        assert data["keep_days"] == 0


@pytest.mark.asyncio
async def test_batched_service_purge_continues_after_chunk_failure(
    hass: HomeAssistant,
) -> None:
    """One failing chunk must not abort the whole drain."""
    manager = _make_manager(window_seconds=7200)
    instance = MagicMock()

    total = PURGE_CHUNK_SIZE * 3
    all_rows = [
        (i + 1, f"{STRIKE_ENTITY_ID_PREFIX}{i:08x}") for i in range(total)
    ]

    async def fake_enumerate(_inst: object, after: int, limit: int) -> list:
        return [r for r in all_rows if r[0] > after][:limit]

    call_n = {"i": 0}

    async def flaky_purge(_call: object) -> None:
        call_n["i"] += 1
        if call_n["i"] == 2:
            raise RuntimeError("transient recorder error")

    hass.services.async_register("recorder", "purge_entities", flaky_purge)
    sleep_mock = AsyncMock()

    with (
        patch(
            "custom_components.blitzortung.geo_location."
            "_async_enumerate_strike_chunk",
            new=fake_enumerate,
        ),
        patch(
            "custom_components.blitzortung.geo_location.asyncio.sleep",
            new=sleep_mock,
        ),
    ):
        await _async_batched_service_purge(hass, instance, manager, total)

    # All 3 chunks attempted; the failure in chunk 2 didn't abort the loop.
    assert call_n["i"] == 3


@pytest.mark.asyncio
async def test_batched_service_purge_uses_window_for_keep_days(
    hass: HomeAssistant,
) -> None:
    """keep_days = window_seconds // 86400, no 24h margin added."""
    instance = MagicMock()

    # Single chunk only — set up empty enumeration after the first slice.
    async def fake_enumerate_once(_inst: object, after: int, limit: int) -> list:
        if after == 0:
            return [(1, f"{STRIKE_ENTITY_ID_PREFIX}aa")]
        return []

    purge_mock = AsyncMock()
    hass.services.async_register("recorder", "purge_entities", purge_mock)

    with (
        patch(
            "custom_components.blitzortung.geo_location."
            "_async_enumerate_strike_chunk",
            new=fake_enumerate_once,
        ),
        patch(
            "custom_components.blitzortung.geo_location.asyncio.sleep",
            new=AsyncMock(),
        ),
    ):
        # window = 25h → keep_days = 25*3600 // 86400 = 1
        await _async_batched_service_purge(
            hass, instance, _make_manager(window_seconds=25 * 3600), 1
        )
        assert purge_mock.call_args.args[0].data["keep_days"] == 1
        purge_mock.reset_mock()

        # window = 2d → keep_days = 2
        await _async_batched_service_purge(
            hass, instance, _make_manager(window_seconds=2 * 86400), 1
        )
        assert purge_mock.call_args.args[0].data["keep_days"] == 2
        purge_mock.reset_mock()

        # window = 2h → keep_days = 0 (sub-day, no preservation)
        await _async_batched_service_purge(
            hass, instance, _make_manager(window_seconds=2 * 3600), 1
        )
        assert purge_mock.call_args.args[0].data["keep_days"] == 0


# ---------------------------------------------------------------------------
# Daily periodic reconcile
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_periodic_reconcile_fires_on_interval(
    hass: HomeAssistant,
    mock_config_entry_coordinates: MockConfigEntry,
    mock_mqtt: MagicMock,
) -> None:
    """The daily backstop sweep must fire on its interval after setup."""
    with patch(
        "custom_components.blitzortung.geo_location._async_reconcile_strikes",
        new=AsyncMock(),
    ) as reconcile_mock:
        await hass.config_entries.async_setup(mock_config_entry_coordinates.entry_id)
        await hass.async_block_till_done()
        # Initial reconcile at setup.
        assert reconcile_mock.call_count == 1

        async_fire_time_changed(
            hass, dt_util.utcnow() + RECONCILE_INTERVAL + timedelta(seconds=1)
        )
        await hass.async_block_till_done()

    assert reconcile_mock.call_count == 2
