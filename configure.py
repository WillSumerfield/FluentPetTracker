#!/usr/bin/env python3
"""Writes every service's settings from the root config.yml.

Run with:  ./fluentpet.sh configure   (./fluentpet.sh up runs it too)
       or: python3 configure.py [--check] [--overwrite-frigate]

config.yml is the only file a person edits. This reads it, checks every setting, and writes:

    frigate/.env                              ports and host folders, for Docker Compose
    frigate/correlator.env                    the Correlator's CR_ settings
    frigate/word-detection.env                Word Detection's WD_ settings
    frigate/config/config.yml                 Frigate, from frigate/config.template.yml
    frigate/relay/mediamtx.yml                the relay, from frigate/relay/mediamtx.template.yml
    home-assistant/config/configuration.yaml  Home Assistant, from home-assistant/configuration.template.yaml
    home-assistant/config/secrets.yaml        only its fluentpet_*_url lines; the rest is kept
    rpi-capture/capture.env                   the Pi's camera, mic and Pause settings

Nothing is written unless every setting checks out. A file whose contents would not change is
left alone. Frigate's file is also written by Frigate's own UI (a Board Zone redrawn there), so
if it has changed since it was last written here, this stops rather than overwrite that change.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import ipaddress
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover - depends on the machine
    print("configure.py needs PyYAML. Install it with:  sudo apt install python3-yaml", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.yml"
EXAMPLE = ROOT / "config.example.yml"

FRIGATE_CONFIG = ROOT / "frigate/config/config.yml"
# A fingerprint of the Frigate file as last written here, to tell a UI edit from our own.
FRIGATE_WRITTEN = ROOT / "frigate/config/.fluentpet-written"
SECRETS = ROOT / "home-assistant/config/secrets.yaml"

TEMPLATES = {
    "frigate/config/config.yml": "frigate/config.template.yml",
    "frigate/relay/mediamtx.yml": "frigate/relay/mediamtx.template.yml",
    "home-assistant/config/configuration.yaml": "home-assistant/configuration.template.yaml",
}

# The Correlator's pages, as Home Assistant's sidebar opens them: secrets.yaml key -> path.
PAGE_SECRETS = {
    "fluentpet_daily_url": "/",
    "fluentpet_review_url": "/review",
    "fluentpet_live_url": "/live",
    "fluentpet_metrics_url": "/metrics",
    "fluentpet_enrol_url": "/enrol",
}

# The labels of Frigate's default model (COCO), less "person", which is always the human.
FRIGATE_LABELS = {
    "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
    "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep",
    "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie",
    "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite", "baseball bat",
    "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange", "broccoli",
    "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant", "bed",
    "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone",
    "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors",
    "teddy bear", "hair drier", "toothbrush",
}
ICON_BY_LABEL = {"cat": "mdi:cat", "dog": "mdi:dog", "bird": "mdi:bird", "horse": "mdi:horse"}

# Every setting, with the value it has when config.yml leaves it out. Matches config.example.yml.
DEFAULTS: Dict[str, Any] = {
    "pet": {"name": "Pet", "labels": ["cat", "dog"]},
    "pi": {
        "address": "192.168.0.104",
        "video": {"width": 1920, "height": 1080, "fps": 30, "bitrate": 12000000},
        "lens_position": 1.0,
        "mic": "plughw:CARD=Mic,DEV=0",
        "no_camera": "test-pattern",
        "control_port": 8800,
        "allowed_pcs": ["192.168.0.164"],
    },
    "frigate": {
        "detect": {"width": 640, "height": 360, "fps": 5},
        "board_zone": "0.25,0.25,1,0.25,1,1,0.25,1",
        "keep_footage_hours": 1,
    },
    "storage": {"clips_dir": "/mnt/d/FluentPetTracker/clips", "data_dir": "correlator/data"},
    "study": {
        "exchange_gap_seconds": 20,
        "exchange_max_seconds": 300,
        "reply_window_seconds": 300,
        "counted_day_hours": 4,
        "presence_tolerance_seconds": 1.5,
        "decision_delay_seconds": 3,
        "clip_pre_roll_seconds": 5,
    },
    "word_detection": {"confident_threshold": 0.75, "uncertain_threshold": 0.55, "enrolment_limit_seconds": 600},
    "network": {
        "public_address": "",
        "ports": {"home_assistant": 8123, "pages": 8600, "frigate": 5000, "frigate_login": 8971, "rtsp": 8554, "mqtt": 1883},
        "live_stream_url": "",
    },
}


class Stop(Exception):
    """Raised to stop with a message and nothing written."""


# ---- Reading and checking config.yml ---------------------------------------------------


def read_settings() -> Dict[str, Any]:
    try:
        raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise Stop(f"config.yml is not valid YAML:\n  {error}") from error
    except OSError as error:
        raise Stop(f"config.yml could not be read: {error}") from error
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise Stop("config.yml must be a set of sections, such as  pet:  and  pi:")

    problems: List[str] = []
    settings = merge(DEFAULTS, raw, "", problems)
    check(settings, problems)
    if problems:
        listed = "\n".join(f"  • {problem}" for problem in problems)
        noun = "problem" if len(problems) == 1 else "problems"
        raise Stop(f"config.yml has {len(problems)} {noun}, so nothing was written:\n{listed}")
    return settings


def merge(defaults: Dict[str, Any], given: Dict[str, Any], prefix: str, problems: List[str]) -> Dict[str, Any]:
    """The defaults with config.yml's values laid over them. Unknown names are reported, not ignored."""
    merged = copy.deepcopy(defaults)
    for key, value in given.items():
        path = f"{prefix}{key}"
        if key not in defaults:
            known = ", ".join(defaults)
            problems.append(f"{path}: not a setting here (expected one of: {known})")
        elif isinstance(defaults[key], dict):
            if value is None:
                continue
            if not isinstance(value, dict):
                problems.append(f"{path}: must be a section of settings, not {value!r}")
                continue
            merged[key] = merge(defaults[key], value, f"{path}.", problems)
        else:
            merged[key] = value
    return merged


def check(s: Dict[str, Any], problems: List[str]) -> None:
    def number(path: str, low: float, high: float, whole: bool = False) -> None:
        value = lookup(s, path)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append(f"{path}: must be a number, not {value!r}")
        elif whole and value != int(value):
            problems.append(f"{path}: must be a whole number, not {value}")
        elif not low <= value <= high:
            problems.append(f"{path}: must be between {low:g} and {high:g}, not {value}")

    def text(path: str, allow_empty: bool = False, forbidden: str = "") -> Optional[str]:
        value = lookup(s, path)
        if not isinstance(value, str):
            problems.append(f"{path}: must be text, not {value!r}")
            return None
        if not allow_empty and not value.strip():
            problems.append(f"{path}: must not be empty")
            return None
        bad = sorted({character for character in value if character in forbidden or character in "\n\r"})
        if bad:
            problems.append(f"{path}: must not contain {' '.join(repr(character) for character in bad)}")
            return None
        return value.strip()

    # The Pet
    name = text("pet.name", forbidden='"\\$`')
    if name is not None and len(name) > 40:
        problems.append("pet.name: must be 40 characters or fewer")
    labels = lookup(s, "pet.labels")
    if not isinstance(labels, list) or not labels or not all(isinstance(label, str) for label in labels):
        problems.append("pet.labels: must be a list of Frigate labels, such as [cat, dog]")
    else:
        for label in labels:
            if label.strip().lower() == "person":
                problems.append("pet.labels: must not include 'person', which is always the human")
            elif label.strip().lower() not in FRIGATE_LABELS:
                problems.append(f"pet.labels: '{label}' is not a label Frigate knows (cat, dog, bird, horse, ...)")
        if len({label.strip().lower() for label in labels}) != len(labels):
            problems.append("pet.labels: lists the same label twice")

    # The Pi
    address = text("pi.address")
    if address is not None and not is_host(address):
        problems.append(f"pi.address: '{address}' is not an IP address or host name")
    number("pi.video.width", 160, 4608, whole=True)
    number("pi.video.height", 120, 2592, whole=True)
    number("pi.video.fps", 1, 60, whole=True)
    number("pi.video.bitrate", 100_000, 25_000_000, whole=True)
    number("pi.lens_position", 0, 32)
    text("pi.mic", forbidden="'")
    if lookup(s, "pi.no_camera") not in ("test-pattern", "wait"):
        problems.append(f"pi.no_camera: must be test-pattern or wait, not {lookup(s, 'pi.no_camera')!r}")
    number("pi.control_port", 1, 65535, whole=True)
    pcs = lookup(s, "pi.allowed_pcs")
    if not isinstance(pcs, list) or not pcs:
        problems.append("pi.allowed_pcs: must be a list of this PC's addresses, such as [192.168.0.164]")
    else:
        for pc in pcs:
            if not is_ip(str(pc)):
                problems.append(f"pi.allowed_pcs: '{pc}' is not an IP address")

    # Frigate
    number("frigate.detect.width", 160, 3840, whole=True)
    number("frigate.detect.height", 120, 2160, whole=True)
    number("frigate.detect.fps", 1, 30, whole=True)
    zone = lookup(s, "frigate.board_zone")
    if zone_points(zone) is None:
        problems.append(
            "frigate.board_zone: must be at least three x,y pairs from 0 to 1, separated by commas,"
            ' such as "0.25,0.25,1,0.25,1,1"'
        )
    number("frigate.keep_footage_hours", 0.25, 24 * 30)

    # Storage
    clips = text("storage.clips_dir")
    if clips is not None and not clips.startswith("/"):
        problems.append(f"storage.clips_dir: must be a full path starting with /, not '{clips}'")
    text("storage.data_dir")

    # The study's rules
    for key in ("exchange_gap_seconds", "exchange_max_seconds", "reply_window_seconds"):
        number(f"study.{key}", 1, 24 * 3600)
    number("study.counted_day_hours", 0.1, 24)
    number("study.presence_tolerance_seconds", 0.1, 60)
    number("study.decision_delay_seconds", 0.1, 60)
    number("study.clip_pre_roll_seconds", 0.1, 120)
    gap, longest = lookup(s, "study.exchange_gap_seconds"), lookup(s, "study.exchange_max_seconds")
    if all(isinstance(value, (int, float)) for value in (gap, longest)) and longest <= gap:
        problems.append("study.exchange_max_seconds: must be longer than study.exchange_gap_seconds")

    # Word Detection
    number("word_detection.confident_threshold", 0.01, 1)
    number("word_detection.uncertain_threshold", 0.01, 1)
    number("word_detection.enrolment_limit_seconds", 10, 3600)
    confident, uncertain = (lookup(s, f"word_detection.{key}") for key in ("confident_threshold", "uncertain_threshold"))
    if all(isinstance(value, (int, float)) for value in (confident, uncertain)) and uncertain > confident:
        problems.append("word_detection.uncertain_threshold: must not be higher than confident_threshold")

    # Network
    public = text("network.public_address", allow_empty=True)
    if public and not re.fullmatch(r"https?://[^\s/]+(:\d+)?/?", public):
        problems.append(
            f"network.public_address: '{public}' must be an address such as https://my-pc.tailnet.ts.net:8443"
        )
    ports = lookup(s, "network.ports")
    for key in DEFAULTS["network"]["ports"]:
        number(f"network.ports.{key}", 1, 65535, whole=True)
    used = [ports[key] for key in DEFAULTS["network"]["ports"]]
    if len(set(used)) != len(used):
        problems.append("network.ports: two services are given the same port")
    text("network.live_stream_url", allow_empty=True)


def lookup(settings: Dict[str, Any], path: str) -> Any:
    value: Any = settings
    for part in path.split("."):
        value = value[part]
    return value


def is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def is_host(value: str) -> bool:
    return is_ip(value) or re.fullmatch(r"[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", value) is not None


def zone_points(zone: Any) -> Optional[List[float]]:
    if not isinstance(zone, str):
        return None
    try:
        numbers = [float(part) for part in zone.split(",")]
    except ValueError:
        return None
    if len(numbers) < 6 or len(numbers) % 2 or not all(0 <= number <= 1 for number in numbers):
        return None
    return numbers


# ---- What each file says ----------------------------------------------------------------


def number_text(value: float) -> str:
    """12.0 as 12, 1.5 as 1.5: the way a person would write it."""
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def env_value(value: Any) -> str:
    """A value for an env file that Compose reads as written. Single quotes stop $ being expanded."""
    text = number_text(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)
    return f'"{text}"' if "'" in text else f"'{text}'"


def env_file(title: str, values: Dict[str, Any]) -> str:
    lines = [f"# {title}", "# Written by configure.py from the root config.yml. Do not edit: change config.yml instead.", ""]
    lines += [f"{key}={env_value(value)}" for key, value in values.items()]
    return "\n".join(lines) + "\n"


def render(target: str, values: Dict[str, str]) -> str:
    template_path = ROOT / TEMPLATES[target]
    try:
        template = template_path.read_text(encoding="utf-8")
    except OSError as error:
        raise Stop(f"The template {TEMPLATES[target]} could not be read: {error}") from error
    # The template's own opening note ("Template for ...") is swapped for one saying where the file came from.
    if template.startswith("# Template for"):
        template = template.split("\n\n", 1)[1] if "\n\n" in template else ""
    try:
        body = Template(template).substitute(values)
    except (KeyError, ValueError) as error:
        raise Stop(f"The template {TEMPLATES[target]} names a setting configure.py does not fill in: {error}") from error
    header = (
        f"# Written by configure.py from the root config.yml and {TEMPLATES[target]}.\n"
        "# Do not edit: change config.yml, or the template, and run ./fluentpet.sh configure.\n\n"
    )
    return header + body


def build(s: Dict[str, Any]) -> Dict[str, str]:
    """Every generated file's path, relative to the repository, and its new contents."""
    pet_name = s["pet"]["name"].strip()
    labels = [label.strip().lower() for label in s["pet"]["labels"]]
    ports = s["network"]["ports"]
    pi = s["pi"]
    study = s["study"]
    data_dir = Path(s["storage"]["data_dir"])
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir

    files = {
        "frigate/.env": env_file(
            "Ports and folders on this PC, for Docker Compose.",
            {
                "FP_CLIPS_DIR": s["storage"]["clips_dir"].rstrip("/") or "/",
                "FP_DATA_DIR": str(data_dir),
                "FP_PORT_HOME_ASSISTANT": ports["home_assistant"],
                "FP_PORT_PAGES": ports["pages"],
                "FP_PORT_FRIGATE": ports["frigate"],
                "FP_PORT_FRIGATE_LOGIN": ports["frigate_login"],
                "FP_PORT_RTSP": ports["rtsp"],
                "FP_PORT_MQTT": ports["mqtt"],
            },
        ),
        "frigate/correlator.env": env_file(
            "The Correlator's settings (see correlator/correlator/config.py).",
            {
                "CR_PET_NAME": pet_name,
                "CR_PET_LABELS": ",".join(labels),
                "CR_UTTERANCE_GAP_SECONDS": study["exchange_gap_seconds"],
                "CR_UTTERANCE_MAX_SECONDS": study["exchange_max_seconds"],
                "CR_RESPONSE_SECONDS": study["reply_window_seconds"],
                "CR_COUNTED_DAY_HOURS": study["counted_day_hours"],
                "CR_PRESENCE_TOLERANCE_SECONDS": study["presence_tolerance_seconds"],
                "CR_DECISION_DELAY_SECONDS": study["decision_delay_seconds"],
                "CR_CLIP_PRE_ROLL_SECONDS": study["clip_pre_roll_seconds"],
                "CR_LIVE_STREAM_URL": s["network"]["live_stream_url"].strip(),
                "CR_PI_CONTROL_URL": f"http://{pi['address']}:{pi['control_port']}",
            },
        ),
        "frigate/word-detection.env": env_file(
            "Word Detection's settings (see word-detection/word_detection/config.py).",
            {
                "WD_CONFIDENT_THRESHOLD": s["word_detection"]["confident_threshold"],
                "WD_UNCERTAIN_THRESHOLD": s["word_detection"]["uncertain_threshold"],
                "WD_ENROLMENT_LIMIT_SECONDS": s["word_detection"]["enrolment_limit_seconds"],
            },
        ),
        "rpi-capture/capture.env": env_file(
            "RPi Capture's settings. install.sh copies this to the Pi's /usr/local/etc/rpi-capture.env.",
            {
                "WIDTH": pi["video"]["width"],
                "HEIGHT": pi["video"]["height"],
                "FPS": pi["video"]["fps"],
                "BITRATE": pi["video"]["bitrate"],
                "LENS_POSITION": pi["lens_position"],
                "MIC": pi["mic"].strip(),
                "NO_CAMERA": pi["no_camera"],
                "CONTROL_PORT": pi["control_port"],
                "PC_ADDRESSES": " ".join(str(pc) for pc in pi["allowed_pcs"]),
            },
        ),
    }

    tracked = json.dumps(["person"] + labels)
    files["frigate/config/config.yml"] = render(
        "frigate/config/config.yml",
        {
            "retain_days": number_text(round(s["frigate"]["keep_footage_hours"] / 24, 3)),
            "detect_width": number_text(s["frigate"]["detect"]["width"]),
            "detect_height": number_text(s["frigate"]["detect"]["height"]),
            "detect_fps": number_text(s["frigate"]["detect"]["fps"]),
            "tracked_labels": tracked,
            "board_zone": ",".join(number_text(point) for point in zone_points(s["frigate"]["board_zone"]) or []),
        },
    )
    files["frigate/relay/mediamtx.yml"] = render("frigate/relay/mediamtx.yml", {"pi_address": pi["address"]})

    # Each value is a whole YAML scalar: JSON strings are valid YAML, whatever the name holds.
    files["home-assistant/config/configuration.yaml"] = render(
        "home-assistant/config/configuration.yaml",
        {
            "pet_name": json.dumps(pet_name),
            "pet_icon": ICON_BY_LABEL.get(labels[0], "mdi:paw"),
            "sensor_presses_today": json.dumps(f"FluentPet {pet_name} Presses today"),
            "sensor_presses_per_hour": json.dumps(f"FluentPet {pet_name} Presses per observed hour today"),
            "sensor_vocabulary": json.dumps(f"FluentPet Words used by {pet_name}"),
            "sensor_last_word": json.dumps(f"FluentPet last Word by {pet_name}"),
        },
    )

    public = s["network"]["public_address"].strip().rstrip("/")
    if public:
        files["home-assistant/config/secrets.yaml"] = merged_secrets(public)
    return files


def merged_secrets(public: str) -> str:
    """secrets.yaml with the page addresses set, and every other line kept as it was."""
    try:
        lines = SECRETS.read_text(encoding="utf-8").splitlines() if SECRETS.exists() else []
    except OSError as error:
        raise Stop(f"home-assistant/config/secrets.yaml could not be read: {error}") from error
    if not lines:
        lines = ["# Not committed. The fluentpet_*_url lines are written by configure.py from config.yml."]
    wanted = {key: f"{key}: {public}{path}" for key, path in PAGE_SECRETS.items()}
    kept = []
    for line in lines:
        key = line.split(":", 1)[0].strip()
        if key in wanted:
            kept.append(wanted.pop(key))
        else:
            kept.append(line)
    kept += wanted.values()
    return "\n".join(kept) + "\n"


# ---- Frigate's own edits -----------------------------------------------------------------


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def frigate_problem(new: str) -> Optional[str]:
    """Why the Frigate file must not be overwritten, or None when it may be."""
    try:
        current = FRIGATE_CONFIG.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as error:
        return f"frigate/config/config.yml could not be read: {error}"
    if current == new:
        return None
    try:
        written = FRIGATE_WRITTEN.read_text(encoding="utf-8").strip()
    except OSError:
        written = ""
    if written == fingerprint(current):
        return None  # last written here, so only config.yml or the template has changed

    try:
        current_data = yaml.safe_load(current)
    except yaml.YAMLError:
        current_data = None
    new_data = yaml.safe_load(new)
    if current_data == new_data:
        return None  # the same settings, laid out differently

    differences = list(differing_paths(current_data, new_data))
    if written:
        lines = ["frigate/config/config.yml was changed outside configure.py (by Frigate's UI, or by hand),"]
        lines.append("and writing it again would undo that. What differs from config.yml:")
    else:
        lines = ["frigate/config/config.yml was not written by configure.py, and writing it now would"]
        lines.append("change what it says. What differs from config.yml:")
    lines += [f"  • {path}" for path in differences[:12]]
    if len(differences) > 12:
        lines.append(f"  • … and {len(differences) - 12} more")
    zone = board_zone_of(current_data)
    if zone and zone_points(zone) != zone_points(board_zone_of(new_data)):
        lines.append("")
        lines.append("The Board Zone was redrawn. To keep it, put this in config.yml under frigate:")
        lines.append(f'  board_zone: "{zone}"')
    lines.append("")
    lines.append("Copy back anything to keep, then run again. To overwrite Frigate's file regardless:")
    lines.append("  ./fluentpet.sh configure --overwrite-frigate")
    return "\n".join(lines)


def differing_paths(old: Any, new: Any, prefix: str = "") -> List[str]:
    if isinstance(old, dict) and isinstance(new, dict):
        paths = []
        for key in sorted(set(old) | set(new), key=str):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in new:
                paths.append(f"{path} (only in Frigate's file)")
            elif key not in old:
                paths.append(f"{path} (only in config.yml)")
            else:
                paths += differing_paths(old[key], new[key], path)
        return paths
    return [] if old == new else [prefix or "(the whole file)"]


def board_zone_of(data: Any) -> Optional[str]:
    try:
        zone = data["cameras"]["board"]["zones"]["board_zone"]["coordinates"]
    except (KeyError, TypeError):
        return None
    if isinstance(zone, list):
        zone = ",".join(str(point) for point in zone)
    return str(zone) if zone is not None else None


# ---- Writing -----------------------------------------------------------------------------


def write_atomically(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(text)
        if path.exists():
            shutil.copymode(path, temporary)
        else:
            os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


@dataclass
class Outcome:
    path: str
    changed: bool


def write_all(files: Dict[str, str]) -> List[Outcome]:
    outcomes = []
    for relative, text in files.items():
        path = ROOT / relative
        try:
            current = path.read_text(encoding="utf-8") if path.exists() else None
        except OSError:
            current = None
        changed = current != text
        if changed:
            try:
                write_atomically(path, text)
            except OSError as error:
                raise Stop(f"{relative} could not be written: {error}") from error
        outcomes.append(Outcome(relative, changed))
    # Remembered even when unchanged, so a file that only differed in layout counts as ours from now on.
    frigate = files["frigate/config/config.yml"]
    write_atomically(FRIGATE_WRITTEN, fingerprint(frigate) + "\n")
    return outcomes


def warnings(s: Dict[str, Any]) -> List[str]:
    """Things that do not stop configure.py, but are worth knowing."""
    notes = []
    if s["pet"]["name"].strip() == "Biscuit" and "Biscuit" in EXAMPLE.read_text(encoding="utf-8"):
        notes.append("pet.name is still the example's 'Biscuit'.")
    clips = Path(s["storage"]["clips_dir"])
    if not (clips / ".fluentpet-clips").exists():
        notes.append(
            f"{clips} has no .fluentpet-clips file (or cannot be reached), so Clips will not be saved"
            " until it does. Presses are still recorded."
        )
    if not s["network"]["public_address"].strip():
        notes.append("network.public_address is empty, so secrets.yaml's page addresses were left as they are.")
    return notes


def main() -> int:
    parser = argparse.ArgumentParser(description="Write every service's settings from the root config.yml.")
    parser.add_argument("--check", action="store_true", help="check config.yml and show what would change, but write nothing")
    parser.add_argument(
        "--overwrite-frigate", action="store_true", help="write Frigate's config.yml even if Frigate's UI has changed it"
    )
    arguments = parser.parse_args()

    if not CONFIG.exists():
        try:
            shutil.copyfile(EXAMPLE, CONFIG)
        except OSError as error:
            print(f"✗ config.yml is missing, and config.example.yml could not be copied: {error}", file=sys.stderr)
            return 1
        print("Made config.yml from config.example.yml. It is yours, and not committed.")
        print("Set at least pet.name, pi.address, pi.allowed_pcs and storage.clips_dir in it, then run this again.")
        return 3

    try:
        settings = read_settings()
        files = build(settings)
        problem = None if arguments.overwrite_frigate else frigate_problem(files["frigate/config/config.yml"])
        if problem:
            raise Stop(problem)
        if arguments.check:
            for relative, text in files.items():
                path = ROOT / relative
                changed = not path.exists() or path.read_text(encoding="utf-8") != text
                print(f"  {'would change' if changed else 'unchanged   '}  {relative}")
            print("✓ config.yml checks out. Nothing was written (--check).")
            return 0
        outcomes = write_all(files)
    except Stop as stop:
        print(f"✗ {stop}", file=sys.stderr)
        return 1

    print(f"Settings for {settings['pet']['name'].strip()}, from config.yml:")
    for outcome in outcomes:
        print(f"  {'✓ written  ' if outcome.changed else '· unchanged'}  {outcome.path}")
    for note in warnings(settings):
        print(f"  ! {note}")
    if any(outcome.changed and outcome.path == "rpi-capture/capture.env" for outcome in outcomes):
        print("  → The Pi's settings changed: copy rpi-capture/ to the Pi and run  sudo sh rpi-capture/install.sh")
    return 0


if __name__ == "__main__":
    sys.exit(main())
