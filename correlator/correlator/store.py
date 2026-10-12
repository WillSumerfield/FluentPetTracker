"""What the web pages may do with the study's database: read it, and record Review Decisions.

The recording service owns the database. This module never changes anything but the two
review columns of a Press.

The table named `utterances` holds Exchanges: runs of Presses separated by a quiet gap, each
with one Clip. The Utterances inside an Exchange are worked out when it is read (see metrics).
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from . import metrics

DECISIONS = ("cat", "human", "discarded")

# The Presser the study counts: a Review Decision when there is one, otherwise the automatic answer.
COUNTED_PRESSER = "COALESCE(reviewed_presser, presser)"
AWAITING_REVIEW = "presser = 'ambiguous' AND reviewed_presser IS NULL"


class NotFound(Exception):
    """Raised when a request names a Press or an Exchange that does not exist."""


class Store:
    def __init__(self, path: Path, heartbeat_seconds: float, response_seconds: float, counted_day_hours: float) -> None:
        self._path = path
        self._heartbeat_seconds = heartbeat_seconds
        self._response_seconds = response_seconds
        self._counted_day_hours = counted_day_hours

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

    def review_press(self, press_id: int, decision: Optional[str]) -> dict:
        """Record a Review Decision, or withdraw it with None. Returns the Press's Exchange."""
        _check(decision)
        with self._connect() as connection:
            row = connection.execute("SELECT utterance_id FROM presses WHERE id = ?", (press_id,)).fetchone()
            if row is None:
                raise NotFound(f"there is no Press {press_id}")
            connection.execute(
                "UPDATE presses SET reviewed_presser = ?, reviewed_at = ? WHERE id = ?",
                (decision, _decided_at(decision), press_id),
            )
            return self._exchanges(connection, "id = ?", (row["utterance_id"],))[0]

    def review_exchange(self, exchange_id: int, decision: Optional[str]) -> dict:
        """Give every Press of one Exchange the same Review Decision, or withdraw them all."""
        _check(decision)
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE presses SET reviewed_presser = ?, reviewed_at = ? WHERE utterance_id = ?",
                (decision, _decided_at(decision), exchange_id),
            )
            if cursor.rowcount == 0:
                raise NotFound(f"there is no Exchange {exchange_id}")
            return self._exchanges(connection, "id = ?", (exchange_id,))[0]

    def next_for_review(self, after_press_id: int = 0) -> dict:
        """The oldest Ambiguous Press with no Review Decision, and how many there are.

        `after_press_id` passes over that Press and every older one, for skipping.
        """
        with self._connect() as connection:
            remaining = connection.execute(f"SELECT COUNT(*) FROM presses WHERE {AWAITING_REVIEW}").fetchone()[0]
            row = connection.execute(
                f"SELECT id, utterance_id FROM presses WHERE {AWAITING_REVIEW} AND id > ? ORDER BY id LIMIT 1",
                (after_press_id,),
            ).fetchone()
            if row is None:
                return {"remaining": remaining, "press_id": None, "exchange": None}
            exchange = self._exchanges(connection, "id = ?", (row["utterance_id"],))[0]
        return {"remaining": remaining, "press_id": row["id"], "exchange": exchange}

    # ---- Exchanges --------------------------------------------------------------

    def exchange(self, exchange_id: int) -> dict:
        with self._connect() as connection:
            found = self._exchanges(connection, "id = ?", (exchange_id,))
        if not found:
            raise NotFound(f"there is no Exchange {exchange_id}")
        return found[0]

    def clip_path(self, exchange_id: int) -> Optional[str]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT clip_path FROM utterances WHERE id = ? AND clip_status = 'ready'", (exchange_id,)
            ).fetchone()
        return row["clip_path"] if row else None

    @staticmethod
    def _exchanges(connection: sqlite3.Connection, where: str, parameters: tuple) -> List[dict]:
        """Exchanges with their Presses and the Utterances those make, oldest first."""
        rows = connection.execute(
            f"SELECT * FROM utterances WHERE {where} ORDER BY started_at, id", parameters
        ).fetchall()
        if not rows:
            return []
        presses: Dict[int, List[dict]] = {row["id"]: [] for row in rows}
        for press in connection.execute(
            f"SELECT * FROM presses WHERE utterance_id IN (SELECT id FROM utterances WHERE {where})"
            " ORDER BY utterance_id, position",
            parameters,
        ):
            presses[press["utterance_id"]].append(
                {
                    "id": press["id"],
                    "exchange_id": press["utterance_id"],
                    "word": press["word"],
                    "pressed_at": press["pressed_at"],
                    "presser": press["reviewed_presser"] or press["presser"],
                    "automatic_presser": press["presser"],
                    "ambiguity": press["ambiguity"],
                    "review_decision": press["reviewed_presser"],
                    "word_uncertain": bool(press["word_uncertain"]),
                }
            )
        exchanges = []
        for row in rows:
            ready = row["clip_status"] == "ready"
            exchanges.append(
                {
                    "id": row["id"],
                    "started_at": row["started_at"],
                    "ended_at": row["last_press_at"],
                    "open": row["closed_at"] is None,
                    "clip_status": row["clip_status"],
                    "clip_url": f"clips/{row['id']}" if ready else None,
                    "clip_started_at": row["clip_started_at"] if ready else None,
                    "clip_ended_at": row["clip_ended_at"] if ready else None,
                    "clip_error": row["clip_error"] if row["clip_status"] == "failed" else None,
                    "presses": presses[row["id"]],
                    "utterances": [
                        {key: utterance[key] for key in ("presser", "press_ids", "words", "started_at", "ended_at")}
                        for utterance in metrics.split_utterances(presses[row["id"]])
                    ],
                }
            )
        return exchanges

    # ---- Figures ----------------------------------------------------------------

    def day(self, day: date) -> dict:
        """One day for the Daily Summary: its Exchanges, when it was observed, and its figures."""
        start = metrics.start_of(day)
        end = metrics.start_of(day + timedelta(days=1))
        now = time.time()
        with self._connect() as connection:
            exchanges = self._exchanges(connection, "started_at >= ? AND started_at < ?", (start, end))
            windows = self._windows(connection, start, min(end, now))
            earliest = connection.execute(
                "SELECT MIN(first) FROM (SELECT MIN(started_at) AS first FROM utterances"
                " UNION ALL SELECT MIN(started_at) FROM observation_windows)"
            ).fetchone()[0]

        utterances = [utterance for exchange in exchanges for utterance in exchange["utterances"]]
        presses = [press for exchange in exchanges for press in exchange["presses"]]
        figures = {"observed_hours": round(sum(e - s for s, e in windows) / 3600, 1)}
        for presser in metrics.PRESSERS:
            own = [utterance for utterance in utterances if utterance["presser"] == presser]
            longest = max(own, key=lambda utterance: len(utterance["words"]), default=None)
            figures[presser] = {
                "words": sum(len(utterance["words"]) for utterance in own),
                "utterances": len(own),
                "distinct_words": len({word for utterance in own for word in utterance["words"]}),
                "longest": longest["words"] if longest else [],
            }
        figures["awaiting_review"] = sum(
            1 for press in presses if press["automatic_presser"] == "ambiguous" and press["review_decision"] is None
        )
        figures["discarded"] = sum(1 for press in presses if press["presser"] == "discarded")
        today = date.today()
        return {
            "date": day.isoformat(),
            "start": start,
            "end": end,
            "now": now,
            "today": today.isoformat(),
            "first_day": date.fromtimestamp(earliest).isoformat() if earliest else today.isoformat(),
            "counted": figures["observed_hours"] > self._counted_day_hours,
            "counted_day_hours": self._counted_day_hours,
            "observed": [{"start": window_start, "end": window_end} for window_start, window_end in windows],
            "figures": figures,
            "exchanges": exchanges,
        }

    def metrics(self, period: str, anchor: date) -> dict:
        now = time.time()
        with self._connect() as connection:
            presses = [
                dict(row)
                for row in connection.execute(
                    f"SELECT id, utterance_id AS exchange_id, word, pressed_at, {COUNTED_PRESSER} AS presser"
                    " FROM presses ORDER BY utterance_id, position"
                )
            ]
            windows = self._windows(connection, 0.0, now)
        return metrics.build(
            presses, windows, period, anchor, date.today(), self._response_seconds, self._counted_day_hours
        )

    def summary(self) -> dict:
        """The few figures Home Assistant polls, and whether the pipeline is observing."""
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


def _check(decision: Optional[str]) -> None:
    if decision is not None and decision not in DECISIONS:
        raise ValueError(f"a Review Decision must be one of {', '.join(DECISIONS)}, or null to withdraw it")


def _decided_at(decision: Optional[str]) -> Optional[float]:
    return time.time() if decision is not None else None
