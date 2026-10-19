#!/bin/sh
# Streams the camera and the mic together as one RTSP stream to the Pi's own MediaMTX, at "board".
# MediaMTX starts this (runOnInit in mediamtx.yml) and starts it again whenever it stops,
# so it is not meant to be run by hand while the service is running.
set -eu

# Settings come from the root config.yml (the pi: section), which configure.py writes to
# rpi-capture/capture.env and install.sh installs here. Each one below is only the fallback
# for a setting that file leaves out.
SETTINGS=/usr/local/etc/rpi-capture.env
if [ -r "$SETTINGS" ]; then
    # shellcheck source=/dev/null
    . "$SETTINGS"
else
    echo "rpi-capture: $SETTINGS was not found; using the built-in settings." >&2
fi

# How far away the board is, as the lens sees it: 1 / distance in metres (0 is infinity,
# 2.0 is 50 cm).
LENS_POSITION=${LENS_POSITION:-1.0}

# The mic, named rather than numbered so it is found even if the card number changes.
MIC=${MIC:-plughw:CARD=Mic,DEV=0}

# 1080p at 30 fps is the most the Pi's H.264 encoder can do. 12 Mbit/s keeps fast motion sharp
# and still fits the Pi's 2.4 GHz Wi-Fi.
WIDTH=${WIDTH:-1920}
HEIGHT=${HEIGHT:-1080}
FPS=${FPS:-30}
BITRATE=${BITRATE:-12000000}

# What to do with no camera fitted: "test-pattern" sends a test picture with the real mic,
# so the PC can run on the mic before the camera arrives; "wait" sends nothing. The camera
# is used whenever one is found, whatever this says.
NO_CAMERA=${NO_CAMERA:-test-pattern}

# Without the mic, wait before giving up, so the log is not filled with a failure
# every few seconds while MediaMTX keeps starting this again.
# Only a mic named by its card (CARD=...) can be looked for; one given by number is just tried.
mic_card=""
case "$MIC" in *CARD=*) mic_card=${MIC#*CARD=}; mic_card=${mic_card%%,*} ;; esac
if [ -n "$mic_card" ] && ! arecord -L 2>/dev/null | grep -qF "CARD=$mic_card,"; then
    echo "rpi-capture: the mic ($MIC) is not plugged in; trying again in 60 s." >&2
    sleep 60
    exit 1
fi

if ! rpicam-hello --list-cameras 2>/dev/null | grep -q '^[0-9]'; then
    if [ "$NO_CAMERA" != test-pattern ]; then
        echo "rpi-capture: no camera found; trying again in 60 s." >&2
        sleep 60
        exit 1
    fi
    # The test picture is made and encoded in software, so it is kept small and slow
    # (about half of one core); the camera's own encoder does the real picture.
    echo "rpi-capture: no camera found; streaming a 640x360 test pattern at 10 fps with the mic" >&2
    exec ffmpeg -nostdin -hide_banner -loglevel error -xerror \
        -re -f lavfi -i testsrc2=size=640x360:rate=10 \
        -thread_queue_size 1024 -f alsa -sample_rate 44100 -channels 1 -i "$MIC" \
        -map 0:v -map 1:a -c:v libx264 -preset ultrafast -tune zerolatency -g 10 -pix_fmt yuv420p \
        -c:a aac -b:a 128k \
        -f rtsp -rtsp_transport tcp rtsp://localhost:8554/board
fi

echo "rpi-capture: streaming ${WIDTH}x${HEIGHT} at ${FPS} fps with sound to rtsp://localhost:8554/board" >&2

# The camera's own encoder makes the H.264; ffmpeg copies it as it is and adds the mic as AAC.
# A raw H.264 pipe carries no timestamps, so ffmpeg stamps each frame with the time it arrives,
# the same clock it stamps the sound with, which keeps picture and sound together.
# The picture is not probed or buffered (-fflags nobuffer -probesize 32 -analyzeduration 0):
# probing it while the mic runs holds up the pipe, and the camera then drops to about 5 fps.
# Colour denoise is off: the Zero 2 W does it on the CPU and cannot keep up at 1080p30, so it
# skips frames. The cost is a little colour grain in dim light.
rpicam-vid --nopreview --verbose 0 -t 0 \
    --width "$WIDTH" --height "$HEIGHT" --framerate "$FPS" --denoise cdn_off \
    --codec h264 --level 4.1 --bitrate "$BITRATE" --inline --intra "$FPS" \
    --autofocus-mode manual --lens-position "$LENS_POSITION" \
    -o - \
| ffmpeg -nostdin -hide_banner -loglevel error -xerror \
    -fflags nobuffer -probesize 32 -analyzeduration 0 \
    -thread_queue_size 1024 -use_wallclock_as_timestamps 1 -f h264 -i - \
    -thread_queue_size 1024 -f alsa -sample_rate 44100 -channels 1 -i "$MIC" \
    -map 0:v -map 1:a -c:v copy -c:a aac -b:a 128k \
    -f rtsp -rtsp_transport tcp rtsp://localhost:8554/board
