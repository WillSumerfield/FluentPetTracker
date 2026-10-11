# Context Map

## Structure

```
 0 .
 1 ├── CONTEXT-MAP.md
 1 ├── README.md
 1 ├── correlator
 2 │   ├── CONTEXT.md
 2 │   ├── Dockerfile
 2 │   ├── correlator
 3 │   │   ├── clips.py                ← cuts Clips through Frigate's export
 3 │   │   ├── config.py               ← settings from environment variables
 3 │   │   ├── database.py             ← Presses, Utterances, Observation Windows
 3 │   │   ├── presence.py             ← Board Zone presence and Presser attribution
 3 │   │   ├── report.py               ← prints what the database holds
 3 │   │   └── service.py              ← the running service
 2 │   ├── data
 2 │   └── requirements.txt
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
 2 │   ├── CONTEXT.md
 2 │   ├── Dockerfile
 2 │   ├── references
 3 │   │   └── happy
 2 │   ├── requirements.txt
 2 │   └── word_detection
 3 │       ├── audio.py                ← reads Reference Clips and the stream
 3 │       ├── check.py                ← lists the Words heard in a recording
 3 │       ├── config.py               ← settings from environment variables
 3 │       ├── enrol.py                ← Enrolment tool
 3 │       ├── features.py             ← audio to spectrogram
 3 │       ├── matcher.py              ← spectrogram to Words
 3 │       └── service.py              ← the running service
 1 └── temp
 2     ├── goal.md                     ← what/why/how, resolved decisions, glossary
 2     ├── phase-1-notes.md            ← RPi Capture implementation decisions
 2     ├── phase-2-notes.md            ← Frigate Classification implementation decisions
 2     ├── phase-3-notes.md            ← Word Detection implementation decisions
 2     ├── phase-4-notes.md            ← Correlator implementation decisions
 2     └── phased-plan.md              ← how the goal gets built, in phases
```

## Contexts

- [RPi Capture](./rpi-capture/CONTEXT.md) — runs on the wall-mounted Raspberry Pi Zero 2 W; camera + mic capture, streamed out via MediaMTX.
- [Frigate Classification](./frigate/CONTEXT.md) — runs on the local PC; consumes the RTSP video stream, classifies human vs. cat presence in the Board Zone, and owns the short-lived continuous recording that Clips are cut from (built-in Frigate behavior, not custom).
- [Word Detection](./word-detection/CONTEXT.md) — runs on the local PC; custom audio pipeline that consumes the mic feed and identifies which Word was spoken by matching it against Reference Clips.
- [Correlator](./correlator/CONTEXT.md) — runs on the local PC; custom app that joins Frigate's presence/zone events with Word Detection's events (by timestamp) into a Press record, resolves Presser attribution, groups Presses into Utterances, cuts one Clip per Utterance, and owns the database that is the source of truth for the longitudinal study.
- [Home Assistant Dashboard](./home-assistant/CONTEXT.md) — runs on the local PC; reads from the Correlator's database to present metrics and video, provides app/remote access, and has limited write access to resolve Ambiguous Press cases.

Frigate Classification, Word Detection and the Correlator are built against a stand-in stream; RPi Capture and the Home Assistant Dashboard are empty scaffolding (see `temp/phased-plan.md`).

## Relationships

- **RPi Capture → Frigate Classification**: video stream (RTSP via MediaMTX → FFmpeg)
- **RPi Capture → Word Detection**: audio stream (mic feed), read from the same RTSP stream as the video
- **Frigate Classification → Correlator**: Board Zone presence events over the MQTT broker, plus the recorded footage Clips are cut from (through Frigate's export feature)
- **Word Detection → Correlator**: Word-identification events, including Uncertain Matches, over the MQTT broker in the Frigate stack
- **Correlator → Home Assistant Dashboard**: finalized Press records (read-only)
- **(Future) FluentPet Connect board API → Word Detection / Correlator**: deferred integration, not part of current scope
