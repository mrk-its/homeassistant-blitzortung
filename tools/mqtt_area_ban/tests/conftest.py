"""Shared helpers: a fake system runner and log line builders (doc IPs only)."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field

import pytest

BROKER_START = 1_793_956_925


def connect(ts: int, cid: str, ip: str, port: int = 40000) -> str:
    """Connect line as mosquitto 2.0 writes it."""
    return f"{ts}: New client connected from {ip}:{port} as {cid} (p2, c1, k60).\n"


def sub(ts: int, cid: str, topic: str, qos: int = 0) -> str:
    """Subscribe line."""
    return f"{ts}: {cid} {qos} {topic}\n"


def globe_client(ts: int, cid: str, ip: str) -> str:
    """Build a client subscribing to the whole globe."""
    return connect(ts, cid, ip) + sub(ts, cid, "blitzortung/1.1/#")


def ha_client(
    ts: int, cid: str, ip: str, cells: tuple[str, ...] = ("u3n", "u3p")
) -> str:
    """Build an integration-like client: component/hello plus level-3 cells."""
    lines = connect(ts, cid, ip) + sub(ts, cid, "component/hello")
    for cell in cells:
        lines += sub(ts, cid, "blitzortung/1.1/" + "/".join(cell) + "/#")
    return lines


@dataclass
class FakeSystem:
    """Records commands and answers like systemctl, ip, nft and ss would."""

    broker_start: int = BROKER_START
    calls: list[tuple[list[str], str | None]] = field(default_factory=list)
    nft_sets: dict[str, dict[str, int]] = field(default_factory=dict)
    table: bool = False
    fail: set[str] = field(default_factory=set)

    def __call__(
        self, cmd: list[str], stdin: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Dispatch one command."""
        self.calls.append((cmd, stdin))
        name = cmd[0]
        if name in self.fail:
            return subprocess.CompletedProcess(cmd, 1, "", f"{name} failed")
        out = ""
        rc = 0
        if name == "systemctl":
            out = f"@{self.broker_start}\n"
        elif name == "ip":
            out = json.dumps(
                [{"addr_info": [{"local": "192.0.2.1"}, {"local": "127.0.0.1"}]}]
            )
        elif cmd[:3] == ["nft", "list", "table"]:
            rc = 0 if self.table else 1
        elif cmd[:2] == ["nft", "-f"]:
            self.table = True
            assert stdin is not None
            for line in stdin.splitlines():
                if line.startswith("add element"):
                    set_name = line.split()[4]
                    body = line.split("{", 1)[1].rsplit("}", 1)[0]
                    for elem in body.split(","):
                        ip, _, secs = elem.split()
                        self.nft_sets.setdefault(set_name, {}).setdefault(
                            ip, int(secs[:-1])
                        )
        elif cmd[:3] == ["nft", "-j", "list"]:
            set_name = cmd[-1]
            if not self.table:
                rc = 1
            elems = [
                {"elem": {"val": ip, "timeout": t, "expires": t}}
                for ip, t in self.nft_sets.get(set_name, {}).items()
            ]
            out = json.dumps(
                {
                    "nftables": [
                        {"metainfo": {}},
                        {"set": {"name": set_name, "elem": elems}},
                    ]
                }
            )
        return subprocess.CompletedProcess(cmd, rc, out, "")

    def commands(self, prefix: str) -> list[list[str]]:
        """Return recorded commands starting with ``prefix``."""
        return [c for c, _ in self.calls if c[0] == prefix]


@pytest.fixture
def fake() -> FakeSystem:
    """Return a fresh fake system."""
    return FakeSystem()
