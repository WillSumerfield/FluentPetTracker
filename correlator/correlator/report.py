"""Prints what the database holds: recent Utterances, their Presses, and Observation Windows.

Run with: python -m correlator.report
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from typing import Optional

from .config import Config, ConfigError
from .database import Database


def _clock(timestamp: Optional[float]) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S") if timestamp else "-"


def _presser(press: sqlite3.Row) -> str:
    if press["presser"] == "ambiguous":
        return f"ambiguous ({press['ambiguity']})"
    return press["presser"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Show what the Correlator has recorded.")
    parser.add_argument("--utterances", type=int, default=10, help="how many recent Utterances to show (default 10)")
    arguments = parser.parse_args()

    try:
        config = Config.from_environment()
        database = Database(config.database_path)
    except (ConfigError, sqlite3.Error, OSError) as error:
        print(f"Cannot read the database: {error}", file=sys.stderr)
        return 1

    try:
        print("Observation Windows (most recent first)")
        windows = database.recent_windows(5)
        for window in windows:
            end = window["ended_at"] or window["last_seen_at"]
            state = "ended" if window["ended_at"] else "open"
            minutes = (end - window["started_at"]) / 60
            print(f"  {_clock(window['started_at'])}  to  {_clock(end)}  {minutes:7.1f} min  {state}")
        if not windows:
            print("  none yet")

        print("\nPresses by Presser")
        counts = database.press_counts()
        for row in counts:
            presser = f"{row['presser']} ({row['ambiguity']})" if row["ambiguity"] else row["presser"]
            word = "uncertain Word" if row["word_uncertain"] else "confident Word"
            print(f"  {presser:<20}  {word:<14}  {row['presses']:>5}")
        if not counts:
            print("  none yet")

        print(f"\nUtterances (most recent {arguments.utterances})")
        utterances = database.recent_utterances(arguments.utterances)
        for utterance in utterances:
            state = "closed" if utterance["closed_at"] else "open"
            clip = utterance["clip_path"] or f"clip {utterance['clip_status']}"
            if utterance["clip_error"] and utterance["clip_status"] != "ready":
                clip += f" ({utterance['clip_error']})"
            print(f"  #{utterance['id']:<5} {_clock(utterance['started_at'])}  {state:<6}  {clip}")
            for press in database.presses_of(utterance["id"]):
                flag = "  uncertain Word" if press["word_uncertain"] else ""
                print(
                    f"         {press['position']}. {press['word']:<14} {_clock(press['pressed_at'])[11:]}"
                    f"  {_presser(press):<18} score {press['word_score']:.2f}{flag}"
                )
        if not utterances:
            print("  none yet")
    finally:
        database.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
