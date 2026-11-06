"""Command line: report large-area IPs, ban them in nftables, restore after reboot."""

from __future__ import annotations

import argparse
import ipaddress
import logging
import re
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .area import IpUsage, feed_summary, ip_usage
from .logfiles import LogFollower, NeedsReplayError
from .logparse import parse_line
from .nft import (
    CommandError,
    Firewall,
    Runner,
    broker_start,
    default_runner,
    host_addresses,
    parse_allowlist,
)
from .state import LockBusyError, State, StateError, load_state, save_state, state_lock

_LOGGER = logging.getLogger("mqtt_area_ban")
_DURATION = re.compile(r"(\d+)([smhd])")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
ALWAYS_ALLOWED = [ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("::1/128")]

EXIT_OK, EXIT_ERROR, EXIT_STATE, EXIT_BUSY = 0, 1, 2, 3


@dataclass
class System:
    """Everything that touches the machine, replaceable in tests."""

    run: Runner = default_runner
    now: Callable[[], float] = time.time
    out: Callable[[str], object] = field(default=sys.stdout.write)


def parse_duration(text: str) -> int:
    """Seconds in a duration like ``47h``, ``90m``, ``2d`` or ``1h30m``."""
    parts = _DURATION.findall(text)
    if not parts or "".join(n + u for n, u in parts) != text:
        raise argparse.ArgumentTypeError(
            f"invalid duration {text!r}, use e.g. 47h, 90m, 2d"
        )
    return sum(int(n) * _UNIT_SECONDS[u] for n, u in parts)


def build_parser() -> argparse.ArgumentParser:
    """Argument parser with the report, run and restore subcommands."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--log", type=Path, default=Path("/var/log/mosquitto/mosquitto.log")
    )
    common.add_argument(
        "--state", type=Path, default=Path("/var/lib/mqtt-area-ban/state.json")
    )
    common.add_argument("--port", type=int, default=1883)
    common.add_argument(
        "--unit", default="mosquitto", help="systemd unit of the broker"
    )
    common.add_argument("-v", "--verbose", action="store_true")

    scan = argparse.ArgumentParser(add_help=False)
    scan.add_argument(
        "--min-area",
        type=float,
        default=0.5,
        help="ban IPs whose clients watch at least this many globes (default 0.5)",
    )
    scan.add_argument(
        "--exclude-ha",
        action="store_true",
        help="ignore Home Assistant clients (those subscribing to component/hello)",
    )
    scan.add_argument(
        "--allow", type=Path, help="file with IPs/CIDRs that are never banned"
    )
    scan.add_argument(
        "--limit", type=int, default=50, help="rows in the report (0 = all)"
    )
    scan.add_argument(
        "--bootstrap",
        action="store_true",
        help="rebuild sessions from all log files since the broker start",
    )
    scan.add_argument(
        "--recover",
        action="store_true",
        help="ignore an unreadable state file: rebuild it from the logs and nft",
    )

    parser = argparse.ArgumentParser(prog="mqtt-area-ban", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "report", parents=[common, scan], help="show large-area IPs, change nothing"
    )
    run = sub.add_parser("run", parents=[common, scan], help="ban large-area IPs")
    run.add_argument("--ttl", type=parse_duration, default=parse_duration("47h"))
    run.add_argument(
        "--apply", action="store_true", help="change the firewall (default: dry run)"
    )
    sub.add_parser(
        "restore", parents=[common], help="re-add unexpired bans after a reboot"
    )
    return parser


def _feed(state: State, lines: Iterable[str]) -> None:
    for line in lines:
        if event := parse_line(line):
            state.apply(event)


def refresh_sessions(state: State, args: argparse.Namespace, system: System) -> None:
    """Bring sessions up to date with the log since the last run."""
    start = broker_start(system.run, args.unit)
    follower = LogFollower(args.log)
    replay = args.bootstrap or args.recover or state.cursor is None
    if not replay and state.broker_start != start:
        _LOGGER.info("broker restarted, dropping %d sessions", len(state.sessions))
        state.reset_sessions(start)
    if not replay and state.cursor is not None:
        try:
            _feed(state, follower.incremental(state.cursor))
        except NeedsReplayError as err:
            _LOGGER.warning("%s; rebuilding sessions from all logs", err)
            replay = True
    if replay:
        state.reset_sessions(start)
        _feed(state, follower.replay(start))
    state.cursor = follower.cursor


@dataclass
class Decision:
    """What to do with one IP."""

    ip: str
    usage: IpUsage
    action: str


def decide(
    usage: dict[str, IpUsage],
    min_area: float,
    allowed: Sequence[ipaddress.IPv4Network | ipaddress.IPv6Network],
    banned: Iterable[str],
    apply: bool,
) -> list[Decision]:
    """Classify IPs with a non-zero area, largest area first."""
    banned = set(banned)
    decisions = []
    for ip, entry in sorted(usage.items(), key=lambda kv: -kv[1].score):
        if entry.score <= 0:
            continue
        address = ipaddress.ip_address(ip)
        if entry.score < min_area:
            action = "below threshold"
        elif any(address in net for net in allowed):
            action = "allowed"
        elif ip in banned:
            action = "already banned"
        else:
            action = "ban" if apply else "would ban"
        decisions.append(Decision(ip, entry, action))
    return decisions


def render(decisions: list[Decision], state: State, limit: int) -> str:
    """Report table plus a one-line summary."""
    header = (
        f"{'IP':<39} {'peak':>7} {'live':>7} {'clients':>7} {'HA':>3}"
        f"  {'action':<15} families"
    )
    rows = [header]
    for d in decisions[: limit or None]:
        top = d.usage.families.most_common(3)
        families = ", ".join(f"{k} x{v}" for k, v in top)
        rows.append(
            f"{d.ip:<39} {d.usage.score:7.3f} {d.usage.area:7.3f}"
            f" {d.usage.clients:7d} {d.usage.ha_clients:3d}"
            f"  {d.action:<15} {families}"
        )
    ips = {s.ip for s in state.sessions.values()}
    acting = sum(1 for d in decisions if d.action in ("ban", "would ban"))
    rows.append(
        f"\n{len(state.sessions)} sessions, {len(ips)} IPs, "
        f"{len(decisions)} with strike area, {acting} to ban, "
        f"{len(state.bans)} bans active"
    )
    rows.append(feed_summary(state.sessions))
    return "\n".join(rows) + "\n"


def restore_bans(state: State, firewall: Firewall, now: float) -> None:
    """Re-add unexpired bans with their remaining time; IPs still in the set stay."""
    state.drop_expired_bans(now)
    firewall.ensure_table()
    firewall.add({ip: int(exp - now) for ip, exp in state.bans.items()})


def _allowed(
    args: argparse.Namespace, system: System
) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    allowed: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = list(ALWAYS_ALLOWED)
    allowed += [ipaddress.ip_network(ip) for ip in host_addresses(system.run)]
    if args.allow:
        try:
            lines = args.allow.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            _LOGGER.warning("allowlist %s not found, using none", args.allow)
        else:
            allowed += parse_allowlist(lines)
    return allowed


def usage_with_peaks(state: State, exclude_ha: bool) -> dict[str, IpUsage]:
    """Live usage per IP, plus IPs whose sessions ended since the last applied run."""
    usage = ip_usage(state.sessions, exclude_ha)
    for ip, peak in state.peaks.items():
        entry = usage.setdefault(ip, IpUsage())
        entry.peak = peak.non_ha if exclude_ha else peak.all
        if not entry.families:
            entry.families = Counter(peak.families)
    return usage


def _load(args: argparse.Namespace, firewall: Firewall, system: System) -> State:
    if not getattr(args, "recover", False):
        return load_state(args.state)
    now = system.now()
    return State(
        bans={ip: int(now) + left for ip, left in firewall.list_banned().items()}
    )


def cmd_scan(args: argparse.Namespace, system: System) -> int:
    """``report`` and ``run``: update sessions, decide, and ban if ``--apply``."""
    firewall = Firewall(system.run, args.port)
    state = _load(args, firewall, system)
    refresh_sessions(state, args, system)
    now = system.now()
    state.drop_expired_bans(now)
    apply = args.command == "run" and args.apply
    decisions = decide(
        usage_with_peaks(state, args.exclude_ha),
        args.min_area,
        _allowed(args, system),
        state.bans,
        apply=apply,
    )
    if apply:
        restore_bans(state, firewall, now)
        new = [d.ip for d in decisions if d.action == "ban"]
        firewall.add(dict.fromkeys(new, args.ttl))
        for ip in new:
            state.bans[ip] = int(now) + args.ttl
            try:
                firewall.kill_connections(ip)
            except CommandError as err:
                _LOGGER.warning("%s", err)
        state.peaks.clear()
        _LOGGER.info("banned %d IPs for %ds", len(new), args.ttl)
    system.out(render(decisions, state, args.limit))
    save_state(args.state, state)
    return EXIT_OK


def cmd_restore(args: argparse.Namespace, system: System) -> int:
    """``restore``: put unexpired bans back into nftables."""
    state = load_state(args.state)
    restore_bans(state, Firewall(system.run, args.port), system.now())
    save_state(args.state, state)
    _LOGGER.info("restored %d bans", len(state.bans))
    return EXIT_OK


def main(argv: Sequence[str] | None = None, system: System | None = None) -> int:
    """Run one command; exit 1 = command failed, 2 = bad state, 3 = another run."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
        stream=sys.stderr,
    )
    system = system or System()
    command = cmd_restore if args.command == "restore" else cmd_scan
    try:
        with state_lock(args.state.with_name("lock")):
            return command(args, system)
    except LockBusyError as err:
        _LOGGER.error("%s", err)
        return EXIT_BUSY
    except StateError as err:
        _LOGGER.error(
            "%s; nothing was banned. Rerun with --recover to rebuild it.", err
        )
        return EXIT_STATE
    except (CommandError, OSError) as err:
        _LOGGER.error("%s", err)
        return EXIT_ERROR
