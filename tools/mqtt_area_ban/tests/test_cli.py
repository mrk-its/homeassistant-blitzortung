"""End-to-end tests of the command line on temporary logs and a fake system."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import BROKER_START, FakeSystem, connect, globe_client, ha_client, sub

from mqtt_area_ban.cli import (
    EXIT_BUSY,
    EXIT_OK,
    EXIT_STATE,
    System,
    main,
    parse_duration,
)
from mqtt_area_ban.state import load_state, state_lock

T = BROKER_START + 5
NOW = BROKER_START + 3600
TTL = 47 * 3600


class Env:
    """Paths, fake system and captured output for one test."""

    def __init__(self, tmp_path: Path, fake: FakeSystem) -> None:
        """Create an empty log next to the state file."""
        self.log = tmp_path / "mosquitto.log"
        self.state = tmp_path / "state" / "state.json"
        self.log.write_text("")
        self.fake = fake
        self.now = float(NOW)
        self.output: list[str] = []

    def write(self, text: str) -> None:
        """Append lines to the log."""
        with self.log.open("a") as f:
            f.write(text)

    def main(self, *args: str) -> int:
        """Run the CLI with this environment's paths."""
        command, *rest = args
        system = System(run=self.fake, now=lambda: self.now, out=self.output.append)
        return main(
            [command, "--log", str(self.log), "--state", str(self.state), *rest], system
        )

    @property
    def report(self) -> str:
        """Last report printed."""
        return self.output[-1]


@pytest.fixture
def env(tmp_path: Path, fake: FakeSystem) -> Env:
    """Build a log with these clients.

    Two whole-globe bots on one IP, a large-radius HA user next to a bot, a
    whole-globe HA-only user, a small HA user and a local client.
    """
    e = Env(tmp_path, fake)
    e.write(
        globe_client(
            BROKER_START - 100, "stale", "203.0.113.99"
        )  # before the broker start
        + globe_client(T, "botA1", "203.0.113.1")
        + globe_client(T, "botA2", "203.0.113.1")
        + ha_client(T, "ha-mixed", "203.0.113.2", cells=("u",))
        + globe_client(T, "botB", "203.0.113.2")
        + connect(T, "ha-big", "203.0.113.3")
        + sub(T, "ha-big", "component/hello")
        + sub(T, "ha-big", "blitzortung/1.1/#")
        + ha_client(T, "ha-small", "203.0.113.4")
        + globe_client(T, "local", "127.0.0.1")
    )
    return e


def _banned(fake: FakeSystem) -> set[str]:
    return set(fake.nft_sets.get("banned4", {}))


def test_parse_duration() -> None:
    """Units combine; garbage is rejected."""
    assert parse_duration("47h") == TTL
    assert parse_duration("1h30m") == 5400
    assert parse_duration("2d") == 172800
    with pytest.raises(Exception, match="invalid duration"):
        parse_duration("47 hours")


def test_report_changes_nothing(env: Env) -> None:
    """Report lists IPs but never calls nft or ss."""
    assert env.main("report") == EXIT_OK
    assert env.fake.commands("nft") == []
    assert env.fake.commands("ss") == []
    assert "203.0.113.99" not in env.report
    assert "203.0.113.1 " in env.report


def test_dry_run_changes_nothing(env: Env) -> None:
    """Run without --apply only reports."""
    assert env.main("run") == EXIT_OK
    assert env.fake.commands("nft") == []
    assert "would ban" in env.report
    assert load_state(env.state).bans == {}


def test_apply_bans_over_threshold(env: Env) -> None:
    """IPs at or over the threshold are banned, loopback is not."""
    assert env.main("run", "--apply", "--min-area", "1") == EXIT_OK
    assert _banned(env.fake) == {"203.0.113.1", "203.0.113.2", "203.0.113.3"}
    assert env.fake.nft_sets["banned4"]["203.0.113.1"] == TTL
    killed = {c[-1] for c in env.fake.commands("ss")}
    assert killed == {"203.0.113.1", "203.0.113.2", "203.0.113.3"}
    assert load_state(env.state).bans == dict.fromkeys(killed, int(NOW) + TTL)


def test_exclude_ha(env: Env) -> None:
    """--exclude-ha spares the HA-only IP but bans the bot next to an HA client."""
    assert env.main("run", "--apply", "--exclude-ha", "--min-area", "1") == EXIT_OK
    assert _banned(env.fake) == {"203.0.113.1", "203.0.113.2"}


def test_threshold(env: Env) -> None:
    """Only the IP with two whole-globe clients reaches 1.5 globes."""
    assert env.main("run", "--apply", "--min-area", "1.5") == EXIT_OK
    assert _banned(env.fake) == {"203.0.113.1"}


def test_allowlist(env: Env, tmp_path: Path) -> None:
    """Allowlisted networks are reported as allowed and never banned."""
    allow = tmp_path / "allow.txt"
    allow.write_text("203.0.113.0/31  # our relays\n")
    assert (
        env.main("run", "--apply", "--min-area", "1", "--allow", str(allow)) == EXIT_OK
    )
    assert _banned(env.fake) == {"203.0.113.2", "203.0.113.3"}
    assert "allowed" in env.report


def test_incremental_run_and_already_banned(env: Env) -> None:
    """A second run reads only new lines and doesn't re-ban."""
    env.main("run", "--apply", "--min-area", "1", "--exclude-ha")
    env.write(globe_client(T + 10, "newbot", "203.0.113.5"))
    env.fake.calls.clear()
    assert env.main("run", "--apply", "--min-area", "1", "--exclude-ha") == EXIT_OK
    assert {c[-1] for c in env.fake.commands("ss")} == {"203.0.113.5"}
    assert "already banned" in env.report


def test_broker_restart_drops_sessions(env: Env) -> None:
    """When systemd reports a newer start, sessions from the old run are forgotten."""
    env.main("report")
    env.fake.broker_start = T + 100
    env.write(globe_client(T + 200, "fresh", "203.0.113.6"))
    env.main("report", "--min-area", "1")
    assert set(load_state(env.state).sessions) == {"fresh"}


def test_ttl_expiry_and_restore(env: Env) -> None:
    """Restore re-adds unexpired bans with the remaining time, forgets the rest."""
    env.main("run", "--apply", "--min-area", "1.5")
    env.fake.nft_sets.clear()  # reboot
    env.fake.table = False
    env.now = NOW + 10 * 3600
    assert env.main("restore") == EXIT_OK
    assert env.fake.nft_sets["banned4"] == {"203.0.113.1": TTL - 10 * 3600}
    env.fake.nft_sets.clear()
    env.now = NOW + TTL + 1
    assert env.main("restore") == EXIT_OK
    assert load_state(env.state).bans == {}
    assert env.fake.nft_sets == {}


def test_expired_ban_is_banned_again(env: Env) -> None:
    """After the TTL the IP reconnects, shows up again and gets a fresh ban."""
    env.main("run", "--apply", "--min-area", "1.5")
    env.now = NOW + TTL + 1
    env.fake.nft_sets.clear()  # the kernel expired it
    env.write(globe_client(T + 10, "botA1", "203.0.113.1"))
    env.fake.calls.clear()
    env.main("run", "--apply", "--min-area", "1.5")
    assert env.fake.nft_sets["banned4"]["203.0.113.1"] == TTL


def test_corrupt_state_bans_nothing(env: Env) -> None:
    """An unreadable state file stops the run before any firewall change."""
    env.state.parent.mkdir(parents=True)
    env.state.write_text("{broken")
    assert env.main("run", "--apply") == EXIT_STATE
    assert env.fake.commands("nft") == []
    assert env.state.read_text() == "{broken"


def test_recover_rebuilds_from_logs_and_nft(env: Env) -> None:
    """--recover rebuilds sessions from the log and bans from the kernel sets."""
    env.state.parent.mkdir(parents=True)
    env.state.write_text("{broken")
    env.fake.table = True
    env.fake.nft_sets = {"banned4": {"198.51.100.7": 3600}}
    assert env.main("report", "--recover") == EXIT_OK
    state = load_state(env.state)
    assert state.bans == {"198.51.100.7": int(NOW) + 3600}
    assert "botA1" in state.sessions
    assert "stale" not in state.sessions


def test_lock_busy(env: Env) -> None:
    """A second concurrent run exits with the busy code."""
    env.state.parent.mkdir(parents=True)
    with state_lock(env.state.with_name("lock")):
        assert env.main("report") == EXIT_BUSY


def test_churning_client_is_banned_after_it_left(env: Env) -> None:
    """An IP whose sessions all ended before the run is still judged by its peak."""
    env.write(
        globe_client(T, "sht1", "203.0.113.7")
        + globe_client(T, "sht2", "203.0.113.7")
        + f"{T + 30}: Client sht1 closed its connection.\n"
        + f"{T + 31}: Client sht2 closed its connection.\n"
    )
    assert env.main("run", "--apply", "--min-area", "1.5") == EXIT_OK
    assert "203.0.113.7" in _banned(env.fake)
    assert load_state(env.state).peaks == {}


def test_dry_run_keeps_peaks(env: Env) -> None:
    """Only an applied run consumes the peaks."""
    env.write(
        globe_client(T, "x", "203.0.113.7") + f"{T + 1}: Client x disconnected.\n"
    )
    env.main("run")
    assert "203.0.113.7" in load_state(env.state).peaks


def test_missing_allowlist_warns_and_continues(
    env: Env, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A missing --allow file doesn't stop the run; nothing extra is allowed."""
    missing = tmp_path / "nope.txt"
    assert env.main("run", "--apply", "--min-area", "1.5", "--allow", str(missing)) == 0
    assert _banned(env.fake) == {"203.0.113.1"}
    assert "allowlist" in caplog.text
    assert "not found" in caplog.text
