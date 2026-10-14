#!/bin/sh
# Sets up this Raspberry Pi Zero 2 W as RPi Capture: the camera and mic streamed as one
# RTSP stream at rtsp://<pi>:8554/board, kept running day and night.
# Run on the Pi, from anywhere:  sudo sh rpi-capture/install.sh
# Safe to run again after changing any file in rpi-capture/.
set -e

MEDIAMTX_VERSION=v1.21.1
MEDIAMTX_SHA256=6a3aa635fb60ea9b8d566ec306f0a42ff1b6b52a3942bc2baffbe55880d4c3dd
CONFIG_TXT=/boot/firmware/config.txt

if [ "$(id -u)" -ne 0 ]; then
    echo "This must be run as root:  sudo sh $0" >&2
    exit 1
fi
if ! command -v systemctl >/dev/null 2>&1; then
    echo "systemd is not running here, so the stream service cannot be installed." >&2
    exit 1
fi
if [ "$(uname -m)" != "aarch64" ]; then
    echo "This expects 64-bit Raspberry Pi OS (aarch64), but this is $(uname -m)." >&2
    exit 1
fi
if [ ! -f "$CONFIG_TXT" ]; then
    echo "$CONFIG_TXT was not found, so this does not look like Raspberry Pi OS." >&2
    exit 1
fi

here=$(cd "$(dirname "$0")" && pwd)
reboot_needed=no

echo "Installing the camera and sound tools (this can take a while on the Zero 2 W)..."
apt-get update -q
apt-get install -y -q --no-install-recommends rpicam-apps-lite ffmpeg alsa-utils

if [ "$(/usr/local/bin/mediamtx --version 2>/dev/null)" = "$MEDIAMTX_VERSION" ]; then
    echo "MediaMTX $MEDIAMTX_VERSION is already installed."
else
    echo "Downloading MediaMTX $MEDIAMTX_VERSION..."
    work=$(mktemp -d)
    trap 'rm -rf "$work"' EXIT
    archive="mediamtx_${MEDIAMTX_VERSION}_linux_arm64.tar.gz"
    curl -fsSL -o "$work/$archive" \
        "https://github.com/bluenviron/mediamtx/releases/download/$MEDIAMTX_VERSION/$archive"
    if ! echo "$MEDIAMTX_SHA256  $work/$archive" | sha256sum -c --quiet -; then
        echo "The MediaMTX download does not match its known checksum, so it was not installed." >&2
        exit 1
    fi
    tar -xzf "$work/$archive" -C "$work" mediamtx
    install -m 755 "$work/mediamtx" /usr/local/bin/mediamtx
fi

# The stream runs as its own user, with only the camera and sound devices it needs.
if ! id mediamtx >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin mediamtx
fi

install -m 755 "$here/capture.sh" /usr/local/bin/rpi-capture-stream
install -d /usr/local/etc
install -m 644 "$here/mediamtx.yml" /usr/local/etc/mediamtx.yml
install -m 644 "$here/mediamtx.service" /etc/systemd/system/mediamtx.service

# The Arducam 12MP (IMX708) is named outright: auto-detection does not always find it.
if ! grep -q '^dtoverlay=imx708' "$CONFIG_TXT"; then
    [ -f "$CONFIG_TXT.before-rpi-capture" ] || cp "$CONFIG_TXT" "$CONFIG_TXT.before-rpi-capture"
    sed -i 's/^camera_auto_detect=1/camera_auto_detect=0/' "$CONFIG_TXT"
    printf '\n[all]\n# RPi Capture: Arducam 12MP (IMX708) on the camera port\ndtoverlay=imx708\n' >> "$CONFIG_TXT"
    echo "Set the camera in $CONFIG_TXT (the old file is kept beside it)."
    reboot_needed=yes
fi

# Wi-Fi power saving is the usual cause of the stream stalling. Takes effect on the next connection.
install -d /etc/NetworkManager/conf.d
printf '[connection]\n# RPi Capture: power saving stalls the stream\nwifi.powersave = 2\n' \
    > /etc/NetworkManager/conf.d/rpi-capture-wifi.conf

# The log is kept in memory, so months of logging do not wear out the SD card.
install -d /etc/systemd/journald.conf.d
printf '[Journal]\nStorage=volatile\nRuntimeMaxUse=32M\n' \
    > /etc/systemd/journald.conf.d/rpi-capture.conf
systemctl restart systemd-journald

# The hardware watchdog restarts the Pi if it locks up. Takes effect on the next boot.
install -d /etc/systemd/system.conf.d
if [ ! -f /etc/systemd/system.conf.d/rpi-capture-watchdog.conf ]; then
    printf '[Manager]\nRuntimeWatchdogSec=15s\n' > /etc/systemd/system.conf.d/rpi-capture-watchdog.conf
    reboot_needed=yes
fi

systemctl daemon-reload
systemctl enable mediamtx.service >/dev/null 2>&1
systemctl restart mediamtx.service
sleep 2

address=$(hostname -I | awk '{print $1}')
echo ""
echo "RPi Capture is installed."
echo "  Stream:          rtsp://$address:8554/board"
echo "  Service:         $(systemctl is-active mediamtx.service)"
echo "  Its log:         journalctl -u mediamtx -f"
if [ "$reboot_needed" = yes ]; then
    echo ""
    echo "Restart the Pi to finish (camera, Wi-Fi power saving, watchdog):  sudo reboot"
fi
