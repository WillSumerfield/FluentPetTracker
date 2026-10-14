#!/usr/bin/env python3
"""Pause and Resume for RPi Capture: switches the stream off at the Pi, and back on.

A Pause stops MediaMTX and keeps it from starting at boot, so the camera and mic stay off,
through a reboot or a power cut, until Resume. Asked over HTTP, by the PC only:

    GET  /status   whether the stream is live, starting, paused or down
    POST /pause    stops the stream
    POST /resume   starts it again

Run by rpi-capture-control.service; its settings come from /etc/default/rpi-capture-control.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

log = logging.getLogger("rpi-capture-control")

SERVICE = "mediamtx.service"
SYSTEMCTL = "/usr/bin/systemctl"
# Starting the stream again can take a while on the Zero 2 W; this is the most a request waits.
SYSTEMCTL_TIMEOUT_SECONDS = 30


class Failed(Exception):
    """Raised when the stream could not be switched as asked."""


class Capture:
    """The stream's state, read from systemd, and the switch that pauses and resumes it."""

    def __init__(self, state_dir: Path) -> None:
        # Kept beside the service's own state so it survives a reboot. It holds when the Pause began.
        self._paused_file = state_dir / "paused"

    def status(self) -> dict:
        active = self._is_active()
        if active == "active":
            return {"state": "live", "since": None}
        if active in ("activating", "reloading"):
            return {"state": "starting", "since": None}
        paused_since = self._paused_since()
        if paused_since is not None:
            return {"state": "paused", "since": paused_since}
        # Neither running nor paused: MediaMTX has failed, or was stopped by hand.
        return {"state": "down", "since": None}

    def pause(self) -> dict:
        if self._paused_since() is None:
            self._write_paused(time.time())
        try:
            self._systemctl("disable", "--now")
        except Failed:
            # The stream may still be running, so the Pause is not claimed.
            self._clear_paused()
            raise
        log.info("Paused: the camera and mic are off until Resume.")
        return self.status()

    def resume(self) -> dict:
        self._systemctl("enable", "--now")
        self._clear_paused()
        log.info("Resumed: the stream is starting again.")
        return self.status()

    def _is_active(self) -> str:
        try:
            result = subprocess.run(
                [SYSTEMCTL, "is-active", SERVICE],
                capture_output=True,
                text=True,
                timeout=SYSTEMCTL_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise Failed(f"systemd could not be asked about the stream: {error}") from error
        return result.stdout.strip()

    def _systemctl(self, *action: str) -> None:
        # sudo is allowed exactly these two commands (see install.sh), and nothing else.
        command = ["sudo", "-n", SYSTEMCTL, *action, SERVICE]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=SYSTEMCTL_TIMEOUT_SECONDS)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise Failed(f"'{' '.join(action)}' could not be run: {error}") from error
        if result.returncode != 0:
            reason = (result.stderr or result.stdout).strip() or f"exit status {result.returncode}"
            raise Failed(f"systemd refused '{' '.join(action)}': {reason}")

    def _paused_since(self) -> float | None:
        try:
            return float(self._paused_file.read_text().strip())
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            # Unreadable, but present: still a Pause, of unknown start.
            return 0.0

    def _write_paused(self, since: float) -> None:
        try:
            self._paused_file.write_text(f"{since:.0f}\n")
        except OSError as error:
            raise Failed(f"the Pause could not be remembered in {self._paused_file}: {error}") from error

    def _clear_paused(self) -> None:
        try:
            self._paused_file.unlink(missing_ok=True)
        except OSError as error:
            log.warning("Could not remove %s: %s", self._paused_file, error)


def make_handler(capture: Capture, allowed: list):
    class Handler(BaseHTTPRequestHandler):
        server_version = "rpi-capture-control"

        def do_GET(self) -> None:
            if not self._allowed():
                return
            if self.path != "/status":
                self._reply(404, {"error": f"There is nothing at {self.path}."})
                return
            self._act(capture.status)

        def do_POST(self) -> None:
            if not self._allowed():
                return
            actions = {"/pause": capture.pause, "/resume": capture.resume}
            if self.path not in actions:
                self._reply(404, {"error": f"There is nothing at {self.path}."})
                return
            log.info("%s asked for %s.", self.client_address[0], self.path.lstrip("/"))
            self._act(actions[self.path])

        def _act(self, action) -> None:
            try:
                self._reply(200, action())
            except Failed as error:
                log.error("%s", error)
                self._reply(500, {"error": f"The Pi could not do that: {error}."})

        def _allowed(self) -> bool:
            try:
                address = ipaddress.ip_address(self.client_address[0])
            except ValueError:
                address = None
            # An IPv4 caller can appear as ::ffff:a.b.c.d.
            if address is not None and getattr(address, "ipv4_mapped", None):
                address = address.ipv4_mapped
            if address is not None and any(address in network for network in allowed):
                return True
            log.warning("Refused a request from %s, which is not on the allow-list.", self.client_address[0])
            self._reply(403, {"error": "Only the PC may Pause or Resume the stream."})
            return False

        def _reply(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args) -> None:
            # Status is asked every few seconds; only what matters is logged, above.
            pass

    return Handler


def parse_allowed(raw: str) -> list:
    networks = []
    for item in raw.replace(",", " ").split():
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError as error:
            raise SystemExit(f"rpi-capture-control: '{item}' in CONTROL_ALLOW is not an address: {error}") from error
    return networks


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s", stream=sys.stderr)
    try:
        port = int(os.environ.get("CONTROL_PORT", "8800"))
    except ValueError:
        log.error("CONTROL_PORT must be a port number, but is '%s'.", os.environ["CONTROL_PORT"])
        return 2
    allowed = parse_allowed(os.environ.get("CONTROL_ALLOW", "127.0.0.1"))
    if not allowed:
        log.error("CONTROL_ALLOW is empty, so nobody could Pause or Resume. Set it to the PC's address.")
        return 2
    state_dir = Path(os.environ.get("STATE_DIRECTORY", "/var/lib/rpi-capture"))

    capture = Capture(state_dir)
    try:
        # One request at a time, so a Pause and a Resume can never cross.
        server = HTTPServer(("0.0.0.0", port), make_handler(capture, allowed))
    except OSError as error:
        log.error("Cannot listen on port %d: %s", port, error)
        return 1
    try:
        state = capture.status()["state"]
    except Failed as error:
        state = f"unknown ({error})"
    log.info("Listening on port %d for %s. The stream is %s.", port, ", ".join(map(str, allowed)), state)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
