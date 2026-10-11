"""What the web pages may do with the study's database: read it, and record Review Decisions.

The recording service owns the database. This module never changes anything but the two
review columns of a Press.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

DECISIONS = ("cat", "human", "discarded")

# The Presser the study counts: a Review Decision when there is one, otherwise the automatic answer.
COUNTED_PRESSER = "COALESCE(reviewed_presser, presser)"
AWAITING_REVIEW = "presser = 'ambiguous' AND reviewed_presser IS NULL"


class PressNotFound(Exception):
    """Raised when a Review Decision names a Press that does not exist."""


class Store:
    def __init__(self, path: Path, heartbeat_seconds: float) -> None:
        self._path = path
        self._heartbeat_seconds = heartbeat_seconds

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # mode=rw: fail rather than create an empty database when the real one is missing.
        connection = sqlite3.connect(f"file:{self._path}?mode=rw", uri=True, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    # ---- Review Decisions -------------------------------------------------------

    def set_review(self, press_id: int, decision: Optional[str]) -> dict:
        """Record a Review Decision, or withdraw it with None. Returns the Press's Utterance."""
        if decision is not None and decision not in DECISIONS:
            raise ValueError(f"a Review Decision must be one of {', '.join(DECISIONS)}, or null to withdraw it")
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE presses SET reviewed_presser = ?, reviewed_at = ? WHERE id = ?",
                (decision, time.time() if decision is not None else None, press_id),
            )
            if cursor.rowcount == 0:
                raise PressNotFound(f"there is no Press {press_id}")
            utterance_id = connection.execute(
                "SELECT utterance_id FROM presses WHERE id = ?", (press_id,)
            ).fetchone()[0]
            return self._utterances(connection, "id = ?", (utterance_id,), 1)[0]

    # ---- Utterances -------------------------------------------------------------

    def utterances(self, limit: int, before_id: Optional[int] = None, awaiting_review: bool = False) -> List[dict]:
        conditions, parameters = ["1 = 1"], []
        if before_id is not None:
            conditions.append("id < ?")
            parameters.append(before_id)
        if awaiting_review:
            conditions.append(f"id IN (SELECT utterance_id FROM presses WHERE {AWAITING_REVIEW})")
        with self._connect() as connection:
            return self._utterances(connection, " AND ".join(conditions), tuple(parameters), limit)

    def clip_path(self, utterance_id: int) -> Optional[str]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT clip_path FROM utterances WHERE id = ? AND clip_status = 'ready'", (utterance_id,)
            ).fetchone()
        return row["clip_path"] if row else None

    @staticmethod
    def _utterances(connection: sqlite3.Connection, where: str, parameters: tuple, limit: int) -> List[dict]:
        rows = connection.execute(
            f"SELECT * FROM utterances WHERE {where} ORDER BY id DESC LIMIT ?", parameters + (limit,)
        ).fetchall()
        if not rows:
            return []
        marks = ", ".join("?" * len(rows))
        presses: Dict[int, List[dict]] = {row["id"]: [] for row in rows}
        for press in connection.execute(
            f"SELECT * FROM presses WHERE utterance_id IN ({marks}) ORDER BY utterance_id, position",
            tuple(row["id"] for row in rows),
        ):
            presses[press["utterance_id"]].append(
                {
                    "id": press["id"],
                    "position": press["position"],
                    "word": press["word"],
                    "pressed_at": press["pressed_at"],
                    "presser": press["reviewed_presser"] or press["presser"],
                    "automatic_presser": press["presser"],
                    "ambiguity": press["ambiguity"],
                    "review_decision": press["reviewed_presser"],
                    "reviewed_at": press["reviewed_at"],
                    "word_uncertain": bool(press["word_uncertain"]),
                    "word_score": press["word_score"],
                }
            )
        return [
            {
                "id": row["id"],
                "started_at": row["started_at"],
                "closed_at": row["closed_at"],
                "clip_status": row["clip_status"],
                "clip_url": f"clips/{row['id']}" if row["clip_status"] == "ready" else None,
                "clip_error": row["clip_error"] if row["clip_status"] == "failed" else None,
                "presses": presses[row["id"]],
            }
            for row in rows
        ]

    # ---- Figures ----------------------------------------------------------------

    def summary(self) -> dict:
        now = time.time()
        midnight = datetime.combine(date.today(), datetime.min.time()).timestamp()
        with self._connect() as connection:
            today = {
                row["who"]: row["presses"]
                for row in connection.execute(
                    f"SELECT {COUNTED_PRESSER} AS who, COUNT(*) AS presses FROM presses"
                    " WHERE pressed_at >= ? GROUP BY who",
                    (midnight,),
                )
            }
            awaiting = connection.execute(f"SELECT COUNT(*) FROM presses WHERE {AWAITING_REVIEW}").fetchone()[0]
            vocabulary = connection.execute(
                f"SELECT COUNT(DISTINCT word) FROM presses WHERE {COUNTED_PRESSER} = 'cat'"
            ).fetchone()[0]
            last = connection.execute(
                f"SELECT word, pressed_at FROM presses WHERE {COUNTED_PRESSER} = 'cat' ORDER BY pressed_at DESC LIMIT 1"
            ).fetchone()
            window = connection.execute(
                "SELECT * FROM observation_windows WHERE ended_at IS NULL ORDER BY id DESC LIMIT 1"
            ).fetchone()
            windows = self._windows(connection, midnight, now)

        # A window whose heartbeat has stopped belongs to a recording service that is no longer running.
        observing = window is not None and now - window["last_seen_at"] <= 3 * self._heartbeat_seconds
        observed_hours = sum(end - start for start, end in windows) / 3600
        cat_today = today.get("cat", 0)
        return {
            "observing": observing,
            "observing_since": window["started_at"] if observing else None,
            "observed_hours_today": round(observed_hours, 2),
            "cat_presses_today": cat_today,
            "cat_presses_per_hour_today": round(cat_today / observed_hours, 2) if observed_hours >= 0.05 else None,
            "human_presses_today": today.get("human", 0),
            "ambiguous_presses_today": today.get("ambiguous", 0),
            "awaiting_review": awaiting,
            "vocabulary_size": vocabulary,
            "last_cat_word": last["word"] if last else None,
            "last_cat_press_at": last["pressed_at"] if last else None,
        }

    def history(self, days: int) -> dict:
        """Figures for the last `days` days including today; 0 means the whole study."""
        now = time.time()
        today = date.today()
        with self._connect() as connection:
            presses = connection.execute(
                f"SELECT pressed_at, word, {COUNTED_PRESSER} AS who FROM presses ORDER BY pressed_at"
            ).fetchall()
            all_windows = self._windows(connection, 0.0, now)

        earliest = min(
            [press["pressed_at"] for press in presses[:1]] + [start for start, _end in all_windows[:1]], default=now
        )
        first_day = date.fromtimestamp(earliest)
        if days > 0:
            first_day = max(first_day, today - timedelta(days=days - 1))
        range_start = datetime.combine(first_day, datetime.min.time()).timestamp()

        observed_by_day: Dict[date, float] = {}
        observed_by_hour = [0.0] * 24
        for start, end in all_windows:
            for piece_start, piece_end in _split_by_hour(max(start, range_start), end):
                moment = datetime.fromtimestamp(piece_start)
                observed_by_day[moment.date()] = observed_by_day.get(moment.date(), 0.0) + piece_end - piece_start
                observed_by_hour[moment.hour] += piece_end - piece_start

        cat_by_day: Dict[date, int] = {}
        cat_by_hour = [0] * 24
        new_words_by_day: Dict[date, List[str]] = {}
        words: Dict[str, dict] = {}
        known_words = set()
        for press in presses:
            moment = datetime.fromtimestamp(press["pressed_at"])
            is_cat = press["who"] == "cat"
            # Vocabulary growth counts from the start of the study, whatever range is shown.
            if is_cat and press["word"] not in known_words:
                known_words.add(press["word"])
                new_words_by_day.setdefault(moment.date(), []).append(press["word"])
            if press["pressed_at"] < range_start or press["who"] == "discarded":
                continue
            entry = words.setdefault(
                press["word"], {"word": press["word"], "cat": 0, "human": 0, "ambiguous": 0, "last_cat_press_at": None}
            )
            entry[press["who"]] += 1
            if is_cat:
                entry["last_cat_press_at"] = press["pressed_at"]
                cat_by_day[moment.date()] = cat_by_day.get(moment.date(), 0) + 1
                cat_by_hour[moment.hour] += 1

        vocabulary = sum(len(new) for day, new in new_words_by_day.items() if day < first_day)
        by_day = []
        for offset in range((today - first_day).days + 1):
            day = first_day + timedelta(days=offset)
            hours = observed_by_day.get(day, 0.0) / 3600
            vocabulary += len(new_words_by_day.get(day, []))
            by_day.append(
                {
                    "date": day.isoformat(),
                    "observed_hours": round(hours, 2),
                    "cat_presses": cat_by_day.get(day, 0),
                    "cat_presses_per_hour": _rate(cat_by_day.get(day, 0), hours),
                    "vocabulary_size": vocabulary,
                    "new_words": new_words_by_day.get(day, []),
                }
            )
        by_hour = [
            {
                "hour": hour,
                "observed_hours": round(observed_by_hour[hour] / 3600, 2),
                "cat_presses": cat_by_hour[hour],
                "cat_presses_per_hour": _rate(cat_by_hour[hour], observed_by_hour[hour] / 3600),
            }
            for hour in range(24)
        ]
        total_hours = sum(observed_by_day.values()) / 3600
        total_cat = sum(cat_by_day.values())
        return {
            "first_day": first_day.isoformat(),
            "observed_hours": round(total_hours, 2),
            "cat_presses": total_cat,
            "cat_presses_per_hour": _rate(total_cat, total_hours),
            "by_day": by_day,
            "by_hour": by_hour,
            "words": sorted(words.values(), key=lambda entry: (-entry["cat"], entry["word"])),
        }

    @staticmethod
    def _windows(connection: sqlite3.Connection, start: float, end: float) -> List[Tuple[float, float]]:
        """Observation Windows as (start, end) pairs, cut to the given span, oldest first."""
        spans = []
        for row in connection.execute(
            "SELECT started_at, COALESCE(ended_at, last_seen_at) AS ended FROM observation_windows"
            " WHERE COALESCE(ended_at, last_seen_at) > ? AND started_at < ? ORDER BY started_at",
            (start, end),
        ):
            span = (max(row["started_at"], start), min(row["ended"], end))
            if span[1] > span[0]:
                spans.append(span)
        return spans


def _rate(presses: int, hours: float) -> Optional[float]:
    """Presses per observed hour; None when too little was observed for the figure to mean anything."""
    return round(presses / hours, 2) if hours >= 0.05 else None


def _split_by_hour(start: float, end: float) -> Iterator[Tuple[float, float]]:
    """Cut a span into pieces that each lie inside one clock hour, in local time."""
    while start < end:
        moment = datetime.fromtimestamp(start)
        next_hour = start - (moment.minute * 60 + moment.second + moment.microsecond / 1e6) + 3600
        piece_end = min(end, next_hour)
        yield start, piece_end
        start = piece_end
