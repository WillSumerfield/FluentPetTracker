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
 3 │   │   ├── service.py              ← the recording service
 3 │   │   ├── metrics.py              ← Utterances and the study's figures, worked out from Presses
 3 │   │   ├── static                  ← the dashboard pages
 3 │   │   ├── store.py                ← what the web pages may read and write
 3 │   │   └── web.py                  ← the web service and its API
 2 │   ├── data
 2 │   └── requirements.txt
 1 ├── frigate
 2 │   ├── CONTEXT.md
 2 │   ├── config
 3 │   │   └── config.yml
 2 │   ├── docker-compose.yml
 2 │   ├── mosquitto
 3 │   │   └── mosquitto.conf
 2 │   ├── relay
 3 │   │   └── mediamtx.yml            ← passes the Pi's stream on
 2 │   ├── standin
 3 │   │   ├── cat.mp4
 3 │   │   └── mediamtx.yml
 2 │   └── storage
 1 ├── home-assistant
 2 │   ├── CONTEXT.md
 2 │   └── config
 3 │       ├── configuration.yaml      ← sidebar entries and sensors
 3 │       └── dashboards
 1 ├── rpi-capture
 2 │   ├── CONTEXT.md
 2 │   ├── capture.sh                  ← camera + mic into one stream
 2 │   ├── control.py                  ← Pause and Resume, asked by the PC
 2 │   ├── install.sh                  ← sets up the Pi
 2 │   ├── mediamtx.service
 2 │   ├── mediamtx.yml
 2 │   └── rpi-capture-control.service
 1 ├── word-detection
 2 │   ├── CONTEXT.md
 2 │   ├── Dockerfile
 2 │   ├── references
 3 │   │   └── play
 2 │   ├── requirements.txt
 2 │   └── word_detection
 3 │       ├── audio.py                ← reads Reference Clips and the stream
 3 │       ├── check.py                ← lists the Words heard in a recording
 3 │       ├── config.py               ← settings from environment variables
 3 │       ├── enrol.py                ← Enrolment tool for the command line
 3 │       ├── enrolment.py            ← Enrolment Recording, Spans, saving
 3 │       ├── features.py             ← audio to spectrogram
 3 │       ├── matcher.py              ← spectrogram to Words
 3 │       ├── references.py           ← the Reference Clip files
 3 │       ├── service.py              ← the running service
 3 │       └── web.py                  ← Enrolment over the web
 1 ├── wsl
 2 │   ├── fluentpet-mtu.service       ← keeps the pages reachable after sleep
 2 │   ├── fluentpet-mtu.sh
 2 │   └── install.sh
 1 └── temp
 2     ├── enrolment-and-sleep-plan.md ← the Enrolment page and recovery after sleep
 2     ├── goal.md                     ← what/why/how, resolved decisions, glossary
 2     ├── phase-1-notes.md            ← RPi Capture implementation decisions
 2     ├── phase-2-notes.md            ← Frigate Classification implementation decisions
 2     ├── phase-3-notes.md            ← Word Detection implementation decisions
 2     ├── phase-4-notes.md            ← Correlator implementation decisions
 2     ├── phase-5-notes.md            ← Home Assistant Dashboard implementation decisions
 2     ├── phase-6-notes.md
 2     ├── phase-7-notes.md            ← Enrolment page and sleep recovery: decisions and tests
 2     └── phased-plan.md              ← how the goal gets built, in phases
```

## Contexts

- [RPi Capture](./rpi-capture/CONTEXT.md) — runs on the wall-mounted Raspberry Pi Zero 2 W; camera + mic capture, streamed out via MediaMTX, and switched off at the Pi during a Pause.
- [Frigate Classification](./frigate/CONTEXT.md) — runs on the local PC; consumes the RTSP video stream, classifies human vs. cat presence in the Board Zone, and owns the short-lived continuous recording that Clips are cut from (built-in Frigate behavior, not custom).
- [Word Detection](./word-detection/CONTEXT.md) — runs on the local PC; custom audio pipeline that consumes the mic feed and identifies which Word was spoken by matching it against Reference Clips.
- [Correlator](./correlator/CONTEXT.md) — runs on the local PC; custom app that joins Frigate's presence/zone events with Word Detection's events (by timestamp) into a Press record, resolves Presser attribution, groups Presses into Exchanges and their Utterances, cuts one Clip per Exchange, and owns the database that is the source of truth for the longitudinal study.
- [Home Assistant Dashboard](./home-assistant/CONTEXT.md) — runs on the local PC; shows the Correlator's pages (live view, Review Queue, history) and polls its figures. It never opens the database; its only write is a Review Decision, sent through the Correlator.

Frigate Classification, Word Detection, the Correlator and the Home Assistant Dashboard run on the Pi's stream, which has the real mic but a test picture until the Arducam is fitted (see `temp/phased-plan.md`).

## Relationships

- **RPi Capture → Frigate Classification**: video stream (RTSP via MediaMTX → FFmpeg)
- **RPi Capture → Word Detection**: audio stream (mic feed), read from the same RTSP stream as the video
- **Frigate Classification → Correlator**: Board Zone presence events over the MQTT broker, plus the recorded footage Clips are cut from (through Frigate's export feature)
- **Word Detection → Correlator**: Word-identification events, including Uncertain Matches, over the MQTT broker in the Frigate stack
- **Correlator → Home Assistant Dashboard**: pages, figures and Clips over the Correlator's web service
- **Correlator → Home Assistant Dashboard**: each closed Exchange, with the Utterances attributed to the cat and those awaiting review, over the MQTT broker; Home Assistant turns these into Utterance Alerts
- **Home Assistant Dashboard → Correlator**: Review Decisions, over the same web service
- **Home Assistant Dashboard → RPi Capture**: Pause and Resume, from the Live Feed page, passed on by the Correlator's web service to the Pi's control service
- **Home Assistant Dashboard → Word Detection**: Enrolment (recording, Spans, and the Reference Clips kept), passed on unchanged by the Correlator's web service. Only Word Detection reads or writes Reference Clips.
- **(Future) FluentPet Connect board API → Word Detection / Correlator**: deferred integration, not part of current scope
