"""The Word Detection service: listens to the stream and publishes Word events over MQTT.

Run with: python -m word_detection.service
"""

from __future__ import annotations

import json
import logging
import signal
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Deque, List, Optional

import paho.mqtt.client as mqtt

from .audio import SAMPLE_RATE, AudioError, PcmStream
from .config import Config, ConfigError
from .features import FRAMES_PER_SECOND, FeatureExtractor
from .matcher import Match, Matcher, Reference, load_references

log = logging.getLogger("word_detection")

CLOCK_WINDOW_CHUNKS = 300  # about 30 seconds of audio


class StreamClock:
    """Works out the wall-clock time at which each moment of the stream was heard.

    Audio arrives in bursts, so each chunk gives a slightly late guess of when the
    stream started. The earliest recent guess is the closest to the truth; using
    only recent guesses lets the estimate follow slow drift between the two clocks.
    """

    def __init__(self) -> None:
        self._start_estimates: Deque[float] = deque(maxlen=CLOCK_WINDOW_CHUNKS)

    def observe(self, samples_received: int) -> None:
        self._start_estimates.append(time.time() - samples_received / SAMPLE_RATE)

    def time_of(self, stream_seconds: float) -> float:
        return min(self._start_estimates) + stream_seconds


class Service:
    def __init__(self, config: Config, references: List[Reference]) -> None:
        self._config = config
        self._references = references
        self._stopping = threading.Event()
        self._stream: Optional[PcmStream] = None
        self._events_topic = f"{config.topic_prefix}/words"
        self._status_topic = f"{config.topic_prefix}/status"
        self._mqtt = self._build_mqtt_client()

    def run(self) -> None:
        """Listen until stopped, reconnecting whenever the stream drops."""
        self._mqtt.connect_async(self._config.mqtt_host, self._config.mqtt_port)
        self._mqtt.loop_start()
        try:
            while not self._stopping.is_set():
                try:
                    self._listen()
                    if not self._stopping.is_set():
                        log.warning("The stream ended.")
                except AudioError as error:
                    log.warning("Lost the stream: %s", error)
                if self._stopping.wait(self._config.retry_seconds):
                    break
                log.info("Reconnecting to %s", self._config.stream_url)
        finally:
            self._mqtt.publish(self._status_topic, "offline", qos=1, retain=True).wait_for_publish(timeout=2)
            self._mqtt.loop_stop()
            self._mqtt.disconnect()
            log.info("Stopped.")

    def stop(self, *_signal_args: object) -> None:
        self._stopping.set()
        if self._stream is not None:
            self._stream.close()

    def _listen(self) -> None:
        extractor = FeatureExtractor()
        matcher = Matcher(self._references, self._config.confident_threshold, self._config.uncertain_threshold)
        clock = StreamClock()
        samples_received = 0

        with PcmStream(self._config.stream_url) as stream:
            self._stream = stream
            try:
                for chunk in stream.chunks():
                    if samples_received == 0:
                        log.info("Listening to %s", self._config.stream_url)
                    samples_received += chunk.size
                    clock.observe(samples_received)
                    for match in matcher.push(extractor.push(chunk)):
                        self._publish(match, clock.time_of(match.start_seconds))
            finally:
                self._stream = None

    def _publish(self, match: Match, started_at: float) -> None:
        payload = {
            "word": match.word,
            "started_at": datetime.fromtimestamp(started_at, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "timestamp": round(started_at, 3),
            "duration": round((match.end_frame - match.start_frame + 1) / FRAMES_PER_SECOND, 3),
            "score": round(match.score, 3),
            "uncertain": match.uncertain,
            "reference": match.reference,
        }
        log.info(
            "Heard '%s' (score %.2f%s)",
            match.word,
            match.score,
            ", uncertain" if match.uncertain else "",
        )
        self._mqtt.publish(self._events_topic, json.dumps(payload), qos=1)

    def _build_mqtt_client(self) -> mqtt.Client:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="word-detection")
        client.will_set(self._status_topic, "offline", qos=1, retain=True)
        client.on_connect = self._on_mqtt_connect
        client.on_disconnect = self._on_mqtt_disconnect
        return client

    def _on_mqtt_connect(self, client: mqtt.Client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code.is_failure:
            log.warning("The MQTT broker refused the connection: %s", reason_code)
            return
        log.info("Connected to the MQTT broker at %s:%d", self._config.mqtt_host, self._config.mqtt_port)
        client.publish(self._status_topic, "online", qos=1, retain=True)

    def _on_mqtt_disconnect(self, _client, _userdata, _flags, reason_code, _properties) -> None:
        if not self._stopping.is_set():
            log.warning("Lost the MQTT broker (%s); reconnecting.", reason_code)


def main() -> int:
    try:
        config = Config.from_environment()
    except ConfigError as error:
        print(f"Word Detection cannot start: {error}", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    references = load_references(config.references_dir)
    if not references:
        log.error("No usable Reference Clips in %s. Enrol at least one Word first.", config.references_dir)
        return 1

    words = sorted({reference.word for reference in references})
    log.info("Loaded %d Reference Clip(s) for %d Word(s): %s", len(references), len(words), ", ".join(words))

    service = Service(config, references)
    signal.signal(signal.SIGTERM, service.stop)
    signal.signal(signal.SIGINT, service.stop)
    service.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
