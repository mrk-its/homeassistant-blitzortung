"""Config flow for blitzortung integration."""

from typing import Any

import homeassistant.helpers.config_validation as cv

try:
    from homeassistant.helpers.schema_config_entry_flow import (
        add_suggested_values_to_schema,
    )
except ImportError:  # pragma: no cover
    add_suggested_values_to_schema = None
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.helpers import selector

from .const import (
    CONF_LOCATION_ENTITY,
    CONF_MAX_TRACKED_LIGHTNINGS,
    CONF_RADIUS,
    CONF_TIME_WINDOW,
    DEFAULT_MAX_TRACKED_LIGHTNINGS,
    DEFAULT_RADIUS,
    DEFAULT_TIME_WINDOW,
    DOMAIN,
)

# Only allow tracker-like entities
LOCATION_ENTITY_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["device_tracker"])
)

LOCATION_ENTITY_SELECTOR_OR_NONE = vol.Any(None, LOCATION_ENTITY_SELECTOR)

RECONFIGURE_SCHEMA = vol.Schema(
    {
        # Keep lat/lon visible but not required (can be empty when using a tracker)
        vol.Optional(CONF_LATITUDE): cv.latitude,
        vol.Optional(CONF_LONGITUDE): cv.longitude,
        vol.Optional(CONF_LOCATION_ENTITY): LOCATION_ENTITY_SELECTOR_OR_NONE,
    }
)

def _get_reconfigure_schema(entry: ConfigEntry) -> vol.Schema:
    """Build the reconfigure schema with suggested values.

    We only suggest fields relevant to the existing configuration mode.
    """
    suggested: dict[str, object] = {}
    config_type = entry.data.get(CONF_CONFIG_TYPE)
    if config_type == CONFIG_TYPE_TRACKER:
        if (tracker_entity := entry.data.get(CONF_LOCATION_ENTITY)) is not None:
            suggested[CONF_LOCATION_ENTITY] = tracker_entity
    else:
        if (lat := entry.data.get(CONF_LATITUDE)) is not None:
            suggested[CONF_LATITUDE] = lat
        if (lon := entry.data.get(CONF_LONGITUDE)) is not None:
            suggested[CONF_LONGITUDE] = lon

    if add_suggested_values_to_schema is None:
        return RECONFIGURE_SCHEMA
    return add_suggested_values_to_schema(RECONFIGURE_SCHEMA, suggested)


CONF_CONFIG_TYPE = "config_type"
CONFIG_TYPE_TRACKER = "tracker"
CONFIG_TYPE_COORDINATES = "coordinates"

CONFIG_TYPE_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=[
            selector.SelectOptionDict(
                value=CONFIG_TYPE_TRACKER, label="Tracker entity"
            ),
            selector.SelectOptionDict(
                value=CONFIG_TYPE_COORDINATES, label="Latitude/Longitude"
            ),
        ],
        mode=selector.SelectSelectorMode.DROPDOWN,
        translation_key=CONF_CONFIG_TYPE,
    )
)


class BlitzortungConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Blitzortung."""

    VERSION = 6
    MINOR_VERSION = 0

    def _ensure_lat_lon(self, data: dict[str, Any]) -> dict[str, Any]:
        """Ensure latitude/longitude exist (fallback to HA defaults)."""
        out = dict(data)
        if CONF_LATITUDE not in out:
            out[CONF_LATITUDE] = self.hass.config.latitude
        if CONF_LONGITUDE not in out:
            out[CONF_LONGITUDE] = self.hass.config.longitude
        return out

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select how the user wants to configure the entry."""
        if user_input is not None:
            # Store temporary selection to determine the next flow step
            self.context[CONF_CONFIG_TYPE] = user_input[CONF_CONFIG_TYPE]
            if user_input[CONF_CONFIG_TYPE] == CONFIG_TYPE_TRACKER:
                return await self.async_step_tracker()
            return await self.async_step_coordinates()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CONFIG_TYPE, default=CONFIG_TYPE_TRACKER
                    ): CONFIG_TYPE_SELECTOR,
                }
            ),
        )

    async def async_step_tracker(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure the entry using a tracking entity."""
        if user_input is not None:
            location_entity = user_input[CONF_LOCATION_ENTITY]

            unique_id = f"tracker-{location_entity.lower()}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            title = user_input[CONF_NAME]

            data = {
                CONF_NAME: title,
                CONF_CONFIG_TYPE: CONFIG_TYPE_TRACKER,
                CONF_LOCATION_ENTITY: location_entity,
            }

            return self.async_create_entry(
                title=title,
                data=data,
                options={
                    CONF_RADIUS: DEFAULT_RADIUS,
                    CONF_MAX_TRACKED_LIGHTNINGS: DEFAULT_MAX_TRACKED_LIGHTNINGS,
                    CONF_TIME_WINDOW: DEFAULT_TIME_WINDOW,
                },
            )

        defaults = user_input or {}
        return self.async_show_form(
            step_id="tracker",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME,
                        default=defaults.get(CONF_NAME, self.hass.config.location_name),
                    ): str,
                    vol.Required(
                        CONF_LOCATION_ENTITY,
                        default=defaults.get(CONF_LOCATION_ENTITY),
                    ): LOCATION_ENTITY_SELECTOR,
                }
            ),
        )

    async def async_step_coordinates(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure the entry using fixed coordinates."""
        if user_input is not None:
            lat = user_input[CONF_LATITUDE]
            lon = user_input[CONF_LONGITUDE]

            unique_id = f"{lat}-{lon}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            data = {
                CONF_NAME: user_input[CONF_NAME],
                CONF_CONFIG_TYPE: CONFIG_TYPE_COORDINATES,
                CONF_LATITUDE: lat,
                CONF_LONGITUDE: lon,
            }

            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data=data,
                options={
                    CONF_RADIUS: DEFAULT_RADIUS,
                    CONF_MAX_TRACKED_LIGHTNINGS: DEFAULT_MAX_TRACKED_LIGHTNINGS,
                    CONF_TIME_WINDOW: DEFAULT_TIME_WINDOW,
                },
            )

        defaults = user_input or {}
        return self.async_show_form(
            step_id="coordinates",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME,
                        default=defaults.get(CONF_NAME, self.hass.config.location_name),
                    ): str,
                    vol.Required(
                        CONF_LATITUDE,
                        default=defaults.get(CONF_LATITUDE, self.hass.config.latitude),
                    ): cv.latitude,
                    vol.Required(
                        CONF_LONGITUDE,
                        default=defaults.get(
                            CONF_LONGITUDE, self.hass.config.longitude
                        ),
                    ): cv.longitude,
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of an existing entry."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            data: dict[str, Any] = dict(entry.data)
            data.update(user_input)

            config_type = data.get(CONF_CONFIG_TYPE)
            if config_type is None:
                config_type = (
                    CONFIG_TYPE_TRACKER
                    if data.get(CONF_LOCATION_ENTITY)
                    else CONFIG_TYPE_COORDINATES
                )

            if config_type == CONFIG_TYPE_TRACKER:
                # Do not allow reconfigure to switch config mode or store coordinates.
                tracker_entity = entry.data.get(CONF_LOCATION_ENTITY) or data.get(
                    CONF_LOCATION_ENTITY
                )
                if tracker_entity:
                    data[CONF_LOCATION_ENTITY] = tracker_entity
                else:
                    data.pop(CONF_LOCATION_ENTITY, None)

                data.pop(CONF_LATITUDE, None)
                data.pop(CONF_LONGITUDE, None)
            else:
                # Do not allow reconfigure to switch config mode/store a tracker entity.
                data.pop(CONF_LOCATION_ENTITY, None)

                # Preserve stored coordinates if the user clears them.
                if (
                    data.get(CONF_LATITUDE) in (None, "")
                    or data.get(CONF_LONGITUDE) in (None, "")
                ):
                    entry_lat = entry.data.get(CONF_LATITUDE)
                    entry_lon = entry.data.get(CONF_LONGITUDE)
                    if entry_lat is not None and entry_lon is not None:
                        data[CONF_LATITUDE] = entry_lat
                        data[CONF_LONGITUDE] = entry_lon
                data = self._ensure_lat_lon(data)

            data[CONF_CONFIG_TYPE] = config_type
            self.hass.config_entries.async_update_entry(entry, data=data)

            return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_get_reconfigure_schema(entry),
            description_placeholders={"name": entry.title},
        )

    def _get_reconfigure_entry(self) -> ConfigEntry:
        """Return the entry that is being reconfigured."""
        entry_id = self.context.get("entry_id")
        if not entry_id:
            raise ValueError("Missing entry_id in reconfigure context")

        entry = self.hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            raise ValueError(f"Unknown entry_id: {entry_id}")

        return entry

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return BlitzortungOptionsFlowHandler(config_entry)


class BlitzortungOptionsFlowHandler(OptionsFlow):
    """Handle options for Blitzortung."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self._config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_RADIUS, default=options.get(CONF_RADIUS, DEFAULT_RADIUS)
                    ): vol.Coerce(int),
                    vol.Required(
                        CONF_TIME_WINDOW,
                        default=options.get(CONF_TIME_WINDOW, DEFAULT_TIME_WINDOW),
                    ): vol.Coerce(int),
                    vol.Required(
                        CONF_MAX_TRACKED_LIGHTNINGS,
                        default=options.get(
                            CONF_MAX_TRACKED_LIGHTNINGS, DEFAULT_MAX_TRACKED_LIGHTNINGS
                        ),
                    ): vol.Coerce(int),
                }
            ),
        )
