"""Tests for the nftables wrapper."""

import pytest
from conftest import BROKER_START, FakeSystem

from mqtt_area_ban.nft import (
    CommandError,
    Firewall,
    broker_start,
    host_addresses,
    parse_allowlist,
    table_definition,
)


def test_table_definition_uses_port() -> None:
    """Both families get a timeout set and a drop rule for the broker port."""
    text = table_definition(1883)
    assert "set banned4 { type ipv4_addr; flags timeout; }" in text
    assert "set banned6 { type ipv6_addr; flags timeout; }" in text
    assert "tcp dport 1883 ip saddr @banned4 drop" in text
    assert "tcp dport 1883 ip6 saddr @banned6 drop" in text


def test_ensure_table_is_idempotent(fake: FakeSystem) -> None:
    """The table is loaded once; later calls only check it exists."""
    fw = Firewall(fake, 1883)
    fw.ensure_table()
    fw.ensure_table()
    loads = [c for c, _ in fake.calls if c[:2] == ["nft", "-f"]]
    assert len(loads) == 1


def test_add_splits_families(fake: FakeSystem) -> None:
    """IPv4 and IPv6 go to their own sets in one nft script."""
    Firewall(fake, 1883).add({"203.0.113.5": 3600, "2001:db8::1": 60, "203.0.113.4": 0})
    script = next(stdin for c, stdin in fake.calls if c[:2] == ["nft", "-f"])
    assert script == (
        "add element inet mqtt_area_ban banned4"
        " { 203.0.113.4 timeout 1s, 203.0.113.5 timeout 3600s }\n"
        "add element inet mqtt_area_ban banned6 { 2001:db8::1 timeout 60s }\n"
    )


def test_add_nothing_runs_nothing(fake: FakeSystem) -> None:
    """An empty ban list doesn't call nft."""
    Firewall(fake, 1883).add({})
    assert fake.calls == []


def test_list_banned(fake: FakeSystem) -> None:
    """Remaining seconds come from the sets; a missing table means nothing is banned."""
    fw = Firewall(fake, 1883)
    assert fw.list_banned() == {}
    fake.table = True
    fake.nft_sets = {"banned4": {"203.0.113.5": 100}, "banned6": {"2001:db8::1": 7}}
    assert fw.list_banned() == {"203.0.113.5": 100, "2001:db8::1": 7}


def test_kill_connections(fake: FakeSystem) -> None:
    """The ss -K call is limited to the broker port and the IP."""
    Firewall(fake, 1883).kill_connections("203.0.113.5")
    assert " ".join(fake.calls[0][0]) == (
        "ss -K -tn state established ( sport = :1883 ) dst 203.0.113.5"
    )


def test_nft_failure_raises(fake: FakeSystem) -> None:
    """A failing nft command is an error, not a silent no-op."""
    fake.fail.add("nft")
    with pytest.raises(CommandError):
        Firewall(fake, 1883).ensure_table()


def test_broker_start(fake: FakeSystem) -> None:
    """The systemd timestamp is parsed; an inactive unit is an error."""
    assert broker_start(fake, "mosquitto") == BROKER_START
    with pytest.raises(CommandError):
        broker_start(lambda _cmd, _stdin=None: fake(["true"]), "mosquitto")


def test_host_addresses(fake: FakeSystem) -> None:
    """Addresses come from ip -j addr; a failure yields none."""
    assert host_addresses(fake) == {"192.0.2.1", "127.0.0.1"}
    fake.fail.add("ip")
    assert host_addresses(fake) == set()


def test_parse_allowlist() -> None:
    """Comments and blank lines are skipped, hosts become /32."""
    nets = parse_allowlist(
        ["# relays", "203.0.113.5", "", "198.51.100.0/24  # office", "2001:db8::/32"]
    )
    assert [str(n) for n in nets] == [
        "203.0.113.5/32",
        "198.51.100.0/24",
        "2001:db8::/32",
    ]
