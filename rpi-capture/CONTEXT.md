# RPi Capture

Runs on the wall-mounted Raspberry Pi Zero 2 W. Captures camera and mic input and streams both out over RTSP via MediaMTX for consumption on the local PC.

## Architecture

MediaMTX runs on the Pi as a systemd service and serves one stream, `board`, with the camera's picture and the mic's sound together. It starts the capture pipeline itself and starts it again whenever it stops.

- **capture.sh**: the capture pipeline; the camera's H.264 and the mic's sound, published to the Pi's own MediaMTX. Its settings (focus, mic, picture size) are at the top.
- **mediamtx.yml**: MediaMTX's configuration. Anyone on the network may watch; only the Pi itself may publish.
- **mediamtx.service**: the systemd service that keeps MediaMTX running.
- **install.sh**: sets up the Pi from these files; run on the Pi, and again after any change.

## Language

No terms specific to this context yet.
