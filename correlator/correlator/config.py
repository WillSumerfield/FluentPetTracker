"""Settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    """Raised when a setting has a value that cannot be used."""


@dataclass(frozen=True)
class Config:
    mqtt_host: str
    mqtt_port: int
    frigate_url: str
    frigate_topic_prefix: str
    words_topic: str
    word_detection_status_topic: str
    camera: str
    zone: str
    data_dir: Path
    exports_dir: Path
    utterance_gap_seconds: float
    utterance_max_seconds: float
    presence_tolerance_seconds: float
    decision_delay_seconds: float
    clip_pre_roll_seconds: float
    clip_export_delay_seconds: float
    heartbeat_seconds: float
    log_level: str

    @property
    def database_path(self) -> Path:
        return self.data_dir / "correlator.db"

    @property
    def clips_dir(self) -> Path:
        return self.data_dir / "clips"

    @classmethod
    def from_environment(cls) -> "Config":
        config = cls(
            mqtt_host=os.environ.get("CR_MQTT_HOST", "mosquitto"),
            mqtt_port=int(_positive("CR_MQTT_PORT", 1883)),
            frigate_url=os.environ.get("CR_FRIGATE_URL", "http://frigate:5000").rstrip("/"),
            frigate_topic_prefix=os.environ.get("CR_FRIGATE_TOPIC_PREFIX", "frigate").strip("/"),
            words_topic=os.environ.get("CR_WORDS_TOPIC", "word-detection/words"),
            word_detection_status_topic=os.environ.get("CR_WORD_DETECTION_STATUS_TOPIC", "word-detection/status"),
            camera=os.environ.get("CR_CAMERA", "board"),
            zone=os.environ.get("CR_ZONE", "board_zone"),
            data_dir=Path(os.environ.get("CR_DATA_DIR", "/data")),
            exports_dir=Path(os.environ.get("CR_EXPORTS_DIR", "/frigate-exports")),
            utterance_gap_seconds=_positive("CR_UTTERANCE_GAP_SECONDS", 20.0),
            utterance_max_seconds=_positive("CR_UTTERANCE_MAX_SECONDS", 300.0),
            presence_tolerance_seconds=_positive("CR_PRESENCE_TOLERANCE_SECONDS", 1.5),
            decision_delay_seconds=_positive("CR_DECISION_DELAY_SECONDS", 3.0),
            clip_pre_roll_seconds=_positive("CR_CLIP_PRE_ROLL_SECONDS", 5.0),
            clip_export_delay_seconds=_positive("CR_CLIP_EXPORT_DELAY_SECONDS", 20.0),
            heartbeat_seconds=_positive("CR_HEARTBEAT_SECONDS", 30.0),
            log_level=os.environ.get("CR_LOG_LEVEL", "INFO").upper(),
        )
        if config.utterance_max_seconds <= config.utterance_gap_seconds:
            raise ConfigError("CR_UTTERANCE_MAX_SECONDS must be greater than CR_UTTERANCE_GAP_SECONDS")
        return config


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
