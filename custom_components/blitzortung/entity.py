"""Define Blitzortung entity."""

from typing import Any
from .mqtt import Message
from .const import ATTRIBUTION

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
