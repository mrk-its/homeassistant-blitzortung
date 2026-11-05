"""Tests that ws_client and the integration agree on the binary strike format."""

import importlib.util
from pathlib import Path

from homeassistant.core import HomeAssistant

from custom_components.blitzortung import BlitzortungCoordinator
from custom_components.blitzortung.const import (
    BINARY_STRIKE,
    BINARY_TOPIC_GEOHASH_LEN,
    BINARY_TOPIC_PREFIX,
)
from custom_components.blitzortung.mqtt import Message

# Loaded by path: importing the ws_client package pulls in websockets and geohash.
_spec = importlib.util.spec_from_file_location(
    "ws_client_binary",
    Path(__file__).parents[1] / "ws_client" / "ws_client" / "binary.py",
)
ws_binary = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ws_binary)


def test_encode_is_little_endian_16_bytes() -> None:
    """Test the payload layout is fixed regardless of the host byte order."""
    payload = ws_binary.encode(1.0, -2.0, 0x0102030405060708)
    assert payload == (
        b"\x00\x00\x80\x3f"  # 1.0
        b"\x00\x00\x00\xc0"  # -2.0
        b"\x08\x07\x06\x05\x04\x03\x02\x01"
    )


def test_constants_match_integration() -> None:
    """Test producer and consumer use the same topic prefix and layout."""
    assert ws_binary.TOPIC_PREFIX == BINARY_TOPIC_PREFIX
    assert ws_binary.STRIKE.format == BINARY_STRIKE.format
    assert ws_binary.TOPIC_GEOHASH_LEN == BINARY_TOPIC_GEOHASH_LEN


async def test_integration_decodes_ws_client_payload(hass: HomeAssistant) -> None:
    """Test a strike encoded by ws_client reaches the integration intact."""
    coordinator = BlitzortungCoordinator(hass, 50.0, 10.0, None, 100, 100, 600, False)
    received = []

    async def lightning_cb(lightning: dict) -> None:
        received.append(lightning)

    coordinator.lightning_callbacks.append(lightning_cb)

    await coordinator.on_mqtt_message(
        Message(
            topic=f"{ws_binary.TOPIC_PREFIX}/u/3/3/c/x/y",
            payload=ws_binary.encode(50.12345, 10.54321, 1_730_900_000_123_456_789),
            qos=0,
            retain=False,
        )
    )

    assert len(received) == 1
    assert received[0]["lat"] == 50.12345
    assert received[0]["lon"] == 10.54321
    assert received[0]["time"] == 1_730_900_000_123_456_789
