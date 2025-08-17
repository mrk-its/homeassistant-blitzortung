"""Define Blitzortung entity."""

from typing import Any

from .const import ATTRIBUTION
from .mqtt import Message


class BlitzortungEntity:
    """Define a Blitzortung sensor."""

    _attr_should_poll = False
    _attr_attribution = ATTRIBUTION

    def update_lightning(self, lightning: dict[str, Any]) -> None:
        """Update the sensor data."""

    def on_message(self, message: Message) -> None:
        """Handle incoming MQTT messages."""

    def tick(self) -> None:
        """Handle tick."""
