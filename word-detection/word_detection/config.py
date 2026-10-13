"""Settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    """Raised when a setting has a value that cannot be used."""


@dataclass(frozen=True)
class Config:
    stream_url: str
    mqtt_host: str
    mqtt_port: int
    topic_prefix: str
    references_dir: Path
    data_dir: Path
    web_port: int
    enrolment_limit_seconds: float
    confident_threshold: float
    uncertain_threshold: float
    retry_seconds: float
    log_level: str

    @classmethod
    def from_environment(cls) -> "Config":
        config = cls(
            stream_url=os.environ.get("WD_STREAM_URL", "rtsp://mediamtx:8554/board"),
            mqtt_host=os.environ.get("WD_MQTT_HOST", "mosquitto"),
            mqtt_port=int(_number("WD_MQTT_PORT", 1883)),
            topic_prefix=os.environ.get("WD_TOPIC_PREFIX", "word-detection").strip("/"),
            references_dir=Path(os.environ.get("WD_REFERENCES_DIR", "/references")),
            # Where an Enrolment Recording is kept until it is saved or discarded.
            data_dir=Path(os.environ.get("WD_DATA_DIR", "/data")),
            web_port=int(_number("WD_WEB_PORT", 8700)),
            enrolment_limit_seconds=_number("WD_ENROLMENT_LIMIT_SECONDS", 600.0),
            confident_threshold=_number("WD_CONFIDENT_THRESHOLD", 0.75),
            uncertain_threshold=_number("WD_UNCERTAIN_THRESHOLD", 0.55),
            retry_seconds=_number("WD_RETRY_SECONDS", 5.0),
            log_level=os.environ.get("WD_LOG_LEVEL", "INFO").upper(),
        )
        if not 0.0 < config.uncertain_threshold <= config.confident_threshold <= 1.0:
            raise ConfigError(
                "WD_UNCERTAIN_THRESHOLD and WD_CONFIDENT_THRESHOLD must be between 0 and 1, "
                "with the uncertain threshold no higher than the confident one"
            )
        if config.retry_seconds <= 0:
            raise ConfigError("WD_RETRY_SECONDS must be greater than 0")
        if config.enrolment_limit_seconds <= 0:
            raise ConfigError("WD_ENROLMENT_LIMIT_SECONDS must be greater than 0")
        if not 0 < config.web_port < 65536:
            raise ConfigError("WD_WEB_PORT must be a port number between 1 and 65535")
        return config


def _number(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError as error:
        raise ConfigError(f"{name} must be a number, but is '{raw}'") from error
