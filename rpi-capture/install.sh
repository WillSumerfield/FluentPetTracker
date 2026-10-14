#!/bin/sh
# Sets up this Raspberry Pi Zero 2 W as RPi Capture: the camera and mic streamed as one
# RTSP stream at rtsp://<pi>:8554/board, kept running day and night.
# Run on the Pi, from anywhere:  sudo sh rpi-capture/install.sh
# Safe to run again after changing any file in rpi-capture/.
set -e

MEDIAMTX_VERSION=v1.21.1
MEDIAMTX_SHA256=6a3aa635fb60ea9b8d566ec306f0a42ff1b6b52a3942bc2baffbe55880d4c3dd
CONFIG_TXT=/boot/firmware/config.txt
PAUSED_FILE=/var/lib/rpi-capture/paused
SETTINGS=/usr/local/etc/rpi-capture.env

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

# Settings come from the root config.yml (the pi: section): ./fluentpet.sh configure on the PC
# writes them to capture.env beside this script, which is copied here with it.
if [ -f "$here/capture.env" ]; then
    # shellcheck source=/dev/null
    . "$here/capture.env"
    echo "Using the settings in $here/capture.env."
else
    echo "No capture.env beside this script, so the built-in settings are used." >&2
    echo "On the PC, run ./fluentpet.sh configure and copy rpi-capture/ here again to set your own." >&2
fi
# Only these may Pause or Resume the stream: the PC's address on the LAN (pi.allowed_pcs),
# which needs a DHCP reservation of its own. Several may be given, separated by spaces.
PC_ADDRESSES=${PC_ADDRESSES:-192.168.0.164}
CONTROL_PORT=${CONTROL_PORT:-8800}
reboot_needed=no

echo "Installing the camera and sound tools (this can take a while on the Zero 2 W)..."
apt-get update -q
apt-get install -y -q --no-install-recommends rpicam-apps-lite ffmpeg alsa-utils python3 sudo

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
if [ -f "$here/capture.env" ]; then
    install -m 644 "$here/capture.env" "$SETTINGS"
fi
install -m 644 "$here/mediamtx.service" /etc/systemd/system/mediamtx.service

# Pause and Resume run as their own user, allowed by sudo to switch MediaMTX off and on, and nothing else.
if ! id rpi-capture-control >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin rpi-capture-control
fi
install -m 755 "$here/control.py" /usr/local/bin/rpi-capture-control
install -m 644 "$here/rpi-capture-control.service" /etc/systemd/system/rpi-capture-control.service
printf '# Written by rpi-capture/install.sh from config.yml (pi:); change it there.\nCONTROL_PORT=%s\nCONTROL_ALLOW="127.0.0.1 %s"\n' \
    "$CONTROL_PORT" "$PC_ADDRESSES" > /etc/default/rpi-capture-control
# The same path control.py runs, since sudo matches the command exactly.
systemctl_path=/usr/bin/systemctl
if [ ! -x "$systemctl_path" ]; then
    echo "$systemctl_path was not found, so Pause and Resume cannot be set up." >&2
    exit 1
fi
sudoers=$(mktemp)
printf 'rpi-capture-control ALL=(root) NOPASSWD: %s disable --now mediamtx.service, %s enable --now mediamtx.service\n' \
    "$systemctl_path" "$systemctl_path" > "$sudoers"
if ! visudo -cqf "$sudoers"; then
    rm -f "$sudoers"
    echo "The sudo rule for Pause and Resume did not check out, so nothing was changed in sudoers." >&2
    exit 1
fi
install -m 440 "$sudoers" /etc/sudoers.d/rpi-capture-control
rm -f "$sudoers"

# The Arducam 12MP (IMX708) is named outright: auto-detection does not always find it.
if ! grep -q '^dtoverlay=imx708' "$CONFIG_TXT"; then
    [ -f "$CONFIG_TXT.before-rpi-capture" ] || cp "$CONFIG_TXT" "$CONFIG_TXT.before-rpi-capture"
    sed -i 's/^camera_auto_detect=1/camera_auto_detect=0/' "$CONFIG_TXT"
    printf '\n[all]\n# RPi Capture: Arducam 12MP (IMX708) on the camera port\ndtoverlay=imx708\n' >> "$CONFIG_TXT"
    echo "Set the camera in $CONFIG_TXT (the old file is kept beside it)."
    reboot_needed=yes
fi

# With no screen, the GPU needs little of the memory set aside for it (CMA). The default 256 MB
# leaves the Pi so little ordinary memory that a USB webcam's buffers ran it out; 128 MB is
# still far more than the camera's frame buffers need.
if grep -q '^dtoverlay=vc4-kms-v3d$' "$CONFIG_TXT"; then
    [ -f "$CONFIG_TXT.before-rpi-capture" ] || cp "$CONFIG_TXT" "$CONFIG_TXT.before-rpi-capture"
    sed -i 's/^dtoverlay=vc4-kms-v3d$/dtoverlay=vc4-kms-v3d,cma-128/' "$CONFIG_TXT"
    echo "Set aside 128 MB for the GPU and camera in $CONFIG_TXT, in place of 256 MB."
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
# A Pause is kept: installing again must not switch the camera and mic back on.
if [ -f "$PAUSED_FILE" ]; then
    paused=yes
    echo "The stream is Paused, so it was left off. Resume it from the Live Feed page."
else
    paused=no
    systemctl enable mediamtx.service >/dev/null 2>&1
    systemctl restart mediamtx.service
fi
systemctl enable rpi-capture-control.service >/dev/null 2>&1
systemctl restart rpi-capture-control.service
sleep 2

address=$(hostname -I | awk '{print $1}')
echo ""
echo "RPi Capture is installed."
echo "  Stream:          rtsp://$address:8554/board"
if [ "$paused" = yes ]; then
    echo "  Service:         paused"
else
    echo "  Service:         $(systemctl is-active mediamtx.service)"
fi
echo "  Its log:         journalctl -u mediamtx -f"
echo "  Pause / Resume:  http://$address:$CONTROL_PORT/status ($(systemctl is-active rpi-capture-control.service)), for $PC_ADDRESSES"
echo "  Its log:         journalctl -u rpi-capture-control -f"
if [ "$reboot_needed" = yes ]; then
    echo ""
    echo "Restart the Pi to finish (camera, Wi-Fi power saving, watchdog):  sudo reboot"
fi
