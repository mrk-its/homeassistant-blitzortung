"""Area of the globe MQTT subscriptions receive strikes for (1.0 = whole globe)."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import NamedTuple, Protocol

ROOT = ("blitzortung", "1.1")
GEOHASH_LEVELS = 12  # strikes are published with a full 12-character geohash
GEOHASH_CHARS = frozenset("0123456789bcdefghjkmnpqrstuvwxyz")
HELLO_TOPIC = "component/hello"
_FAMILY_SUFFIX = re.compile(r"[-_]?[0-9a-fA-F]{6,}.*$|[-_]?\d{6,}$")


class Pattern(NamedTuple):
    """Geohash levels of a subscription ('+' = any cell) and whether it ends in '#'."""

    levels: tuple[str, ...]
    tail: bool

    @property
    def area(self) -> float:
        """Fraction of the globe this pattern receives strikes for."""
        return 32.0 ** -sum(1 for level in self.levels if level != "+")

    def covers(self, other: Pattern) -> bool:
        """Return True if this pattern matches every strike ``other`` matches."""
        if not self.tail:
            return self == other
        if len(self.levels) > len(other.levels):
            return False
        return all(
            a in ("+", b) for a, b in zip(self.levels, other.levels, strict=False)
        )


def parse_filter(topic: str) -> Pattern | None:
    """Return the strike pattern of a filter, or None if it receives no strikes."""
    levels = topic.split("/")
    for i, expected in enumerate(ROOT):
        if i >= len(levels):
            return None
        if levels[i] == "#":
            return Pattern((), tail=True) if i == len(levels) - 1 else None
        if levels[i] not in ("+", expected):
            return None
    geo = levels[len(ROOT) :]
    tail = bool(geo) and geo[-1] == "#"
    if tail:
        geo = geo[:-1]
    if len(geo) > GEOHASH_LEVELS or (not tail and len(geo) != GEOHASH_LEVELS):
        return None
    if not all(level == "+" or level in GEOHASH_CHARS for level in geo):
        return None
    return Pattern(tuple(geo), tail=tail)


def client_area(topics: Iterable[str]) -> float:
    """Area covered by one client's subscriptions; nested subscriptions count once."""
    patterns = {p for t in topics if (p := parse_filter(t)) is not None}
    literal_tails = {p.levels for p in patterns if p.tail and "+" not in p.levels}
    wildcards = [p for p in patterns if "+" in p.levels]
    total = 0.0
    for p in patterns:
        # Literal patterns are checked by prefix lookup: clients with thousands of
        # subscriptions exist, and a pairwise check would be quadratic.
        prefixes = (p.levels[:n] for n in range(len(p.levels) + (0 if p.tail else 1)))
        if any(prefix in literal_tails for prefix in prefixes):
            continue
        if any(w != p and w.covers(p) for w in wildcards):
            continue
        total += p.area
    return total


def client_family(client_id: str) -> str:
    """Client ID without its random suffix, to group instances of one app."""
    if client_id.startswith("auto-"):
        return "auto"
    return _FAMILY_SUFFIX.sub("", client_id) or "<random id>"


class SessionLike(Protocol):
    """What ``ip_usage`` needs from a session."""

    ip: str
    topics: set[str]
    ha: bool


@dataclass
class IpUsage:
    """Summed area and clients behind one IP."""

    area: float = 0.0  # live sessions
    clients: int = 0
    ha_clients: int = 0
    families: Counter[str] = field(default_factory=Counter)
    peak: float = 0.0  # largest area seen since the last applied run

    @property
    def score(self) -> float:
        """Area the ban decision uses."""
        return max(self.area, self.peak)


def ip_usage(
    sessions: Mapping[str, SessionLike], exclude_ha: bool
) -> dict[str, IpUsage]:
    """Sum client areas per IP: the broker sends each client its own copy."""
    usage: dict[str, IpUsage] = {}
    for client_id, session in sessions.items():
        entry = usage.setdefault(session.ip, IpUsage())
        entry.clients += 1
        if session.ha:
            entry.ha_clients += 1
            if exclude_ha:
                continue
        area = client_area(session.topics)
        if area > 0:
            entry.area += area
            entry.families[client_family(client_id)] += 1
    return usage
