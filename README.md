# FluentPetTracker

A wall-mounted Raspberry Pi Zero W2 (camera + mic) streams live video from above a FluentPet board to a local PC, where it's processed for animal/human detection and surfaced on a dashboard.

**Stack:**
- RTSP streaming: MediaMTX (on the Pi) + FFmpeg (on the PC)
- Classification: Frigate NVR (animal/human detection)
- Dashboard & access: Home Assistant

Design and domain decisions are being worked out — see `CONTEXT-MAP.md` once contexts are established.

## Phone access

The phone reaches the app over Tailscale, from anywhere, through the Home Assistant app. Nothing is opened to the home network: every port stays bound to `127.0.0.1`, and Tailscale Serve forwards three things from this PC's tailnet address over HTTPS.

```
tailscale serve --bg --https=443  http://127.0.0.1:8123
tailscale serve --bg --https=8443 http://127.0.0.1:8600
tailscale serve --bg --https=8443 --set-path /live/mse/api/ws http://127.0.0.1:5000/live/mse/api/ws
```

- Port 443 is Home Assistant, 8443 is the Correlator's pages, and `/live/mse/api/ws` on 8443 is the one address of Frigate the Live Feed needs. The rest of Frigate stays private.
- Home Assistant refuses forwarded requests until it trusts Docker's network: `use_x_forwarded_for: true` and `trusted_proxies` of `127.0.0.1` and `172.16.0.0/12`. This version keeps its HTTP settings in `home-assistant/config/.storage/http`, not in `configuration.yaml`, so they were added there. Run `tailscale set --operator=$USER` as root once, so Serve can be managed without `sudo`.
- The pages have no login of their own: being on the tailnet is what grants access.
- The addresses of the pages are kept in `home-assistant/config/secrets.yaml`, which is not committed, so the tailnet's name stays out of the repository. It needs `fluentpet_daily_url`, `fluentpet_review_url`, `fluentpet_live_url` and `fluentpet_metrics_url`.
- Utterance Alerts need the MQTT integration added in Home Assistant's settings (broker `mosquitto`, port 1883) and the Home Assistant app installed on the phone.
- The app is only reachable while the PC is awake and WSL is running.

