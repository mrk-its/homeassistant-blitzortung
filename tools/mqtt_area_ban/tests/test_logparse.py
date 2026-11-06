"""Tests for log line parsing, on real mosquitto 2.0.22 lines with doc IPs."""

import pytest

from mqtt_area_ban.logparse import (
    Connect,
    End,
    Subscribe,
    Unsubscribe,
    normalize_ip,
    parse_line,
)

ID = "auto-2FC87553-1C0C-66C8-AF92-A0362F633877"
NEW = "1793956964: New client connected from"


@pytest.mark.parametrize(
    ("line", "event"),
    [
        (
            f"{NEW} 203.0.113.7:47593 as {ID} (p2, c1, k60).",
            Connect(1793956964, ID, "203.0.113.7"),
        ),
        (
            f"{NEW} 203.0.113.7:47593 as {ID} (p2, c1, k60, u'user').",
            Connect(1793956964, ID, "203.0.113.7"),
        ),
        (
            f"{NEW} 2001:db8::5:47593 as x (p5, c0, k15).",
            Connect(1793956964, "x", "2001:db8::5"),
        ),
        (
            f"{NEW} ::ffff:203.0.113.9:1234 as y (p1, c0, k30).",
            Connect(1793956964, "y", "203.0.113.9"),
        ),
        (f"1793956923: Client {ID} closed its connection.", End(1793956923, ID)),
        (
            f"1793956924: Client {ID} has exceeded timeout, disconnecting.",
            End(1793956924, ID),
        ),
        (f"1793956924: Client {ID} disconnected.", End(1793956924, ID)),
        (
            f"1793956924: Client {ID} disconnected due to protocol error.",
            End(1793956924, ID),
        ),
        (
            f"1793956924: Client {ID} already connected, closing old connection.",
            End(1793956924, ID),
        ),
        (
            f"1793951668: {ID} 0 blitzortung/1.1/u/3/n/#",
            Subscribe(1793951668, ID, "blitzortung/1.1/u/3/n/#"),
        ),
        (
            "1793951668: DVES_5EE020 2 cmnd/tasmota/#",
            Subscribe(1793951668, "DVES_5EE020", "cmnd/tasmota/#"),
        ),
        (
            "1793956900: nodered_f7c6b9064d3c3273 blitzortung/1/#",
            Unsubscribe(1793956900, "nodered_f7c6b9064d3c3273", "blitzortung/1/#"),
        ),
        ("1793956829: New connection from 203.0.113.7:27255 on port 1883.", None),
        ("1793956829: New client connected from not-an-ip:1 as z (p2, c1, k60).", None),
        ("garbage", None),
        ("", None),
    ],
)
def test_parse_line(line: str, event: object) -> None:
    """Each line shape gives the expected event."""
    assert parse_line(line + "\n") == event


def test_normalize_ip_brackets() -> None:
    """Bracketed IPv6 is accepted too."""
    assert normalize_ip("[2001:db8::1]:1883") == "2001:db8::1"
