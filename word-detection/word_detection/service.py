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
from typing import Deque, Optional

import paho.mqtt.client as mqtt

from .audio import SAMPLE_RATE, AudioError, PcmStream
from .config import Config, ConfigError
from .enrolment import Enrolment
from .features import FRAMES_PER_SECOND, FeatureExtractor
from .matcher import Match, Matcher, load_references
from .web import serve_forever

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
    def __init__(self, config: Config) -> None:
        self._config = config
        self._stopping = threading.Event()
        # Set whenever the Reference Clips on disk may differ from the ones being matched against.
        self._references_changed = threading.Event()
        self._matching = False
        self._stream: Optional[PcmStream] = None
        self._hearing = False
        self._events_topic = f"{config.topic_prefix}/words"
        self._status_topic = f"{config.topic_prefix}/status"
        self._mqtt = self._build_mqtt_client()
        self.enrolment = Enrolment(
            config.references_dir,
            config.data_dir,
            config.enrolment_limit_seconds,
            on_recording_changed=self._publish_status,
            on_references_changed=self._references_changed.set,
        )

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
        matcher = self._new_matcher()
        matcher_started_at = 0.0  # stream seconds at which the matcher began counting frames
        clock = StreamClock()
        samples_received = 0
        was_recording = False

        with PcmStream(self._config.stream_url) as stream:
            self._stream = stream
            try:
                for chunk in stream.chunks():
                    if samples_received == 0:
                        log.info("Listening to %s", self._config.stream_url)
                        self._set_hearing(True)
                    samples_received += chunk.size
                    clock.observe(samples_received)

                    # An Enrolment Recording takes the audio instead: nothing heard in it is a Press.
                    if self.enrolment.recording:
                        self.enrolment.feed(chunk)
                        was_recording = True
                        continue
                    if was_recording or self._references_changed.is_set():
                        was_recording = False
                        extractor = FeatureExtractor()
                        matcher = self._new_matcher()
                        matcher_started_at = samples_received / SAMPLE_RATE
                    if matcher is None:
                        continue
                    for match in matcher.push(extractor.push(chunk)):
                        self._publish(match, clock.time_of(matcher_started_at + match.start_seconds))
            finally:
                self._stream = None
                self._set_hearing(False)

    def _new_matcher(self) -> Optional[Matcher]:
        """A matcher for the Reference Clips now on disk, or None while no Word is enrolled."""
        self._references_changed.clear()
        references = load_references(self._config.references_dir)
        was_matching, self._matching = self._matching, bool(references)
        if references:
            words = sorted({reference.word for reference in references})
            log.info("Using %d Reference Clip(s) for %d Word(s): %s", len(references), len(words), ", ".join(words))
        else:
            log.warning(
                "No usable Reference Clips in %s. Nothing is reported until a Word is enrolled.",
                self._config.references_dir,
            )
        if was_matching != self._matching:
            self._publish_status()
        if not references:
            return None
        return Matcher(references, self._config.confident_threshold, self._config.uncertain_threshold)

    def _set_hearing(self, hearing: bool) -> None:
        """Report whether the stream is being heard. While it is not, a Press would be missed."""
        if hearing != self._hearing:
            self._hearing = hearing
            self.enrolment.set_hearing(hearing)
            self._publish_status()

    def _publish_status(self) -> None:
        """Say whether a Press now would be reported. Only "online" means it would."""
        if not self._hearing:
            status = "offline"
        elif self.enrolment.recording:
            status = "enrolling"
        elif not self._matching:
            status = "no-references"
        else:
            status = "online"
        self._mqtt.publish(self._status_topic, status, qos=1, retain=True)

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
        self._publish_status()

    def _on_mqtt_disconnect(self, _client, _userdata, _flags, reason_code, _properties) -> None:
        if not self._stopping.is_set():
            log.warning("Lost the MQTT broker (%s); reconnecting.", reason_code)


def main() -> int:
    try:
        config = Config.from_environment()
    except ConfigError as error:
        print(f"Word Detection cannot start: {error}", file=sys.stderr)
        return 2

    logging.getLogger("waitress").setLevel(logging.WARNING)  # its "Serving on" line says nothing new
    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    service = Service(config)
    threading.Thread(
        target=serve_forever, args=(service.enrolment, config.web_port), name="enrolment-web", daemon=True
    ).start()
    log.info("Enrolment is served on port %d.", config.web_port)
    signal.signal(signal.SIGTERM, service.stop)
    signal.signal(signal.SIGINT, service.stop)
    service.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
