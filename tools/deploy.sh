#!/usr/bin/env bash
# (Re)deploy the broker-side tools to the broker host:
#
#   mqtt-area-ban         -> /opt/mqtt-area-ban, /etc/cron.d/mqtt-area-ban,
#                            /etc/mqtt-area-ban/allow.txt
#   mosquitto_area_limit  -> source in /opt/mosquitto-area-limit, built there into
#                            /usr/lib/x86_64-linux-gnu/mosquitto_area_limit.so,
#                            config in /etc/mosquitto/conf.d/area_limit.conf
#
#   tools/deploy.sh [host]            # default host: zrodlana.ha.sed.pl
#   SKIP_TESTS=1 tools/deploy.sh      # skip the local test run
#
# The plugin is built before anything is replaced, so a build failure changes nothing.
# Directories are swapped in with one rename, so cron never runs a half-copied tree.
# Mosquitto is never restarted: plugins load only on restart, so when the plugin or its
# config changed the script says so and leaves the restart to you. The mqtt-area-ban
# state in /var/lib/mqtt-area-ban and the nftables bans are left alone.
set -euo pipefail

HOST=${1:-zrodlana.ha.sed.pl}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$HERE/.." && pwd)

if [[ -z ${SKIP_TESTS:-} ]]; then
    echo "== local checks"
    (cd "$HERE/mqtt_area_ban" && "$REPO/venv/bin/pytest" -q -p no:cacheprovider)
    (cd "$HERE/mqtt_area_ban" && "$REPO/venv/bin/ruff" check --no-cache . \
        && "$REPO/venv/bin/ruff" format --no-cache --check .)
fi

# Runs on the host; both directories arrive as one tarball on stdin.
read -r -d '' REMOTE <<'EOF' || true
set -euo pipefail
STAGE=$(mktemp -d)
trap 'sudo rm -rf "$STAGE"' EXIT
tar -xzf - -C "$STAGE"

PKG=/opt/mqtt-area-ban
CRON=/etc/cron.d/mqtt-area-ban
SRC=/opt/mosquitto-area-limit
SO=/usr/lib/x86_64-linux-gnu/mosquitto_area_limit.so
PCONF=/etc/mosquitto/conf.d/area_limit.conf

swap_dir() {  # swap_dir <staged dir> <destination>
    sudo rm -rf "$2.new" "$2.old"
    sudo cp -r "$1" "$2.new"
    sudo chown -R root:root "$2.new"
    if [[ -d $2 ]]; then sudo mv "$2" "$2.old"; fi
    sudo mv "$2.new" "$2"
    sudo rm -rf "$2.old"
}

options() {  # options <file>: the lines mosquitto acts on
    sudo grep -vE '^[[:space:]]*(#|$)' "$1" 2>/dev/null || true
}

install_file() {  # install_file <src> <dest>: atomic, root 0644; prints "changed" if it did
    if sudo cmp -s "$1" "$2"; then return; fi
    sudo install -o root -g root -m 0644 "$1" "$2.tmp"
    sudo mv "$2.tmp" "$2"
    echo changed
}

echo "== building mosquitto_area_limit"
(cd "$STAGE/mosquitto_area_limit" \
    && gcc -Wall -Wextra -Werror -O2 -fPIC -shared \
        -o mosquitto_area_limit.so mosquitto_area_limit.c)

# Refuse to switch to a tree that doesn't even start.
(cd /tmp && sudo PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$STAGE/mqtt_area_ban" \
    python3 -m mqtt_area_ban --help >/dev/null)

echo "== mqtt-area-ban"
swap_dir "$STAGE/mqtt_area_ban" "$PKG"
sudo install -d -o root -g root -m 0755 /etc/mqtt-area-ban
# allow.txt is kept out of git; without it, keep the server's copy, or start from the
# example so the cron job's --allow always points at a file.
ALLOW=/etc/mqtt-area-ban/allow.txt
if [[ -f $PKG/deploy/allow.txt ]]; then
    install_file "$PKG/deploy/allow.txt" "$ALLOW" >/dev/null
elif [[ -f $ALLOW ]]; then
    echo "no deploy/allow.txt in this checkout, keeping $ALLOW"
else
    install_file "$PKG/deploy/allow.txt.example" "$ALLOW" >/dev/null
    echo "no deploy/allow.txt in this checkout, installed the example as $ALLOW"
fi
# cron skips files in /etc/cron.d that aren't root-owned 0644 or have a dot in the name.
install_file "$PKG/deploy/mqtt-area-ban.cron" "$CRON" >/dev/null
echo "installed $PKG"
echo "allowlist $ALLOW:"
options "$ALLOW" | sed 's/^/  /'
[[ -n $(options "$ALLOW") ]] || echo "  (empty: only loopback and the host's own addresses)"
echo "cron entries in $CRON:"
grep -vE '^[[:space:]]*(#|$)' "$CRON" | sed 's/^/  /'

echo "== mosquitto_area_limit"
mv "$STAGE/mosquitto_area_limit/mosquitto_area_limit.so" "$STAGE/plugin.so"
swap_dir "$STAGE/mosquitto_area_limit" "$SRC"
# Renaming over the .so is safe while mosquitto runs: it keeps the old file mapped.
so_changed=$(install_file "$STAGE/plugin.so" "$SO")
conf_changed=
if [[ $(options "$SRC/area_limit.conf") != $(options "$PCONF") ]]; then conf_changed=changed; fi
install_file "$SRC/area_limit.conf" "$PCONF" >/dev/null
echo "source in $SRC, plugin $SO, config $PCONF"
if [[ -n $so_changed$conf_changed ]]; then
    echo "!! the plugin${so_changed:+ binary}${conf_changed:+ config} changed:" \
        "it takes effect after 'sudo systemctl restart mosquitto' (drops all clients for ~1 min)"
else
    echo "plugin and config unchanged, no restart needed"
fi
EOF

echo "== deploying to $HOST"
tar -C "$HERE" --exclude=__pycache__ --exclude=.pytest_cache --exclude=.ruff_cache \
    -czf - mqtt_area_ban mosquitto_area_limit |
    ssh -o BatchMode=yes "$HOST" "bash -c $(printf '%q' "$REMOTE")"
