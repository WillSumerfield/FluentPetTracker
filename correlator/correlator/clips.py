"""Cuts one Clip per Utterance out of Frigate's recording, using Frigate's export feature."""

from __future__ import annotations

import json
import logging
import os
import shutil
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Optional

from .config import Config
from .database import Database

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
RETRY_SECONDS = 30.0
EXPORT_TIMEOUT_SECONDS = 180.0
REQUEST_TIMEOUT_SECONDS = 10.0

# Made once, by hand, in the folder meant for Clips. A folder without it is taken to be the
# wrong place: for one, the empty folder Docker makes when the drive for Clips is not connected.
CLIPS_MARKER = ".fluentpet-clips"


def clip_folder_problem(folder: Path) -> Optional[str]:
    """Why Clips cannot be saved to this folder now, or None when they can."""
    if not folder.is_dir():
        return f"the Clip folder {folder} does not exist"
    if not (folder / CLIPS_MARKER).is_file():
        return (
            f"the Clip folder {folder} has no {CLIPS_MARKER} file, so it may not be the intended "
            "drive (is it connected?)"
        )
    if not os.access(folder, os.W_OK):
        return f"the Clip folder {folder} cannot be written to"
    return None


class FrigateError(Exception):
    """Raised when Frigate cannot be reached or refuses a request."""


class ClipCutter:
    """Moves each closed Utterance's Clip from 'waiting' to 'ready' (or 'failed').

    Progress lives in the database, so an export started before a restart is picked up again.
    """

    def __init__(self, config: Config, database: Database) -> None:
        self._config = config
        self._database = database
        self._not_before: Dict[int, float] = {}  # Utterance id -> earliest time to try again
        self._exporting_since: Dict[int, float] = {}

    def advance(self, now: float) -> None:
        """Start exports that are due and collect the ones that have finished."""
        for utterance in self._database.utterances_with_clip_status("waiting"):
            due = max(
                utterance["clip_ended_at"] + self._config.clip_export_delay_seconds,
                self._not_before.get(utterance["id"], 0.0),
            )
            if now >= due:
                self._start(utterance, now)

        exporting = self._database.utterances_with_clip_status("exporting")
        if not exporting:
            return
        try:
            exports = {export["id"]: export for export in self._request("GET", "/api/exports")}
        except FrigateError as error:
            log.warning("Cannot check on Clip exports: %s", error)
            return
        for utterance in exporting:
            self._collect(utterance, exports.get(utterance["clip_export_id"]), now)

    def _start(self, utterance, now: float) -> None:
        utterance_id = utterance["id"]
        problem = clip_folder_problem(self._config.clips_dir)
        if problem:
            self._give_up_or_retry(utterance, problem, now)
            return
        path = (
            f"/api/export/{self._config.camera}"
            f"/start/{utterance['clip_started_at']:.3f}/end/{utterance['clip_ended_at']:.3f}"
        )
        try:
            reply = self._request("POST", path, {"playback": "realtime", "name": f"utterance-{utterance_id}"})
            export_id = reply.get("export_id") if reply.get("success") else None
            if not export_id:
                raise FrigateError(reply.get("message") or "Frigate did not accept the export")
        except FrigateError as error:
            self._give_up_or_retry(utterance, str(error), now)
            return
        self._database.clip_exporting(utterance_id, export_id)
        self._exporting_since[utterance_id] = now

    def _collect(self, utterance, export: Optional[dict], now: float) -> None:
        utterance_id = utterance["id"]
        started = self._exporting_since.setdefault(utterance_id, now)
        if export is None:
            self._give_up_or_retry(utterance, "Frigate no longer lists the export", now)
            return
        if export.get("in_progress"):
            if now - started > EXPORT_TIMEOUT_SECONDS:
                self._give_up_or_retry(utterance, "the export did not finish in time", now)
            return

        source = self._config.exports_dir / Path(export.get("video_path") or "").name
        target = self._config.clips_dir / f"utterance-{utterance_id:06d}.mp4"
        problem = clip_folder_problem(self._config.clips_dir)
        if problem:
            self._give_up_or_retry(utterance, problem, now)
            return
        try:
            if not source.is_file() or source.stat().st_size == 0:
                raise OSError(f"{source.name} is missing or empty")
            shutil.copyfile(source, target)
        except OSError as error:
            self._give_up_or_retry(utterance, f"cannot copy the exported file: {error}", now)
            return

        self._database.clip_ready(utterance_id, target.name)
        self._exporting_since.pop(utterance_id, None)
        self._not_before.pop(utterance_id, None)
        log.info(
            "Clip saved for Utterance %d: %s (%.0f s)",
            utterance_id,
            target.name,
            utterance["clip_ended_at"] - utterance["clip_started_at"],
        )
        try:
            self._request("POST", "/api/exports/delete", {"ids": [export["id"]]})
        except FrigateError as error:
            log.warning("Clip saved, but Frigate's copy of the export could not be removed: %s", error)

    def _give_up_or_retry(self, utterance, error: str, now: float) -> None:
        utterance_id = utterance["id"]
        self._exporting_since.pop(utterance_id, None)
        if utterance["clip_attempts"] + 1 >= MAX_ATTEMPTS:
            self._database.clip_failed(utterance_id, error)
            self._not_before.pop(utterance_id, None)
            log.error("No Clip for Utterance %d after %d attempts: %s", utterance_id, MAX_ATTEMPTS, error)
        else:
            self._database.clip_retry(utterance_id, error)
            self._not_before[utterance_id] = now + RETRY_SECONDS
            log.warning("Clip for Utterance %d not cut yet (%s); trying again shortly.", utterance_id, error)

    def _request(self, method: str, path: str, body: Optional[dict] = None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self._config.frigate_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as error:
            raise FrigateError(f"Frigate answered {error.code} to {method} {path}") from error
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise FrigateError(f"cannot reach Frigate at {self._config.frigate_url}: {error}") from error
