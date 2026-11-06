"""Parse mosquitto log lines (log_type subscribe, unsubscribe and notice)."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

_CONNECT = re.compile(r"^(\d+): New client connected from (\S+) as (\S+) \(")
_END = re.compile(r"^(\d+): Client (\S+) ")
_SUBSCRIBE = re.compile(r"^(\d+): (\S+) [012] (\S+)$")
_UNSUBSCRIBE = re.compile(r"^(\d+): (\S+) (\S+)$")


@dataclass(frozen=True)
class Connect:
    """A client session started."""

    ts: int
    client_id: str
    ip: str


@dataclass(frozen=True)
class End:
    """A client session ended (closed, disconnected, timed out, taken over)."""

    ts: int
    client_id: str


@dataclass(frozen=True)
class Subscribe:
    """A client subscribed to a topic filter."""

    ts: int
    client_id: str
    topic: str


@dataclass(frozen=True)
class Unsubscribe:
    """A client unsubscribed from a topic filter."""

    ts: int
    client_id: str
    topic: str


Event = Connect | End | Subscribe | Unsubscribe


def normalize_ip(address: str) -> str | None:
    """Turn mosquitto's ``host:port`` into a plain IP; IPv4-mapped IPv6 becomes IPv4."""
    host = address.rsplit(":", 1)[0].strip("[]")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return str(ip.ipv4_mapped)
    return str(ip)


def parse_line(line: str) -> Event | None:
    """Return the event a log line describes, or None for lines that don't matter."""
    line = line.rstrip("\n")
    if m := _CONNECT.match(line):
        ip = normalize_ip(m.group(2))
        return Connect(int(m.group(1)), m.group(3), ip) if ip else None
    if m := _END.match(line):
        return End(int(m.group(1)), m.group(2))
    if m := _SUBSCRIBE.match(line):
        return Subscribe(int(m.group(1)), m.group(2), m.group(3))
    if m := _UNSUBSCRIBE.match(line):
        return Unsubscribe(int(m.group(1)), m.group(2), m.group(3))
    return None
