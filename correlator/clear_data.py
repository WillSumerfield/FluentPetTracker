#!/usr/bin/env python3
"""Clears everything the study has recorded, for a fresh start. Run on this PC:  ./fluentpet.sh clear

Every Press (with its Review Decision), Exchange and Observation Window goes, and every Clip with
its thumbnail. The figures are worked out from Presses, so they start again too. The database is
kept, moved into a cleared-<date-time>/ folder beside it; the Clips are deleted.

Settings, Reference Clips, Frigate's own footage and Home Assistant's history are not touched.

    ./fluentpet.sh clear          show what would go, and ask before clearing it
    ./fluentpet.sh clear --yes    clear without asking

The folders come from frigate/.env, as Docker mounts them. If the Clip folder cannot be reached,
nothing is changed: Clip names start again from 1, so old Clips left behind would be mixed up
with new ones. The correlator and correlator-web services are stopped while the files are moved,
and started again if they were running.
"""

from __future__ import annotations

import argparse
import re
import shlex
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_DIR = ROOT / "frigate"
COMPOSE_ENV = COMPOSE_DIR / ".env"
CLIPS_MARKER = ".fluentpet-clips"
CLIP_FILE = re.compile(r"utterance-\d+\.(mp4|jpg)")
DATABASE_FILES = ("correlator.db", "correlator.db-wal", "correlator.db-shm")
# Started in this order: the recording service makes the empty database the web service opens.
SERVICES = ("correlator", "correlator-web")
CONFIRM_WORD = "clear"


class Stop(Exception):
    """Raised to stop with a message. Whatever the message does not say was left as it was."""


@dataclass
class Study:
    """What is about to be cleared."""

    data_dir: Path
    clips_dir: Path
    presses: int = 0
    exchanges: int = 0
    review_decisions: int = 0
    windows: int = 0
    first: Optional[float] = None
    last: Optional[float] = None
    clip_files: List[Path] = field(default_factory=list)
    clip_bytes: int = 0

    @property
    def database(self) -> Path:
        return self.data_dir / "correlator.db"

    @property
    def clips(self) -> int:
        return sum(1 for path in self.clip_files if path.suffix == ".mp4")

    @property
    def empty(self) -> bool:
        return not self.database.exists() and not self.clip_files


# ---- Reading what is there -----------------------------------------------------------


def read_env(path: Path) -> Dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = shlex.split(value)[0] if value.strip() else ""
    return values


def folders() -> Tuple[Path, Path]:
    if not COMPOSE_ENV.is_file():
        raise Stop("frigate/.env was not found. Run ./fluentpet.sh configure first.")
    try:
        env = read_env(COMPOSE_ENV)
    except (OSError, ValueError) as error:
        raise Stop(f"frigate/.env could not be read: {error}") from error
    data_dir, clips_dir = env.get("FP_DATA_DIR", ""), env.get("FP_CLIPS_DIR", "")
    if not data_dir or not clips_dir:
        raise Stop("frigate/.env has no FP_DATA_DIR or FP_CLIPS_DIR. Run ./fluentpet.sh configure first.")
    return Path(data_dir), Path(clips_dir)


def clip_folder_problem(folder: Path) -> Optional[str]:
    """The recording service's own test (correlator/clips.py), so both agree on the folder."""
    if not folder.is_dir():
        return f"The Clip folder {folder} does not exist"
    if not (folder / CLIPS_MARKER).is_file():
        return f"The Clip folder {folder} has no {CLIPS_MARKER} file, so it may not be the intended drive"
    try:
        probe = folder / ".fluentpet-clear-probe"
        probe.touch()
        probe.unlink()
    except OSError:
        return f"The Clip folder {folder} cannot be written to"
    return None


def survey(data_dir: Path, clips_dir: Path) -> Study:
    study = Study(data_dir, clips_dir)
    try:
        study.clip_files = sorted(path for path in clips_dir.iterdir() if CLIP_FILE.fullmatch(path.name))
    except OSError as error:
        raise Stop(f"The Clip folder {clips_dir} could not be listed: {error}") from error
    for path in study.clip_files:
        try:
            study.clip_bytes += path.stat().st_size
        except OSError:
            pass
    if not study.database.exists():
        return study
    try:
        connection = sqlite3.connect(f"file:{study.database}?mode=ro", uri=True, timeout=10.0)
        try:
            study.presses, study.review_decisions, study.first, study.last = connection.execute(
                "SELECT COUNT(*), COUNT(reviewed_presser), MIN(pressed_at), MAX(pressed_at) FROM presses"
            ).fetchone()
            # The utterances table holds Exchanges (see correlator/database.py).
            study.exchanges = connection.execute("SELECT COUNT(*) FROM utterances").fetchone()[0]
            study.windows = connection.execute("SELECT COUNT(*) FROM observation_windows").fetchone()[0]
        finally:
            connection.close()
    except sqlite3.Error as error:
        # A database too new or too broken to count is still cleared; the summary says so.
        print(f"  ! The study's database could not be counted ({error}). It will still be backed up.")
    return study


# ---- Docker --------------------------------------------------------------------------


def compose(*arguments: str) -> str:
    try:
        result = subprocess.run(
            ["docker", "compose", *arguments], cwd=COMPOSE_DIR, capture_output=True, text=True, check=False
        )
    except FileNotFoundError as error:
        raise Stop("docker was not found. Is Docker Desktop running, with WSL integration on?") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise Stop(f"docker compose {' '.join(arguments)} failed: {detail[-1] if detail else result.returncode}")
    return result.stdout


def running_services() -> List[str]:
    running = set(compose("ps", "--status", "running", "--services").split())
    return [service for service in SERVICES if service in running]


# ---- Clearing ------------------------------------------------------------------------


def checkpoint(database: Path) -> None:
    """Fold the write-ahead log into the database, so the backup is one self-contained file."""
    try:
        connection = sqlite3.connect(str(database), timeout=10.0)
        try:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            connection.close()
    except sqlite3.Error as error:
        # The -wal file is moved with the database anyway, so nothing is lost.
        print(f"  ! The database's log could not be folded in ({error}); it is kept beside the backup.")


def back_up(study: Study, backup: Path) -> List[str]:
    checkpoint(study.database)
    try:
        backup.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        raise Stop(f"The backup folder {backup} could not be made: {error}") from error
    moved = []
    for name in DATABASE_FILES:
        source = study.data_dir / name
        if not source.exists():
            continue
        try:
            source.rename(backup / name)
        except OSError as error:
            raise Stop(f"{name} could not be moved to {backup}: {error}") from error
        moved.append(name)
    return moved


def delete_clips(study: Study) -> Tuple[int, List[str]]:
    deleted, failed = 0, []
    for path in study.clip_files:
        try:
            path.unlink(missing_ok=True)
            deleted += 1
        except OSError as error:
            failed.append(f"{path.name}: {error.strerror or error}")
    return deleted, failed


# ---- Showing it ----------------------------------------------------------------------


def shown(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def size(count: int) -> str:
    amount = float(count)
    for unit in ("bytes", "KB", "MB", "GB"):
        if amount < 1000 or unit == "GB":
            return f"{amount:.0f} {unit}" if unit == "bytes" else f"{amount:.1f} {unit}"
        amount /= 1000
    return f"{amount:.1f} GB"


def plural(count: int, word: str, words: str = "") -> str:
    return f"{count} {word if count == 1 else words or word + 's'}"


def day(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")


def summary(study: Study, backup: Path, running: List[str]) -> None:
    print("Clearing the study's recorded data\n")
    if study.database.exists():
        print(f"  Database  {shown(study.database)}")
        print(
            f"            {plural(study.presses, 'Press', 'Presses')} in "
            f"{plural(study.exchanges, 'Exchange')}, {plural(study.review_decisions, 'Review Decision')}, "
            f"{plural(study.windows, 'Observation Window')}"
        )
        if study.first is not None and study.last is not None:
            print(f"            {day(study.first)} → {day(study.last)}")
        print(f"            → backed up to {shown(backup)}/")
    else:
        print(f"  Database  {shown(study.database)}  (none yet)")
    print(f"  Clips     {shown(study.clips_dir)}")
    if study.clip_files:
        print(f"            {plural(study.clips, 'Clip')} with thumbnails, {size(study.clip_bytes)}  → deleted")
    else:
        print("            none")
    print()
    if running:
        print(f"  {' and '.join(running)} will be stopped, then started again.")
    else:
        print("  The Correlator is not running, so nothing needs stopping.")
    print("  Settings, Reference Clips, Frigate's footage and Home Assistant's history are not touched.\n")


def confirmed() -> bool:
    try:
        answer = input(f"  Type '{CONFIRM_WORD}' to go on: ")
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer.strip().lower() == CONFIRM_WORD


# ---- Main ----------------------------------------------------------------------------


def clear(study: Study, backup: Path, running: List[str]) -> int:
    """Stop, move, delete, start. The services are started again whatever happens in between."""
    done: List[str] = []
    problems: List[str] = []
    if running:
        print(f"  Stopping {' and '.join(running)}…")
        try:
            compose("stop", *running)
        except Stop:
            # One may have stopped before the other failed: leave them as they were found.
            for service in running:
                try:
                    compose("start", service)
                except Stop:
                    pass
            raise
    try:
        if study.database.exists():
            moved = back_up(study, backup)
            done.append(f"✓ Database backed up to {shown(backup)}/ ({', '.join(moved)})")
        deleted, failed = delete_clips(study)
        if study.clip_files:
            whole = "" if failed else f", {size(study.clip_bytes)}"
            done.append(f"✓ {plural(study.clips, 'Clip')} deleted, with thumbnails ({plural(deleted, 'file')}{whole})")
        problems.extend(f"✗ Not deleted: {line}" for line in failed)
    except Stop as stop:
        problems.append(f"✗ {stop}")
    finally:
        for service in running:
            print(f"  Starting {service}…")
            try:
                compose("start", service)
            except Stop as stop:
                problems.append(f"✗ {service} could not be started again ({stop}). Run ./fluentpet.sh up")

    print()
    for line in done:
        print(f"  {line}")
    for line in problems:
        print(f"  {line}", file=sys.stderr)
    if problems:
        print("\n✗ The study was only partly cleared. Everything not listed above was left as it was.", file=sys.stderr)
        return 1
    print("\n✓ Cleared. The study starts afresh from the next Press.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Clear everything the study has recorded, for a fresh start.")
    parser.add_argument("--yes", action="store_true", help="clear without asking first")
    arguments = parser.parse_args()

    try:
        data_dir, clips_dir = folders()
        problem = clip_folder_problem(clips_dir)
        if problem:
            raise Stop(f"{problem}. Connect the drive and try again. Nothing was changed.")
        study = survey(data_dir, clips_dir)
        if study.empty:
            print("✓ There is nothing to clear: no database and no Clips yet.")
            return 0
        running = running_services()
    except Stop as stop:
        print(f"✗ {stop}", file=sys.stderr)
        return 1

    backup = data_dir / f"cleared-{datetime.now():%Y-%m-%d-%H%M%S}"
    summary(study, backup, running)
    if not arguments.yes and not confirmed():
        print("Nothing was changed.")
        return 1

    print()
    try:
        return clear(study, backup, running)
    except Stop as stop:
        # Only stopping the services can get here, before any file was touched.
        print(f"✗ {stop}. Nothing was changed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
