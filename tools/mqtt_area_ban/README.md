# mqtt-area-ban

Bans IPs whose MQTT subscriptions on the Blitzortung broker cover a large part of the
globe. The tool reads mosquitto's log, adds up the area each IP watches, and drops port
1883 for IPs over a threshold through its own nftables table. Bans expire on their own.

## Requirements

- mosquitto logging `subscribe`, `unsubscribe` and `notice`, to a file:
  ```
  log_type subscribe
  log_type unsubscribe
  log_type notice
  ```
  `notice` gives the connect lines with the client's IP. Turn it on with
  `systemctl reload mosquitto`, then restart the broker once so that every connected
  client logs a connect line.
- Python 3.13 or later (stdlib only), `nft`, `ss` with `-K` (`CONFIG_INET_DIAG_DESTROY`),
  `systemctl`, and root.

## Area

Strikes are published on `blitzortung/1.1/<g1>/…/<g12>`, one geohash character per
level, and each character splits a cell into 32. A subscription to
`blitzortung/1.1/u/3/n/#` covers 32⁻³ of the globe. `blitzortung/1.1/#`, `blitzortung/#`
and `#` cover all of it. Filters that match no strike topic count as 0, for example
`blitzortung/1/#` or a filter with no trailing `#`. A filter nested inside another
filter of the same client counts once.

An IP's area is the **sum over its clients**, because the broker sends each client its
own copy. With `--exclude-ha`, Home Assistant clients (those subscribing to
`component/hello`) are left out. An IP with an HA client next to a large non-HA client is
judged on the non-HA client alone.

The decision uses the larger of two numbers: the IP's area right now, and the **peak** it
reached since the last applied run. The peak is measured just before each session ends,
because some clients reconnect every minute under a new ID and are rarely connected at
the moment the daily run looks.

## Usage

```
mqtt-area-ban report [--min-area 0.5] [--exclude-ha] [--allow FILE] [--limit 50]
mqtt-area-ban run    [same options] [--ttl 47h] [--apply]
mqtt-area-ban restore
common: --log /var/log/mosquitto/mosquitto.log --state /var/lib/mqtt-area-ban/state.json
        --port 1883 --unit mosquitto --bootstrap --recover -v
```

- `report` prints a table: IP, peak and live area in globes, clients, HA clients, action
  and client ID families. It never touches the firewall.
- `run` without `--apply` is a dry run.
- `run --apply` adds the IPs over the threshold to the set with a timeout of `--ttl` and
  resets their open connections with `ss -K`. Then it clears the peaks.
- `restore` re-adds unexpired bans after a reboot, with their remaining time.
- `--allow FILE` takes one IP or CIDR per line, with `#` comments. Loopback and the
  host's own addresses are always allowed.
  A missing file logs a warning and the run goes on. `deploy/allow.txt` is installed
  as `/etc/mqtt-area-ban/allow.txt`, and the cron run uses it. It's kept out of git:
  copy `deploy/allow.txt.example` to start. Without it, `tools/deploy.sh` keeps the
  server's file, or installs the example on a first deploy.

Without `python -m pip install`, run it as `PYTHONPATH=/opt/mqtt-area-ban python3 -m mqtt_area_ban …`.

## Firewall

```
table inet mqtt_area_ban {
  set banned4 { type ipv4_addr; flags timeout; }
  set banned6 { type ipv6_addr; flags timeout; }
  chain input { type filter hook input priority filter - 10; policy accept;
    tcp dport 1883 ip saddr @banned4 drop
    tcp dport 1883 ip6 saddr @banned6 drop }
}
```

To see the bans: `nft list set inet mqtt_area_ban banned4`. To lift one early:
`nft delete element inet mqtt_area_ban banned4 { 203.0.113.7 }`, and also remove it from
`bans` in the state file, or `restore` will add it back. To lift all of them:
`nft delete table inet mqtt_area_ban` and delete `bans` from the state file.

## TTL and schedule

The kernel expires each ban. A banned IP can't connect, so the tool doesn't see it
while banned. Once the ban expires, the client reconnects. If it still watches a large
area, the next run bans it again. If it never comes back, it drops off.

Set the TTL **a bit shorter than a multiple of the run interval**. With a daily run and
`--ttl 47h`, a ban ends one hour before the run two days later, so that run sees the
client reconnect. With exactly 48h, the IP could get almost a day of traffic before the
next run. Clients that wait longer before reconnecting need a bigger margin.

`deploy/mqtt-area-ban.cron` runs at 12:00. Logrotate runs between 00:00 and 01:00 UTC,
so at most one rotation happens between two runs. If two rotations do happen, the tool
finds its place in `mosquitto.log.2.gz` by the file's first bytes.

## State file

`/var/lib/mqtt-area-ban/state.json` holds the live sessions, the log position, the
peaks and the bans. It is written atomically (temp file, fsync, rename), and the
previous version is kept as `state.json.bak`. A lock file stops two runs from
overlapping.

If the state file can't be read, the tool exits with code 2 and bans nothing.
`--recover` rebuilds it: sessions come from all log files since the broker start, and
bans from the nftables sets.

Exit codes: 0 ok, 1 a command failed, 2 bad state file, 3 another run is active.

## Tests

```sh
cd tools/mqtt_area_ban
../../venv/bin/pytest
../../venv/bin/ruff check . && ../../venv/bin/ruff format --check .
```
