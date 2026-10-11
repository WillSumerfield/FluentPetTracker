# Frigate Classification

Runs on the local PC. Consumes the RTSP stream via FFmpeg and classifies human vs. animal presence in zones around the board. Owns continuous recording and event-triggered Clip saving (Frigate's built-in behavior, not custom).

## Architecture

Empty — implementation begins in Phase 2 (see `temp/phased-plan.md`).

## Language

**Clip**:
The video segment Frigate saves (with pre-event padding) corresponding to a Press.
_Avoid_: Recording, footage, video segment
