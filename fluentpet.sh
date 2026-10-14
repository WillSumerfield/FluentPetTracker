#!/bin/sh
# Starts FluentPetTracker on this PC, with every setting taken from the root config.yml.
#
#   ./fluentpet.sh up              write the settings from config.yml, then start everything
#   ./fluentpet.sh configure       only write the settings (add --check to write nothing)
#   ./fluentpet.sh thumbnails      give Clips cut before thumbnails existed one each
#   ./fluentpet.sh clear           clear everything the study has recorded, for a fresh start
#   ./fluentpet.sh <anything else> passed to docker compose, e.g.  ./fluentpet.sh logs -f correlator
set -eu

root=$(cd "$(dirname "$0")" && pwd)

configure() {
    if ! command -v python3 >/dev/null 2>&1; then
        echo "✗ python3 is needed to read config.yml. Install it with:  sudo apt install python3 python3-yaml" >&2
        exit 1
    fi
    python3 "$root/configure.py" "$@"
}

compose() {
    if ! command -v docker >/dev/null 2>&1; then
        echo "✗ docker was not found. Is Docker Desktop running, with WSL integration on?" >&2
        exit 1
    fi
    cd "$root/frigate"
    exec docker compose "$@"
}

command=${1:-}
case "$command" in
    "" | -h | --help | help)
        sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
        ;;
    configure)
        shift
        configure "$@"
        ;;
    thumbnails)
        python3 "$root/correlator/backfill_thumbnails.py"
        ;;
    clear)
        shift
        # Settings are written first, so the folders cleared are the ones Docker mounts.
        configure
        echo ""
        python3 "$root/correlator/clear_data.py" "$@"
        ;;
    up)
        shift
        # Settings are written first, every time, so they never lag behind config.yml.
        configure
        echo ""
        compose up -d "$@"
        ;;
    *)
        compose "$@"
        ;;
esac
