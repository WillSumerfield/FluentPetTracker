#!/bin/sh
# Keeps WSL's network adapter at the packet size Tailscale needs.
#
# Windows puts the adapter back to 1280 every time the computer wakes from sleep. At that
# size nothing sent through Tailscale arrives, so the phone cannot load the pages and the
# dashboard's frames stay empty on the PC. This puts it right at start and again whenever
# the adapter changes.

ADAPTER="${FLUENTPET_ADAPTER:-eth0}"
WANTED_MTU="${FLUENTPET_MTU:-1500}"

restore() {
    current=$(cat "/sys/class/net/$ADAPTER/mtu" 2>/dev/null) || {
        echo "Adapter $ADAPTER is not there yet; waiting for it." >&2
        return
    }
    [ "$current" = "$WANTED_MTU" ] && return
    if ip link set dev "$ADAPTER" mtu "$WANTED_MTU"; then
        echo "Restored $ADAPTER to MTU $WANTED_MTU (it had been set to $current)."
    else
        echo "Could not set $ADAPTER to MTU $WANTED_MTU; it stays at $current." >&2
    fi
}

restore
# One line arrives for every change to the adapter, including the one made here; that one
# finds nothing left to do.
ip monitor link | while read -r _change; do
    restore
done

# Only reached if the monitor stops. Leaving with an error has systemd start it again.
echo "The watch on $ADAPTER ended unexpectedly." >&2
exit 1
