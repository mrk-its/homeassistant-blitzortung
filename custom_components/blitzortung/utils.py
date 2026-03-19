"""Utils for Blitzortung integration."""

from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE
from homeassistant.core import HomeAssistant


def get_coordinates_from_entity(
    hass: HomeAssistant, entity_id: str
) -> tuple[float, float] | None:
    """Get coordinates from entity."""
    state = hass.states.get(entity_id)
    if state is None:
        return None

    latitude = state.attributes.get(ATTR_LATITUDE)
    longitude = state.attributes.get(ATTR_LONGITUDE)

    if latitude is None or longitude is None:
        return None

    return latitude, longitude
