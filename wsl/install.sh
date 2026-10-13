#!/bin/sh
# Installs the watcher that keeps the pages reachable after the computer has slept.
# Run once, from anywhere:  sudo sh wsl/install.sh
set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "This must be run as root:  sudo sh $0" >&2
    exit 1
fi
if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemd is not running here, so the watcher cannot be installed." >&2
    exit 1
fi

here=$(cd "$(dirname "$0")" && pwd)
install -m 755 "$here/fluentpet-mtu.sh" /usr/local/sbin/fluentpet-mtu.sh
install -m 644 "$here/fluentpet-mtu.service" /etc/systemd/system/fluentpet-mtu.service

# The watcher replaces the one-off fix made when WSL boots, which did not cover waking.
if [ -f /etc/wsl.conf ] && grep -q "ip link set dev eth0 mtu" /etc/wsl.conf; then
    cp /etc/wsl.conf /etc/wsl.conf.before-fluentpet-mtu
    sed -i -e 's/; *ip link set dev eth0 mtu [0-9]*//' -e 's/ip link set dev eth0 mtu [0-9]*; *//' \
        -e '/^command *= *ip link set dev eth0 mtu [0-9]* *$/d' /etc/wsl.conf
    echo "Removed the boot-time fix from /etc/wsl.conf (the old file is kept beside it)."
fi

systemctl daemon-reload
systemctl enable --now fluentpet-mtu.service
sleep 1

echo "The watcher is installed and running."
echo "  Adapter packet size now:  $(cat /sys/class/net/eth0/mtu 2>/dev/null || echo unknown)"
echo "  Its log:                  journalctl -u fluentpet-mtu"
