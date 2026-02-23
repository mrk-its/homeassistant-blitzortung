"""Config flow for blitzortung integration."""

from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME
from homeassistant.helpers import selector
from homeassistant.helpers.schema_config_entry_flow import (
    add_suggested_values_to_schema,
)

from .const import (
    CONF_CONFIG_TYPE,
    CONF_LOCATION_ENTITY,
    CONF_MAX_TRACKED_LIGHTNINGS,
    CONF_RADIUS,
    CONF_TIME_WINDOW,
    CONFIG_TYPE_COORDINATES,
    CONFIG_TYPE_TRACKER,
    DEFAULT_MAX_TRACKED_LIGHTNINGS,
    DEFAULT_RADIUS,
    DEFAULT_TIME_WINDOW,
    DOMAIN,
)

# Only allow tracker-like entities
LOCATION_ENTITY_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["device_tracker"])
)

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

RECONFIGURE_COORDINATES_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_LATITUDE): cv.latitude,
        vol.Optional(CONF_LONGITUDE): cv.longitude,
    }
)


def _get_reconfigure_schema(entry: ConfigEntry) -> vol.Schema:
    """Build the reconfigure schema with suggested values for coordinate entries."""
    suggested: dict[str, object] = {}
    if (lat := entry.data.get(CONF_LATITUDE)) is not None:
        suggested[CONF_LATITUDE] = lat
    if (lon := entry.data.get(CONF_LONGITUDE)) is not None:
        suggested[CONF_LONGITUDE] = lon

    return add_suggested_values_to_schema(RECONFIGURE_COORDINATES_SCHEMA, suggested)


class BlitzortungConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Blitzortung."""

    VERSION = 6
    MINOR_VERSION = 0

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select how the user wants to configure the entry."""
        if user_input is not None:
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

        return self.async_show_form(
            step_id="tracker",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME,
                        default=self.hass.config.location_name,
                    ): str,
                    vol.Required(CONF_LOCATION_ENTITY): LOCATION_ENTITY_SELECTOR,
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

        return self.async_show_form(
            step_id="coordinates",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME,
                        default=self.hass.config.location_name,
                    ): str,
                    vol.Required(
                        CONF_LATITUDE,
                        default=self.hass.config.latitude,
                    ): cv.latitude,
                    vol.Required(
                        CONF_LONGITUDE,
                        default=self.hass.config.longitude,
                    ): cv.longitude,
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of an existing entry (coordinates only).

        Changing the location entity type is not supported via reconfigure.
        To change from tracker to coordinates or vice versa, remove and re-add
        the integration.
        """
        entry = self._get_reconfigure_entry()

        # Only coordinate entries can be reconfigured this way.
        # Tracker entries show a read-only notice and abort immediately.
        config_type = entry.data.get(CONF_CONFIG_TYPE)
        if config_type == CONFIG_TYPE_TRACKER:
            return self.async_abort(reason="tracker_reconfigure_not_supported")

        if user_input is not None:
            data: dict[str, Any] = dict(entry.data)

            # Preserve stored coordinates if the user clears them.
            lat = user_input.get(CONF_LATITUDE)
            lon = user_input.get(CONF_LONGITUDE)
            if lat in (None, ""):
                lat = entry.data.get(CONF_LATITUDE)
            if lon in (None, ""):
                lon = entry.data.get(CONF_LONGITUDE)

            data[CONF_LATITUDE] = (
                lat if lat is not None
                else entry.data.get(CONF_LATITUDE, self.hass.config.latitude)
            )
            data[CONF_LONGITUDE] = (
                lon if lon is not None
                else entry.data.get(CONF_LONGITUDE, self.hass.config.longitude)
            )

            # Never store a tracker entity in a coordinates entry.
            data.pop(CONF_LOCATION_ENTITY, None)
            data[CONF_CONFIG_TYPE] = CONFIG_TYPE_COORDINATES

            self.hass.config_entries.async_update_entry(entry, data=data)
            return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_get_reconfigure_schema(entry),
            description_placeholders={"name": entry.title},
        )

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
