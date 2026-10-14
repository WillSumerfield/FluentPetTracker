"""Settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple


class ConfigError(Exception):
    """Raised when a setting has a value that cannot be used."""


@dataclass(frozen=True)
class Config:
    mqtt_host: str
    mqtt_port: int
    frigate_url: str
    frigate_topic_prefix: str
    pet_name: str
    pet_labels: Tuple[str, ...]
    words_topic: str
    word_detection_status_topic: str
    exchanges_topic: str
    camera: str
    zone: str
    data_dir: Path
    clips_dir: Path
    exports_dir: Path
    utterance_gap_seconds: float
    utterance_max_seconds: float
    presence_tolerance_seconds: float
    decision_delay_seconds: float
    clip_pre_roll_seconds: float
    clip_export_delay_seconds: float
    heartbeat_seconds: float
    web_port: int
    response_seconds: float
    counted_day_hours: float
    live_stream_url: str
    word_detection_url: str
    pi_control_url: str
    log_level: str

    @property
    def database_path(self) -> Path:
        return self.data_dir / "correlator.db"

    @classmethod
    def from_environment(cls) -> "Config":
        config = cls(
            mqtt_host=os.environ.get("CR_MQTT_HOST", "mosquitto"),
            mqtt_port=int(_positive("CR_MQTT_PORT", 1883)),
            frigate_url=os.environ.get("CR_FRIGATE_URL", "http://frigate:5000").rstrip("/"),
            frigate_topic_prefix=os.environ.get("CR_FRIGATE_TOPIC_PREFIX", "frigate").strip("/"),
            # What the pages and alerts call the Pet, and the Frigate labels that count as it.
            pet_name=os.environ.get("CR_PET_NAME", "").strip() or "Pet",
            pet_labels=_labels("CR_PET_LABELS", ("cat", "dog")),
            words_topic=os.environ.get("CR_WORDS_TOPIC", "word-detection/words"),
            word_detection_status_topic=os.environ.get("CR_WORD_DETECTION_STATUS_TOPIC", "word-detection/status"),
            # Where each closed Exchange is announced, for Home Assistant's Utterance Alerts.
            exchanges_topic=os.environ.get("CR_EXCHANGES_TOPIC", "correlator/exchanges").strip("/"),
            camera=os.environ.get("CR_CAMERA", "board"),
            zone=os.environ.get("CR_ZONE", "board_zone"),
            data_dir=Path(os.environ.get("CR_DATA_DIR", "/data")),
            # Where Clips are kept; it must hold a .fluentpet-clips file (see clips.py).
            clips_dir=Path(os.environ.get("CR_CLIPS_DIR", "/data/clips")),
            exports_dir=Path(os.environ.get("CR_EXPORTS_DIR", "/frigate-exports")),
            utterance_gap_seconds=_positive("CR_UTTERANCE_GAP_SECONDS", 20.0),
            utterance_max_seconds=_positive("CR_UTTERANCE_MAX_SECONDS", 300.0),
            presence_tolerance_seconds=_positive("CR_PRESENCE_TOLERANCE_SECONDS", 1.5),
            decision_delay_seconds=_positive("CR_DECISION_DELAY_SECONDS", 3.0),
            clip_pre_roll_seconds=_positive("CR_CLIP_PRE_ROLL_SECONDS", 5.0),
            clip_export_delay_seconds=_positive("CR_CLIP_EXPORT_DELAY_SECONDS", 20.0),
            heartbeat_seconds=_positive("CR_HEARTBEAT_SECONDS", 30.0),
            web_port=int(_positive("CR_WEB_PORT", 8600)),
            response_seconds=_positive("CR_RESPONSE_SECONDS", 300.0),
            counted_day_hours=_positive("CR_COUNTED_DAY_HOURS", 4.0),
            # Where a browser reaches Frigate's live stream. Empty: the page works it out from its own address.
            live_stream_url=os.environ.get("CR_LIVE_STREAM_URL", "").strip(),
            # Where Word Detection does the work of the Enrolment page.
            word_detection_url=os.environ.get("CR_WORD_DETECTION_URL", "http://word-detection:8700").rstrip("/"),
            # Where the Pi's control service Pauses and Resumes capture. Empty: the Live Feed has no Pause.
            pi_control_url=os.environ.get("CR_PI_CONTROL_URL", "").strip().rstrip("/"),
            log_level=os.environ.get("CR_LOG_LEVEL", "INFO").upper(),
        )
        if config.utterance_max_seconds <= config.utterance_gap_seconds:
            raise ConfigError("CR_UTTERANCE_MAX_SECONDS must be greater than CR_UTTERANCE_GAP_SECONDS")
        if "person" in config.pet_labels:
            raise ConfigError("CR_PET_LABELS must not include 'person': a person is always the human")
        return config


def _labels(name: str, default: Tuple[str, ...]) -> Tuple[str, ...]:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    labels = tuple(label.strip().lower() for label in raw.split(",") if label.strip())
    if not labels:
        raise ConfigError(f"{name} must name at least one Frigate label, such as 'cat'")
    return labels


def _positive(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise ConfigError(f"{name} must be a number, but is '{raw}'") from error
    if value <= 0:
        raise ConfigError(f"{name} must be greater than 0, but is {raw}")
    return value
