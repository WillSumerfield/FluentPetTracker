# Context Map

## Structure

```
 0 .
 1 ├── CONTEXT-MAP.md
 1 ├── README.md
 1 ├── correlator
 2 │   └── CONTEXT.md
 1 ├── frigate
 2 │   └── CONTEXT.md
 1 ├── home-assistant
 2 │   └── CONTEXT.md
 1 ├── rpi-capture
 2 │   └── CONTEXT.md
 1 ├── word-detection
 2 │   └── CONTEXT.md
 1 └── temp
 2     ├── goal.md                     ← what/why/how, resolved decisions, glossary
 2     └── phased-plan.md              ← how the goal gets built, in phases
```

## Contexts

- [RPi Capture](./rpi-capture/CONTEXT.md) — runs on the wall-mounted Raspberry Pi Zero 2 W; camera + mic capture, streamed out via MediaMTX.
- [Frigate Classification](./frigate/CONTEXT.md) — runs on the local PC; consumes the RTSP video stream, classifies human vs. animal presence in zones around the board, owns continuous recording and event-triggered Clip saving (built-in Frigate behavior, not custom).
- [Word Detection](./word-detection/CONTEXT.md) — runs on the local PC; custom audio pipeline that consumes the mic feed and identifies which Word was spoken.
- [Correlator](./correlator/CONTEXT.md) — runs on the local PC; custom app that joins Frigate's presence/zone events with Word Detection's events (by timestamp) into a Press record, resolves Presser attribution, and owns the database that is the source of truth for the longitudinal study.
- [Home Assistant Dashboard](./home-assistant/CONTEXT.md) — runs on the local PC; reads from the Correlator's database to present metrics and video, provides app/remote access, and has limited write access to resolve Ambiguous Press cases.

All five contexts are currently empty scaffolding — implementation hasn't started (see `temp/phased-plan.md`).

## Relationships

- **RPi Capture → Frigate Classification**: video stream (RTSP via MediaMTX → FFmpeg)
- **RPi Capture → Word Detection**: audio stream (mic feed)
- **Frigate Classification → Correlator**: presence/zone events + Clip references
- **Word Detection → Correlator**: Word-identification events
- **Correlator → Home Assistant Dashboard**: finalized Press records (read-only)
- **(Future) FluentPet Connect board API → Word Detection / Correlator**: deferred integration, not part of current scope
