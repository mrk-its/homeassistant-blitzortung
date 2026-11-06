"""Tests for subscription area."""

import pytest

from mqtt_area_ban.area import client_area, client_family, ip_usage, parse_filter
from mqtt_area_ban.state import Session


@pytest.mark.parametrize(
    ("topic", "area"),
    [
        ("#", 1.0),
        ("blitzortung/#", 1.0),
        ("blitzortung/1.1/#", 1.0),
        ("blitzortung/+/#", 1.0),
        ("blitzortung/1.1/u/#", 1 / 32),
        ("blitzortung/1.1/u/3/n/#", 32.0**-3),
        ("blitzortung/1.1/+/3/#", 1 / 32),
        ("blitzortung/1.1/" + "/".join("u3nxb2u3nxb2"), 32.0**-12),
        # Receive no strikes:
        ("blitzortung/1/#", 0.0),
        ("blitzortung/1.1/u/3/n", 0.0),
        ("blitzortung/1.1/+/+/u9", 0.0),
        ("blitzortung/1.1/a/#", 0.0),
        ("blitzortung/1.1/#/u", 0.0),
        ("component/hello", 0.0),
        ("b/1/u/#", 0.0),
    ],
)
def test_single_topic_area(topic: str, area: float) -> None:
    """Each topic shape maps to the right area."""
    assert client_area([topic]) == pytest.approx(area)


def test_parse_filter_shapes() -> None:
    """Patterns keep geohash levels and the trailing '#'."""
    assert parse_filter("blitzortung/1.1/u/3/#") == (("u", "3"), True)
    assert parse_filter("blitzortung") is None


def test_nested_topics_count_once() -> None:
    """A topic inside another of the same client adds nothing."""
    topics = ["blitzortung/1.1/u/#", "blitzortung/1.1/u/3/#", "blitzortung/1.1/u/3/n/#"]
    assert client_area(topics) == pytest.approx(1 / 32)
    assert client_area([*topics, "blitzortung/1.1/#"]) == pytest.approx(1.0)


def test_wildcard_covers_literal() -> None:
    """Wildcards hide the literals they contain, and the other way round."""
    assert client_area(
        ["blitzortung/1.1/+/3/#", "blitzortung/1.1/u/3/n/#"]
    ) == pytest.approx(1 / 32)
    assert client_area(
        ["blitzortung/1.1/u/#", "blitzortung/1.1/u/+/n/#"]
    ) == pytest.approx(1 / 32)


def test_neighbour_cells_add_up() -> None:
    """Disjoint cells sum."""
    cells = [f"blitzortung/1.1/u/3/{c}/#" for c in "npqr"]
    assert client_area(cells) == pytest.approx(4 * 32.0**-3)


def test_client_family() -> None:
    """Random suffixes are stripped."""
    assert client_family("auto-2FC87553-1C0C-66C8-AF92-A0362F633877") == "auto"
    assert client_family("meshcore_weather_1793951688") == "meshcore_weather"
    assert client_family("shtff7daa9d1") == "sht"
    assert client_family("D0611A24-A519-7AC5-A244-65EA731CCB2A") == "<random id>"


def _sessions() -> dict[str, Session]:
    return {
        "ha1": Session(
            "203.0.113.1", {"component/hello", "blitzortung/1.1/u/#"}, ha=True
        ),
        "bot": Session("203.0.113.1", {"blitzortung/1.1/#"}),
        "ha2": Session(
            "203.0.113.2", {"component/hello", "blitzortung/1.1/#"}, ha=True
        ),
        "bot2a": Session("203.0.113.3", {"blitzortung/1.1/#"}),
        "bot2b": Session("203.0.113.3", {"blitzortung/1.1/#"}),
    }


def test_ip_usage_sums_clients() -> None:
    """Clients behind one IP add up, each gets its own copy."""
    usage = ip_usage(_sessions(), exclude_ha=False)
    assert usage["203.0.113.1"].area == pytest.approx(1 + 1 / 32)
    assert usage["203.0.113.1"].clients == 2
    assert usage["203.0.113.1"].ha_clients == 1
    assert usage["203.0.113.2"].area == pytest.approx(1.0)
    assert usage["203.0.113.3"].area == pytest.approx(2.0)


def test_exclude_ha_judges_non_ha_clients_only() -> None:
    """A mixed IP keeps its non-HA area; an HA-only IP drops to zero."""
    usage = ip_usage(_sessions(), exclude_ha=True)
    assert usage["203.0.113.1"].area == pytest.approx(1.0)
    assert usage["203.0.113.1"].families == {"bot": 1}
    assert usage["203.0.113.2"].area == 0.0
