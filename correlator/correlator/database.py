"""The study's database: Presses, Utterances and Observation Windows, in one SQLite file.

All times are stored as seconds since 1970 (UTC).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable, List, Optional

SCHEMA = """
-- Holds Exchanges, despite its name: runs of Presses by anyone, one Clip each. The Utterances
-- inside an Exchange are not stored; they follow from who is counted as each Press's Presser.
CREATE TABLE IF NOT EXISTS utterances (
    id              INTEGER PRIMARY KEY,
    started_at      REAL NOT NULL,           -- time of the first Press
    last_press_at   REAL NOT NULL,
    closed_at       REAL,                    -- NULL while more Presses may still join
    clip_status     TEXT NOT NULL DEFAULT 'waiting'
                    CHECK (clip_status IN ('waiting', 'exporting', 'ready', 'failed')),
    clip_path       TEXT,                    -- relative to the data folder
    clip_started_at REAL,
    clip_ended_at   REAL,
    clip_export_id  TEXT,
    clip_attempts   INTEGER NOT NULL DEFAULT 0,
    clip_error      TEXT
);

CREATE TABLE IF NOT EXISTS presses (
    id               INTEGER PRIMARY KEY,
    utterance_id     INTEGER NOT NULL REFERENCES utterances (id),
    position         INTEGER NOT NULL,       -- order within the Utterance, from 1
    pressed_at       REAL NOT NULL,
    word             TEXT NOT NULL,
    word_score       REAL,
    word_uncertain   INTEGER NOT NULL DEFAULT 0,
    reference_clip   TEXT,
    presser          TEXT NOT NULL CHECK (presser IN ('cat', 'human', 'ambiguous')),
    ambiguity        TEXT CHECK (ambiguity IN ('both', 'nobody')),
    subjects_seen    TEXT NOT NULL,          -- JSON list of who was in the Board Zone
    reviewed_presser TEXT CHECK (reviewed_presser IN ('cat', 'human', 'discarded')),
    reviewed_at      REAL,
    UNIQUE (utterance_id, position)
);

CREATE TABLE IF NOT EXISTS observation_windows (
    id           INTEGER PRIMARY KEY,
    started_at   REAL NOT NULL,
    last_seen_at REAL NOT NULL,              -- heartbeat; becomes the end after a crash
    ended_at     REAL                        -- NULL while the window is open
);

CREATE INDEX IF NOT EXISTS presses_pressed_at ON presses (pressed_at);
CREATE INDEX IF NOT EXISTS utterances_started_at ON utterances (started_at);
"""


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(path), isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(SCHEMA)

    def close(self) -> None:
        self._connection.close()

    # ---- Utterances and Presses -------------------------------------------------

    def open_utterance(self) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM utterances WHERE closed_at IS NULL ORDER BY id DESC LIMIT 1")

    def add_press(
        self,
        utterance_id: Optional[int],
        pressed_at: float,
        word: str,
        word_score: Optional[float],
        word_uncertain: bool,
        reference_clip: Optional[str],
        presser: str,
        ambiguity: Optional[str],
        subjects_seen: Iterable[str],
    ) -> int:
        """Store a Press, starting a new Utterance when no utterance_id is given. Returns the Utterance id."""
        with self._connection:
            self._connection.execute("BEGIN")
            if utterance_id is None:
                cursor = self._connection.execute(
                    "INSERT INTO utterances (started_at, last_press_at) VALUES (?, ?)", (pressed_at, pressed_at)
                )
                utterance_id = int(cursor.lastrowid)
            else:
                self._connection.execute(
                    "UPDATE utterances SET last_press_at = ? WHERE id = ?", (pressed_at, utterance_id)
                )
            position = self._connection.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM presses WHERE utterance_id = ?", (utterance_id,)
            ).fetchone()[0]
            self._connection.execute(
                "INSERT INTO presses (utterance_id, position, pressed_at, word, word_score, word_uncertain,"
                " reference_clip, presser, ambiguity, subjects_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    utterance_id,
                    position,
                    pressed_at,
                    word,
                    word_score,
                    int(word_uncertain),
                    reference_clip,
                    presser,
                    ambiguity,
                    json.dumps(sorted(subjects_seen)),
                ),
            )
        return utterance_id

    def close_utterance(self, utterance_id: int, closed_at: float, clip_started_at: float) -> None:
        self._connection.execute(
            "UPDATE utterances SET closed_at = ?, clip_started_at = ?, clip_ended_at = ? WHERE id = ?",
            (closed_at, clip_started_at, closed_at, utterance_id),
        )

    def presses_of(self, utterance_id: int) -> List[sqlite3.Row]:
        return self._all("SELECT * FROM presses WHERE utterance_id = ? ORDER BY position", (utterance_id,))

    def recent_utterances(self, limit: int) -> List[sqlite3.Row]:
        return self._all("SELECT * FROM utterances ORDER BY id DESC LIMIT ?", (limit,))

    def press_counts(self) -> List[sqlite3.Row]:
        return self._all(
            "SELECT presser, COALESCE(ambiguity, '') AS ambiguity, word_uncertain, COUNT(*) AS presses"
            " FROM presses GROUP BY presser, ambiguity, word_uncertain ORDER BY presser, ambiguity, word_uncertain"
        )

    # ---- Clips ------------------------------------------------------------------

    def utterances_with_clip_status(self, status: str) -> List[sqlite3.Row]:
        return self._all(
            "SELECT * FROM utterances WHERE closed_at IS NOT NULL AND clip_status = ? ORDER BY id", (status,)
        )

    def clip_exporting(self, utterance_id: int, export_id: str) -> None:
        self._connection.execute(
            "UPDATE utterances SET clip_status = 'exporting', clip_export_id = ? WHERE id = ?",
            (export_id, utterance_id),
        )

    def clip_ready(self, utterance_id: int, clip_path: str) -> None:
        self._connection.execute(
            "UPDATE utterances SET clip_status = 'ready', clip_path = ?, clip_error = NULL WHERE id = ?",
            (clip_path, utterance_id),
        )

    def clip_retry(self, utterance_id: int, error: str) -> None:
        self._connection.execute(
            "UPDATE utterances SET clip_status = 'waiting', clip_export_id = NULL, clip_error = ?,"
            " clip_attempts = clip_attempts + 1 WHERE id = ?",
            (error, utterance_id),
        )

    def clip_failed(self, utterance_id: int, error: str) -> None:
        self._connection.execute(
            "UPDATE utterances SET clip_status = 'failed', clip_export_id = NULL, clip_error = ? WHERE id = ?",
            (error, utterance_id),
        )

    # ---- Observation Windows ----------------------------------------------------

    def open_window(self) -> Optional[sqlite3.Row]:
        return self._one("SELECT * FROM observation_windows WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1")

    def start_window(self, now: float) -> int:
        cursor = self._connection.execute(
            "INSERT INTO observation_windows (started_at, last_seen_at) VALUES (?, ?)", (now, now)
        )
        return int(cursor.lastrowid)

    def touch_window(self, window_id: int, now: float) -> None:
        self._connection.execute("UPDATE observation_windows SET last_seen_at = ? WHERE id = ?", (now, window_id))

    def end_window(self, window_id: int, ended_at: float) -> None:
        self._connection.execute(
            "UPDATE observation_windows SET last_seen_at = ?, ended_at = ? WHERE id = ?",
            (ended_at, ended_at, window_id),
        )

    def end_abandoned_windows(self) -> int:
        """End windows left open by a crash, at their last heartbeat. Returns how many."""
        cursor = self._connection.execute(
            "UPDATE observation_windows SET ended_at = last_seen_at WHERE ended_at IS NULL"
        )
        return cursor.rowcount

    def recent_windows(self, limit: int) -> List[sqlite3.Row]:
        return self._all("SELECT * FROM observation_windows ORDER BY id DESC LIMIT ?", (limit,))

    # ---- Helpers ----------------------------------------------------------------

    def _one(self, sql: str, parameters: tuple = ()) -> Optional[sqlite3.Row]:
        return self._connection.execute(sql, parameters).fetchone()

    def _all(self, sql: str, parameters: tuple = ()) -> List[sqlite3.Row]:
        return self._connection.execute(sql, parameters).fetchall()
