<!-- CLAUDE.md is a symlink to this file — edit only AGENTS.md -->
# Instructions for AI Agents (Copilot, Claude, Codex)

## Repository structure

- `custom_components/blitzortung/` — the Home Assistant integration (main deliverable)
- `ws_client/` — standalone CLI proxy/relay (separate deployable, shares version from `version.py`)
- `tests/` — pytest tests using `pytest-homeassistant-custom-component`

## Environment & setup

```sh
python3.13 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
prek install         # not `pre-commit`
```

The toolchain is **prek** (not pre-commit), **ruff** for lint+format, **pytest** for tests.
Pyproject target-version is `py313`. CI runs Python 3.14 with `uv`.

### Lint & format

```sh
ruff check custom_components/blitzortung
ruff format --check custom_components/blitzortung
prek run end-of-file-fixer trailing-whitespace check-yaml check-json check-toml mixed-line-ending --all-files
```

### Test

```sh
pytest tests --cov=custom_components/blitzortung --cov-report=term-missing
```

`pytest.ini` sets `asyncio_mode = auto` and `asyncio_default_fixture_loop_scope = function`.

## Ruff config

- `lint.select = ["ALL"]` with ~15 ignores (ANN401, COM812, D203, D213, EM101/2, FBT001-3, PLR0913/5, TC002/3/6, TRY003/400)
- `custom_components/blitzortung/geohash.py` excluded from checks entirely (vendored third-party)
- `max-complexity = 25`

## Integration architecture

| File | Role |
|---|---|
| `__init__.py` | Setup/teardown, config migration, `BlitzortungCoordinator` class (central orchestrator) |
| `config_flow.py` | Config/options flow (2 modes: fixed coords or entity-based) |
| `const.py` | Constants, defaults, platform list `["sensor", "geo_location"]` |
| `entity.py` | Base `BlitzortungEntity` with `update_lightning`, `on_message`, `tick` |
| `sensor.py` | Distance, Azimuth, Counter sensors + optional ServerStat sensors |
| `geo_location.py` | `BlitzortungEventManager` + `BlitzortungEvent` (GeolocationEvent per strike) |
| `mqtt.py` | Custom paho-mqtt wrapper (not using HA's MQTT component) |
| `version.py` | Single source of truth: `__version__ = "1.5.0"` |

Key facts:
- **No coordinator file** — `BlitzortungCoordinator` lives in `__init__.py:251`
- Connects to public MQTT broker `blitzortung.ha.sed.pl:1883`
- Subscribes to `blitzortung/1.1/{geohash}/#` topics based on geohash overlap
- Config entry currently **version 6** with migrations from v1 in `async_migrate_entry`
- `CONFIG_SCHEMA` in `__init__.py:65` exposes optional `server_stats` bool via `configuration.yaml`
- Two config types: `CONFIG_TYPE_COORDINATES` (fixed lat/lon) and `CONFIG_TYPE_ENTITY` (track device_tracker/person/zone)
- Imperial units: radius is converted from miles to km on setup
- Dynamic location tracking: min move threshold = `radius * 0.25 * 1000` meters
- `geohash_overlap()` selects precision so the tile set fits in ≤9 cells

## Translations

`strings.json` is the source of truth. All 10 translation files in `translations/` (en, fi, fr, hr, nb, nl, pl, sk, sl, ua) must be updated together when adding/changing user-facing strings.

## Code style

Comments explain *why* something is done, not *what* the code does. Do not restate the code or add comments for obvious decisions.

Docstrings: prefer one-liners. If needed, max 2–3 lines — never longer.

## Testing quirks

- Mock the `MQTT` class with the `mock_mqtt` fixture from `tests/conftest.py`
- Fixtures: `mock_config_entry_coordinates`, `mock_config_entry_location_entity`, `mock_location_entity`
- Config flow tests must cover: both config types, error cases (no unique ID, no coords), reconfigure, options flow, `zone.home` special case
- Migration tests cover v1→v6 with edge cases for missing values and renamed keys
- Tests use `MockConfigEntry` and `enable_custom_integrations` autouse fixture

## ws_client (separate package)

- Standalone CLI tool: `ws-client mqtt://host:port [-j] [-b]`
- Depends on `websockets==10.3`, `paho-mqtt==1.5.0`, `python-geohash==0.8.5`
- Copies `version.py` into the package at build time via setup.py
- Not required for the HA integration to run; it's the server-side data feeder
