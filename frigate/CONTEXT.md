# Frigate Classification

Runs on the local PC. Consumes the RTSP stream via FFmpeg and classifies human vs. animal presence in zones around the board. Owns the short-lived continuous recording that Clips are later cut from (Frigate's built-in behavior, not custom). Also relays the stream, with sound, to the dashboard's Live Feed page.

## Architecture

A Docker Compose stack: Frigate, the MQTT broker it publishes to, and a temporary stand-in for the Pi's stream. The stack also starts the Word Detection and Correlator containers, which are built from `word-detection/` and `correlator/`.

- **docker-compose.yml**: defines the stack's containers.
- **config/**: Frigate's configuration, including the Board Zone; Frigate also writes its runtime database here.
- **mosquitto/**: configuration for the MQTT broker.
- **standin/**: a looped video served as if it were the Pi's stream, to be removed once RPi Capture is live.
- **storage/**: Frigate's short-lived recordings (not committed).

## Language

**Board Zone**:
The area around the FluentPet Board from which a subject could reach a button, sized to a person's arm's reach. Being in the Board Zone at press time is what makes a subject a candidate Presser.
_Avoid_: Range, proximity, detection area