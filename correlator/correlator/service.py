"""The Correlator service: turns Word events and Board Zone presence into Press records.

Run with: python -m correlator.service
"""

from __future__ import annotations

import json
import logging
import queue
import signal
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import paho.mqtt.client as mqtt

from .clips import ClipCutter, clip_folder_problem
from .config import Config, ConfigError
from .database import Database
from .metrics import split_utterances
from .presence import AMBIGUOUS, PresenceTracker, attribute

log = logging.getLogger("correlator")

TICK_SECONDS = 1.0
# An Exchange found closed this long after the fact (after a crash, say) is not announced:
# an Utterance Alert about something long over would mislead.
ANNOUNCE_WITHIN_SECONDS = 300.0


@dataclass(frozen=True)
class WordEvent:
    """A Word heard by Word Detection, waiting for Frigate's view of the same moment to arrive."""

    pressed_at: float
    word: str
    score: Optional[float]
    uncertain: bool
    reference: Optional[str]
    decide_at: float


class Service:
    def __init__(self, config: Config, database: Database) -> None:
        self._config = config
        self._database = database
        self._presence = PresenceTracker(config.camera, config.zone)
        self._clips = ClipCutter(config, database)
        self._inbox: "queue.Queue[tuple]" = queue.Queue()
        self._stopping = threading.Event()
        self._waiting: List[WordEvent] = []
        self._broker_connected = False
        self._frigate_online = False
        self._word_detection_online = False
        self._last_heartbeat = 0.0
        self._events_topic = f"{config.frigate_topic_prefix}/events"
        self._frigate_status_topic = f"{config.frigate_topic_prefix}/available"
        self._mqtt = self._build_mqtt_client()

    def run(self) -> None:
        problem = clip_folder_problem(self._config.clips_dir)
        if problem:
            log.warning("Clips cannot be saved: %s. Presses are still recorded.", problem)
        else:
            log.info("Clips are saved to %s.", self._config.clips_dir)
        abandoned = self._database.end_abandoned_windows()
        if abandoned:
            log.warning("Ended %d Observation Window(s) left open by an earlier crash.", abandoned)
        self._close_utterance_if_due(time.time(), starting_up=True)

        self._mqtt.connect_async(self._config.mqtt_host, self._config.mqtt_port)
        self._mqtt.loop_start()
        last_tick = 0.0
        try:
            while not self._stopping.is_set():
                try:
                    self._handle(self._inbox.get(timeout=TICK_SECONDS))
                except queue.Empty:
                    pass
                now = time.time()
                if now - last_tick >= TICK_SECONDS:
                    last_tick = now
                    self._tick(now)
        finally:
            self._mqtt.loop_stop()
            self._mqtt.disconnect()
            self._end_window(time.time(), "the Correlator is stopping")
            log.info("Stopped.")

    def stop(self, *_signal_args: object) -> None:
        self._stopping.set()

    # ---- Incoming messages ------------------------------------------------------

    def _handle(self, item: tuple) -> None:
        kind = item[0]
        now = time.time()
        if kind == "connected":
            self._broker_connected = True
            log.info("Connected to the MQTT broker at %s:%d", self._config.mqtt_host, self._config.mqtt_port)
        elif kind == "disconnected":
            self._broker_connected = self._frigate_online = self._word_detection_online = False
            self._presence.clear_present(now)
            log.warning("Lost the MQTT broker; reconnecting.")
        elif kind == "message":
            _, topic, payload = item
            if topic == self._frigate_status_topic:
                self._frigate_online = payload.strip() == b"online"
                if not self._frigate_online:
                    self._presence.clear_present(now)
            elif topic == self._config.word_detection_status_topic:
                self._word_detection_online = payload.strip() == b"online"
            elif topic == self._events_topic:
                event = self._parse(topic, payload)
                if event is not None:
                    self._presence.handle_event(event, now)
            elif topic == self._config.words_topic:
                self._queue_word(self._parse(topic, payload), now)

    def _queue_word(self, event: Optional[dict], now: float) -> None:
        if event is None:
            return
        try:
            word = str(event["word"]).strip()
            pressed_at = float(event["timestamp"])
            score = float(event["score"]) if event.get("score") is not None else None
        except (KeyError, TypeError, ValueError) as error:
            log.warning("Ignored a Word event with a missing or unusable field: %s", error)
            return
        if not word:
            log.warning("Ignored a Word event with an empty Word.")
            return

        # Wait until Frigate's events for the moments just after the Press have had time to arrive.
        decide_at = max(now, pressed_at + self._config.presence_tolerance_seconds) + self._config.decision_delay_seconds
        self._waiting.append(
            WordEvent(pressed_at, word, score, bool(event.get("uncertain")), event.get("reference"), decide_at)
        )

    @staticmethod
    def _parse(topic: str, payload: bytes) -> Optional[dict]:
        try:
            event = json.loads(payload)
        except (ValueError, UnicodeDecodeError) as error:
            log.warning("Ignored a message on %s that is not valid JSON: %s", topic, error)
            return None
        if not isinstance(event, dict):
            log.warning("Ignored a message on %s that is not a JSON object.", topic)
            return None
        return event

    # ---- Regular work -----------------------------------------------------------

    def _tick(self, now: float) -> None:
        self._update_window(now)

        due = sorted((event for event in self._waiting if event.decide_at <= now), key=lambda event: event.pressed_at)
        self._waiting = [event for event in self._waiting if event.decide_at > now]
        for event in due:
            self._record_press(event)

        self._close_utterance_if_due(now)
        self._clips.advance(now)
        self._presence.forget_before(now - 600.0)

    def _record_press(self, event: WordEvent) -> None:
        tolerance = self._config.presence_tolerance_seconds
        subjects = self._presence.subjects_between(event.pressed_at - tolerance, event.pressed_at + tolerance)
        attribution = attribute(subjects)

        utterance = self._database.open_utterance()
        if utterance is not None:
            too_late = event.pressed_at - utterance["last_press_at"] > self._config.utterance_gap_seconds
            too_long = event.pressed_at - utterance["started_at"] > self._config.utterance_max_seconds
            if too_late:
                self._close_utterance(utterance, utterance["last_press_at"] + self._config.utterance_gap_seconds)
                utterance = None
            elif too_long:
                self._close_utterance(utterance, event.pressed_at)
                utterance = None

        utterance_id = self._database.add_press(
            utterance_id=utterance["id"] if utterance is not None else None,
            pressed_at=event.pressed_at,
            word=event.word,
            word_score=event.score,
            word_uncertain=event.uncertain,
            reference_clip=event.reference,
            presser=attribution.presser,
            ambiguity=attribution.ambiguity,
            subjects_seen=subjects,
        )

        if attribution.presser == AMBIGUOUS:
            who = f"Ambiguous Press ({attribution.ambiguity} in the Board Zone)"
        else:
            who = f"pressed by the {attribution.presser}"
        log.info(
            "Press: '%s'%s, %s, Utterance %d",
            event.word,
            " (uncertain Word)" if event.uncertain else "",
            who,
            utterance_id,
        )

    def _close_utterance_if_due(self, now: float, starting_up: bool = False) -> None:
        utterance = self._database.open_utterance()
        if utterance is None:
            return
        closes_at = utterance["last_press_at"] + self._config.utterance_gap_seconds
        # A Word event still waiting to be recorded might belong to this Utterance.
        latest_arrival = self._config.presence_tolerance_seconds + 2 * self._config.decision_delay_seconds
        if starting_up or (now >= closes_at + latest_arrival and not self._waiting):
            if now >= closes_at:
                self._close_utterance(utterance, closes_at)

    def _close_utterance(self, utterance: sqlite3.Row, closed_at: float) -> None:
        clip_started_at = utterance["started_at"] - self._config.clip_pre_roll_seconds
        self._database.close_utterance(utterance["id"], closed_at, clip_started_at)
        words = " + ".join(press["word"] for press in self._database.presses_of(utterance["id"]))
        log.info("Utterance %d closed: %s", utterance["id"], words)
        self._announce_exchange(utterance, closed_at)

    def _announce_exchange(self, exchange: sqlite3.Row, closed_at: float) -> None:
        """Tells the broker an Exchange has closed, with the Utterances attributed to the cat
        and the ones still awaiting review.

        Only the automatic Presser counts here: a Review Decision is never announced.
        """
        if time.time() - closed_at > ANNOUNCE_WITHIN_SECONDS:
            log.info("Exchange %d closed too long ago to announce.", exchange["id"])
            return
        presses = [
            {
                "id": press["id"],
                "exchange_id": exchange["id"],
                "presser": press["presser"],
                "word": press["word"],
                "pressed_at": press["pressed_at"],
            }
            for press in self._database.presses_of(exchange["id"])
        ]
        utterances = split_utterances(presses)
        cat_utterances = [utterance["words"] for utterance in utterances if utterance["presser"] == "cat"]
        review_utterances = [utterance["words"] for utterance in utterances if utterance["presser"] == AMBIGUOUS]
        message = {
            "exchange_id": exchange["id"],
            "day": datetime.fromtimestamp(exchange["started_at"]).date().isoformat(),
            "started_at": exchange["started_at"],
            "closed_at": closed_at,
            "cat_utterances": cat_utterances,
            "cat_text": " · ".join(" ".join(words) for words in cat_utterances),
            "review_utterances": review_utterances,
            "review_text": " · ".join(" ".join(words) for words in review_utterances),
        }
        try:
            result = self._mqtt.publish(self._config.exchanges_topic, json.dumps(message), qos=1)
        except (ValueError, RuntimeError) as error:
            log.warning("Could not announce Exchange %d: %s", exchange["id"], error)
            return
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            log.warning("Could not announce Exchange %d: %s", exchange["id"], mqtt.error_string(result.rc))

    # ---- Observation Windows ----------------------------------------------------

    def _update_window(self, now: float) -> None:
        live = self._broker_connected and self._frigate_online and self._word_detection_online
        window = self._database.open_window()
        if live and window is None:
            self._database.start_window(now)
            self._last_heartbeat = now
            log.info("Observation Window started: Frigate and Word Detection are both live.")
        elif live and now - self._last_heartbeat >= self._config.heartbeat_seconds:
            self._database.touch_window(window["id"], now)
            self._last_heartbeat = now
        elif not live and window is not None:
            missing = [
                name
                for name, up in (
                    ("the MQTT broker", self._broker_connected),
                    ("Frigate", self._frigate_online),
                    ("Word Detection", self._word_detection_online),
                )
                if not up
            ]
            self._end_window(now, f"lost {' and '.join(missing)}")

    def _end_window(self, now: float, reason: str) -> None:
        window = self._database.open_window()
        if window is not None:
            self._database.end_window(window["id"], now)
            log.info("Observation Window ended after %.0f s: %s.", now - window["started_at"], reason)

    # ---- MQTT -------------------------------------------------------------------

    def _build_mqtt_client(self) -> mqtt.Client:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="correlator")
        client.on_connect = self._on_connect
        client.on_disconnect = lambda *_args: self._inbox.put(("disconnected",))
        client.on_message = lambda _client, _userdata, message: self._inbox.put(
            ("message", message.topic, message.payload)
        )
        return client

    def _on_connect(self, client: mqtt.Client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code.is_failure:
            log.warning("The MQTT broker refused the connection: %s", reason_code)
            return
        self._inbox.put(("connected",))
        for topic in (
            self._events_topic,
            self._frigate_status_topic,
            self._config.words_topic,
            self._config.word_detection_status_topic,
        ):
            client.subscribe(topic, qos=1)


def main() -> int:
    try:
        config = Config.from_environment()
    except ConfigError as error:
        print(f"The Correlator cannot start: {error}", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        database = Database(config.database_path)
    except (sqlite3.Error, OSError) as error:
        log.error("Cannot open the database at %s: %s", config.database_path, error)
        return 1
    log.info(
        "Database ready at %s. An Utterance closes %.0f s after its last Press.",
        config.database_path,
        config.utterance_gap_seconds,
    )

    service = Service(config, database)
    signal.signal(signal.SIGTERM, service.stop)
    signal.signal(signal.SIGINT, service.stop)
    try:
        service.run()
    except sqlite3.Error as error:
        log.error("The database failed, so the Correlator is stopping: %s", error)
        return 1
    finally:
        database.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
