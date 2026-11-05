"""Shared test helpers."""

from custom_components.blitzortung.const import BINARY_STRIKE, BINARY_TOPIC_PREFIX
from custom_components.blitzortung.mqtt import Message


def strike_message(
    lat: float, lon: float, time_ns: int = 1_000_000_000, topic: str = "u/3/3"
) -> Message:
    """Build a binary strike message as published by ws_client."""
    return Message(
        topic=f"{BINARY_TOPIC_PREFIX}/{topic}",
        payload=BINARY_STRIKE.pack(lat, lon, time_ns),
        qos=0,
        retain=False,
    )
