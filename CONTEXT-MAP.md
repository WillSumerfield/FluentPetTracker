# Context Map

## Structure

```
 0 .
 1 ├── CONTEXT-MAP.md
 1 ├── README.md
 1 └── temp
 2     └── plan.md                     ← open questions / working notes
```

_Context directories (rpi-capture, frigate, word-detection, correlator, home-assistant) are planned but not yet created — layout is still being finalized. This map will be updated with real paths once they exist._

## Contexts (planned)

- **RPi Capture** — runs on the wall-mounted Raspberry Pi Zero 2 W; camera + mic capture, streamed out via MediaMTX.
- **Frigate Classification** — runs on the local PC; consumes the RTSP video stream, classifies human vs. animal presence in zones around the board, owns continuous recording and event-triggered Clip saving (built-in Frigate behavior, not custom).
- **Word Detection** — runs on the local PC; custom audio pipeline that consumes the mic feed and identifies which Word was spoken.
- **Correlator** — runs on the local PC; custom app that joins Frigate's presence/zone events with Word Detection's events (by timestamp) into a Press record, resolves Presser attribution, and owns the database that is the source of truth for the longitudinal study.
- **Home Assistant Dashboard** — runs on the local PC; reads from the Correlator's database (read-only) to present metrics and video, and provides app/remote access.

## Relationships

- **RPi Capture → Frigate Classification**: video stream (RTSP via MediaMTX → FFmpeg)
- **RPi Capture → Word Detection**: audio stream (mic feed)
- **Frigate Classification → Correlator**: presence/zone events + Clip references
- **Word Detection → Correlator**: Word-identification events
- **Correlator → Home Assistant Dashboard**: finalized Press records (read-only)
- **(Future) FluentPet Connect board API → Word Detection / Correlator**: deferred integration, not part of current scope
