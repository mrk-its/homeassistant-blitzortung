"""The tool's own nftables table, and the system commands around it."""

from __future__ import annotations

import ipaddress
import json
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass

TABLE = "mqtt_area_ban"
SETS = {4: "banned4", 6: "banned6"}

Runner = Callable[[list[str], str | None], subprocess.CompletedProcess[str]]


def default_runner(
    cmd: list[str], stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a command, capturing text output; failures are reported, not raised."""
    return subprocess.run(cmd, input=stdin, text=True, capture_output=True, check=False)  # noqa: S603


class CommandError(Exception):
    """A system command failed."""


def _check(result: subprocess.CompletedProcess[str], cmd: list[str]) -> str:
    if result.returncode != 0:
        raise CommandError(
            f"{' '.join(cmd)} failed ({result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout


def table_definition(port: int) -> str:
    """Table with a timeout set per address family and drop rules for the port."""
    return f"""table inet {TABLE} {{
  set {SETS[4]} {{ type ipv4_addr; flags timeout; }}
  set {SETS[6]} {{ type ipv6_addr; flags timeout; }}
  chain input {{
    type filter hook input priority filter - 10; policy accept;
    tcp dport {port} ip saddr @{SETS[4]} drop
    tcp dport {port} ip6 saddr @{SETS[6]} drop
  }}
}}
"""


@dataclass
class Firewall:
    """Bans IPs from the broker port through the ``inet mqtt_area_ban`` table."""

    run: Runner
    port: int

    def ensure_table(self) -> None:
        """Create the table if it's missing (nft state doesn't survive a reboot)."""
        if self.run(["nft", "list", "table", "inet", TABLE], None).returncode == 0:
            return
        cmd = ["nft", "-f", "-"]
        _check(self.run(cmd, table_definition(self.port)), cmd)

    def add(self, bans: dict[str, int]) -> None:
        """Add IPs with a timeout in seconds; IPs already in a set keep theirs."""
        by_family: dict[int, list[str]] = {4: [], 6: []}
        for ip, seconds in sorted(bans.items()):
            by_family[ipaddress.ip_address(ip).version].append(
                f"{ip} timeout {max(seconds, 1)}s"
            )
        script = "".join(
            f"add element inet {TABLE} {SETS[family]} {{ {', '.join(elems)} }}\n"
            for family, elems in by_family.items()
            if elems
        )
        if script:
            cmd = ["nft", "-f", "-"]
            _check(self.run(cmd, script), cmd)

    def list_banned(self) -> dict[str, int]:
        """IPs in the sets with remaining seconds; empty if there is no table."""
        banned: dict[str, int] = {}
        for name in SETS.values():
            result = self.run(["nft", "-j", "list", "set", "inet", TABLE, name], None)
            if result.returncode != 0:
                continue
            for item in json.loads(result.stdout).get("nftables", []):
                for elem in item.get("set", {}).get("elem", []):
                    if isinstance(elem, dict) and "elem" in elem:
                        banned[str(elem["elem"]["val"])] = int(
                            elem["elem"].get("expires", 0)
                        )
        return banned

    def kill_connections(self, ip: str) -> None:
        """Reset the IP's connections so mosquitto drops its sessions at once."""
        cmd = [
            "ss",
            "-K",
            "-tn",
            "state",
            "established",
            "(",
            "sport",
            "=",
            f":{self.port}",
            ")",
        ]
        _check(self.run([*cmd, "dst", ip], None), cmd)


def broker_start(run: Runner, unit: str) -> int:
    """Epoch second the broker's systemd unit last became active."""
    cmd = [
        "systemctl",
        "show",
        "--timestamp=unix",
        "--value",
        "-p",
        "ActiveEnterTimestamp",
        unit,
    ]
    value = _check(run(cmd, None), cmd).strip()
    if not value.startswith("@"):
        raise CommandError(f"{unit} has no start time ({value!r}); is it running?")
    return int(value[1:])


def host_addresses(run: Runner) -> set[str]:
    """Addresses of this machine, so the tool never bans the server itself."""
    result = run(["ip", "-j", "addr"], None)
    if result.returncode != 0:
        return set()
    return {
        info["local"]
        for link in json.loads(result.stdout)
        for info in link.get("addr_info", [])
        if "local" in info
    }


def parse_allowlist(
    lines: Iterable[str],
) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Networks from an allowlist: one IP or CIDR per line, '#' comments."""
    networks = []
    for raw in lines:
        entry = raw.split("#", 1)[0].strip()
        if entry:
            networks.append(ipaddress.ip_network(entry, strict=False))
    return networks
