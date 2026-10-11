# FluentPetTracker

A wall-mounted Raspberry Pi Zero W2 (camera + mic) streams live video from above a FluentPet board to a local PC, where it's processed for animal/human detection and surfaced on a dashboard.

**Stack:**
- RTSP streaming: MediaMTX (on the Pi) + FFmpeg (on the PC)
- Classification: Frigate NVR (animal/human detection)
- Dashboard & access: Home Assistant

Design and domain decisions are being worked out — see `CONTEXT-MAP.md` once contexts are established.
