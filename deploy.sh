#!/bin/sh
# Deploy the publisher to a host that runs it (e.g. HA OS via the Terminal & SSH add-on).
#
#   ./deploy.sh root@ha-host                    # -> /config/scripts/pylontech + /config/packages/pylontech.yaml
#   ./deploy.sh root@ha-host /opt/pylontech ""  # other target dir, no HA package
#   SSH_OPTS="-i ~/.ssh/key -p 22" ./deploy.sh ...
#   ./deploy.sh --stage DIR                     # only build the deploy tree locally
#
# Copies run.py, pylontech_ha/ and the pylontech_rs485 library from the submodule.
# Never touches config.ini, the MQTT password file or history.json on the target.
set -eu
cd "$(dirname "$0")"

LIB=lib/pylontech-rs485/src/pylontech_rs485
[ -f "$LIB/protocol.py" ] || { echo "submodule missing: git submodule update --init" >&2; exit 1; }

stage() {
    d="$1"; mkdir -p "$d/pylontech_ha" "$d/pylontech_rs485"
    cp run.py config.example.ini "$d/"
    cp pylontech_ha/*.py "$d/pylontech_ha/"
    cp "$LIB"/*.py "$d/pylontech_rs485/"
    { echo "pylontech-ha $(git describe --always --dirty 2>/dev/null || echo unknown)"
      echo "pylontech-rs485 $(git -C lib/pylontech-rs485 describe --tags --always --dirty 2>/dev/null || echo unknown)"
    } > "$d/VERSION"
}

if [ "${1:-}" = "--stage" ]; then stage "${2:?dir}"; echo "staged in $2"; exit 0; fi

TARGET="${1:?usage: deploy.sh user@host [remote_dir] [package_dir]}"
DIR="${2:-/config/scripts/pylontech}"
PKG="${3-/config/packages}"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
stage "$TMP/p"
# shellcheck disable=SC2086
tar -C "$TMP/p" -czf - . | ssh ${SSH_OPTS:-} "$TARGET" "mkdir -p '$DIR' && tar -C '$DIR' -xzf - && cat '$DIR/VERSION'"
if [ -n "$PKG" ]; then
    # shellcheck disable=SC2086
    ssh ${SSH_OPTS:-} "$TARGET" "mkdir -p '$PKG' && cat > '$PKG/pylontech.yaml'" < ha/packages/pylontech.yaml
    echo "package -> $PKG/pylontech.yaml (check config + reload/restart HA)"
fi
