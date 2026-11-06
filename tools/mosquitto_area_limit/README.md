# mosquitto_area_limit

A mosquitto plugin that refuses subscriptions covering too much of the globe. It runs
on the Blitzortung broker and stops anonymous clients from taking the whole strike feed
with one subscription such as `#` or `blitzortung/1.1/#`.

Strikes are published with one geohash character per topic level, for example
`blitzortung/1.1/u/3/n/x/b/2/…` or `b/1/u/3/n/x/b/2`. The number of geohash characters a
subscription fixes decides how much of the globe it receives: each character narrows it
to 1/32. The plugin refuses a subscription that fixes too few of them.

## What it does

The plugin only looks at **SUBSCRIBE requests from anonymous clients** (no username):

1. If the client ID starts with one of `deny_client_prefixes`, every subscription is
   refused.
2. If the filter would receive strikes from a configured feed (`roots`) while fixing
   fewer than `min_levels` geohash characters, the subscription is refused. A `+` level
   doesn't count as fixed.
3. Anything else is passed on to mosquitto's other checks. The `acl_file` still decides
   as before.

The plugin doesn't restrict authenticated clients, message delivery or publishing.

With `roots blitzortung/1.1,b/1` and `min_levels 1`:

| Filter | Result |
|---|---|
| `#`, `+/#`, `blitzortung/#`, `blitzortung/+/#`, `b/#` | refused |
| `blitzortung/1.1/#`, `blitzortung/1.1/+/#`, `blitzortung/1.1/+/+/#`, `b/1/#` | refused |
| `blitzortung/1.1/u/#`, `blitzortung/1.1/+/3/#`, `b/1/u/3/n/#` | allowed |
| `$SYS/#`, `component/hello`, anything outside the roots | allowed (not handled) |
| anything, from client ID `fae-relay-3f2f0fea` | refused |
| anything, from the `blitzortung` user | allowed (authenticated) |

A refused filter gets return code 0x80 in the SUBACK. The client stays connected, and its
other filters in the same request are judged on their own. Mosquitto doesn't write a
subscribe log line for a refused filter.

## Requirements

- Mosquitto 2.0 or later (plugin interface version 5). Built and tested with 2.0.22.
- The broker and client headers (Debian and Ubuntu packages):
  ```sh
  sudo apt-get install mosquitto-dev libmosquitto-dev
  ```
  `mosquitto-dev` provides `mosquitto_broker.h` and `mosquitto_plugin.h`.
  `libmosquitto-dev` provides `mosquitto.h`.
- gcc.

## Build

```sh
gcc -Wall -Wextra -Werror -O2 -fPIC -shared \
    -o mosquitto_area_limit.so mosquitto_area_limit.c
```

Build against the headers of the mosquitto version that will load the plugin, and
rebuild after a mosquitto upgrade.

## Install

```sh
sudo install -o root -g root -m 0644 mosquitto_area_limit.so \
    /usr/lib/x86_64-linux-gnu/mosquitto_area_limit.so
sudo install -o root -g root -m 0644 area_limit.conf /etc/mosquitto/conf.d/area_limit.conf
sudo systemctl restart mosquitto
```

- **Location of the `.so`:** Ubuntu confines mosquitto with AppArmor
  (`/etc/apparmor.d/mosquitto`). The profile lets it load libraries from
  `/usr/lib/x86_64-linux-gnu/`, where the dynamic security plugin also lives, but not
  from `/opt` or `/tmp`. A plugin there fails to load with a permission error. Check `journalctl -k | grep apparmor`.
- **Restart, not reload:** mosquitto loads plugins only at startup ("Not currently
  reloaded on reload signal"). A restart disconnects every client; on the Blitzortung
  broker the ~20,000 clients reconnect within about a minute. This applies to option
  changes too.
- **`tools/deploy.sh`** does the build and install on the broker host. It keeps the
  source in `/opt/mosquitto-area-limit` and never restarts mosquitto: it says when the
  plugin or its options changed and a restart is needed.

## Configuration

The options go in a mosquitto config file, here `/etc/mosquitto/conf.d/area_limit.conf`:

```
plugin /usr/lib/x86_64-linux-gnu/mosquitto_area_limit.so
plugin_opt_roots blitzortung/1.1,b/1
plugin_opt_min_levels 1
plugin_opt_deny_client_prefixes fae-relay
```

| Option | Required | Default | Meaning |
|---|---|---|---|
| `plugin_opt_roots` | yes | – | Comma-separated topic roots of the strike feeds. A geohash character follows the root at each level. At most 8. |
| `plugin_opt_min_levels` | no | `1` | Smallest number of geohash characters an anonymous filter must fix under a root. `0` turns the area check off. |
| `plugin_opt_deny_client_prefixes` | no | none | Comma-separated client ID prefixes whose subscriptions are all refused. At most 16. Prefixes are case-sensitive. |

Format details:
- Lists are separated by commas only. Spaces are kept as part of the value, so write
  `blitzortung/1.1,b/1`, not `blitzortung/1.1, b/1`.
- An unknown `plugin_opt_…` key, a missing `roots`, or too many entries stop the plugin
  from loading, and mosquitto then refuses to start. The reason is in the mosquitto log
  as an `area_limit:` error.
- `plugin_opt_…` lines apply to the `plugin` line above them. Keep them together in one
  file.

Choosing `min_levels`: each level is 32 times smaller than the one above.

| `min_levels` | Largest allowed cell (equator) | Effect on Home Assistant users |
|---|---|---|
| 1 | ~5,000 × 5,000 km (1/32 of the globe) | none: the integration never subscribes at level 0 |
| 2 | ~1,250 × 625 km | breaks the ~10% of users whose radius gives level-1 or level-2 cells |

## Logs

With `log_type notice`, the plugin logs its settings at startup and each refusal:

```
area_limit: 2 roots, min_levels 1, 1 denied client prefixes
area_limit: refused blitzortung/1.1/# for client auto-1A2B… (area)
area_limit: refused blitzortung/1.1/u/# for client fae-relay-3f2f0fea (client id)
```

```sh
sudo grep -c "area_limit: refused" /var/log/mosquitto/mosquitto.log
```

## Check after a change

```sh
# refused: prints "All subscription requests were denied."
mosquitto_sub -h localhost -t 'blitzortung/1.1/#' -C 1 -W 5
# allowed: prints strikes when there are any over Europe
mosquitto_sub -h localhost -t 'blitzortung/1.1/u/#' -C 1 -W 60
```

## Remove

```sh
sudo rm /etc/mosquitto/conf.d/area_limit.conf
sudo systemctl restart mosquitto
```

The `.so` can stay: it does nothing unless a config file loads it.

## Limits

- Filters longer than 1,023 characters or deeper than 32 levels aren't checked.
- The client ID check only stops subscriptions. A denied client can still connect and
  stay connected. To keep it off the broker entirely, ban its IP (see
  `tools/mqtt_area_ban`).
- A client can still cover a large area with many narrower filters, for example all 32
  level-1 cells. `tools/mqtt_area_ban` adds up such subscriptions per IP and bans the
  large ones.
