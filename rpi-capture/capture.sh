#!/bin/sh
# Streams the camera and the mic together as one RTSP stream to the Pi's own MediaMTX, at "board".
# MediaMTX starts this (runOnInit in mediamtx.yml) and starts it again whenever it stops,
# so it is not meant to be run by hand while the service is running.
set -eu

# How far away the board is, as the lens sees it: 1 / distance in metres (0 is infinity,
# 2.0 is 50 cm). PLACEHOLDER until the Arducam is mounted; see temp/rpi-setup-plan.md.
LENS_POSITION=1.0

# The Samson Go Mic, named rather than numbered so it is found even if the card number changes.
MIC=plughw:CARD=Mic,DEV=0

WIDTH=1280
HEIGHT=720
FPS=30

# With no camera fitted, wait before giving up, so the log is not filled with a failure
# every few seconds while MediaMTX keeps starting this again.
if ! rpicam-hello --list-cameras 2>/dev/null | grep -q '^[0-9]'; then
    echo "rpi-capture: no camera found; trying again in 60 s." >&2
    sleep 60
    exit 1
fi
if ! arecord -L 2>/dev/null | grep -q 'CARD=Mic'; then
    echo "rpi-capture: the mic ($MIC) is not plugged in; trying again in 60 s." >&2
    sleep 60
    exit 1
fi

echo "rpi-capture: streaming ${WIDTH}x${HEIGHT} at ${FPS} fps with sound to rtsp://localhost:8554/board" >&2

# The camera's own encoder makes the H.264; ffmpeg copies it as it is and adds the mic as AAC.
# A raw H.264 pipe carries no timestamps, so ffmpeg stamps each frame with the time it arrives,
# the same clock it stamps the sound with, which keeps picture and sound together.
rpicam-vid --nopreview --verbose 0 -t 0 \
    --width "$WIDTH" --height "$HEIGHT" --framerate "$FPS" \
    --codec h264 --inline --intra "$FPS" \
    --autofocus-mode manual --lens-position "$LENS_POSITION" \
    -o - \
| ffmpeg -nostdin -hide_banner -loglevel error \
    -thread_queue_size 1024 -use_wallclock_as_timestamps 1 -f h264 -i - \
    -thread_queue_size 1024 -f alsa -sample_rate 44100 -channels 1 -i "$MIC" \
    -map 0:v -map 1:a -c:v copy -c:a aac -b:a 128k \
    -f rtsp -rtsp_transport tcp rtsp://localhost:8554/board
