# RPi Capture

Runs on the wall-mounted Raspberry Pi Zero 2 W. Captures camera and mic input and streams both out over RTSP via MediaMTX for consumption on the local PC.

## Architecture

MediaMTX runs on the Pi as a systemd service and serves one stream, `board`, with the camera's picture and the mic's sound together. It starts the capture pipeline itself and starts it again whenever it stops.

- **capture.sh**: the capture pipeline; the camera's H.264 and the mic's sound, published to the Pi's own MediaMTX. With no camera fitted it sends a test picture with the mic instead. Its settings (focus, mic, picture size) are at the top.
- **mediamtx.yml**: MediaMTX's configuration. Anyone on the network may watch; only the Pi itself may publish.
- **mediamtx.service**: the systemd service that keeps MediaMTX running.
- **control.py**, **rpi-capture-control.service**: Pause and Resume. A small service that switches MediaMTX off and back on when the PC asks, and answers no one else. A Pause outlasts a reboot.
- **install.sh**: sets up the Pi from these files; run on the Pi, and again after any change. It leaves a Paused stream off, and holds the PC's address, the only one allowed to Pause or Resume.

## Language

**Pause**:
A stretch of time during which capture is deliberately switched off at the Pi, so nothing is seen, heard or recorded. It ends the current Observation Window; Resume ends the Pause. Unlike an outage, it is chosen.
_Avoid_: Stop, privacy mode, off
