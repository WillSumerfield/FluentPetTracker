# Context Map

## Structure

```
 0 .
 1 ├── CONTEXT-MAP.md
 1 ├── README.md
 1 ├── correlator
 2 │   └── CONTEXT.md
 1 ├── frigate
 2 │   ├── CONTEXT.md
 2 │   ├── config
 3 │   │   └── config.yml
 2 │   ├── docker-compose.yml
 2 │   ├── mosquitto
 3 │   │   └── mosquitto.conf
 2 │   ├── standin
 3 │   │   ├── cat.mp4
 3 │   │   └── mediamtx.yml
 2 │   └── storage
 1 ├── home-assistant
 2 │   └── CONTEXT.md
 1 ├── rpi-capture
 2 │   └── CONTEXT.md
 1 ├── word-detection
 2 │   └── CONTEXT.md
 1 └── temp
 2     ├── goal.md                     ← what/why/how, resolved decisions, glossary
 2     ├── phase-1-notes.md            ← RPi Capture implementation decisions
 2     ├── phase-2-notes.md            ← Frigate Classification implementation decisions
 2     └── phased-plan.md              ← how the goal gets built, in phases
```

## Contexts

- [RPi Capture](./rpi-capture/CONTEXT.md) — runs on the wall-mounted Raspberry Pi Zero 2 W; camera + mic capture, streamed out via MediaMTX.
- [Frigate Classification](./frigate/CONTEXT.md) — runs on the local PC; consumes the RTSP video stream, classifies human vs. cat presence in the Board Zone, and owns the short-lived continuous recording that Clips are cut from (built-in Frigate behavior, not custom).
- [Word Detection](./word-detection/CONTEXT.md) — runs on the local PC; custom audio pipeline that consumes the mic feed and identifies which Word was spoken.
- [Correlator](./correlator/CONTEXT.md) — runs on the local PC; custom app that joins Frigate's presence/zone events with Word Detection's events (by timestamp) into a Press record, resolves Presser attribution, groups Presses into Utterances, cuts one Clip per Utterance, and owns the database that is the source of truth for the longitudinal study.
- [Home Assistant Dashboard](./home-assistant/CONTEXT.md) — runs on the local PC; reads from the Correlator's database to present metrics and video, provides app/remote access, and has limited write access to resolve Ambiguous Press cases.

All five contexts are currently empty scaffolding — implementation hasn't started (see `temp/phased-plan.md`).

## Relationships

- **RPi Capture → Frigate Classification**: video stream (RTSP via MediaMTX → FFmpeg)
- **RPi Capture → Word Detection**: audio stream (mic feed)
- **Frigate Classification → Correlator**: Board Zone presence events, plus the recorded footage Clips are cut from
- **Word Detection → Correlator**: Word-identification events
- **Correlator → Home Assistant Dashboard**: finalized Press records (read-only)
- **(Future) FluentPet Connect board API → Word Detection / Correlator**: deferred integration, not part of current scope
