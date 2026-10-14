"""Who was in the Board Zone, and when, built from Frigate's events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

PET = "pet"
HUMAN = "human"
AMBIGUOUS = "ambiguous"

KEEP_SECONDS = 600.0


@dataclass(frozen=True)
class Attribution:
    presser: str
    ambiguity: Optional[str]  # 'both' or 'nobody' when the Press is ambiguous


def attribute(subjects: Set[str]) -> Attribution:
    """Exactly one subject in the Board Zone is the Presser; anything else is an Ambiguous Press."""
    if subjects == {PET}:
        return Attribution(PET, None)
    if subjects == {HUMAN}:
        return Attribution(HUMAN, None)
    return Attribution(AMBIGUOUS, "both" if subjects else "nobody")


class PresenceTracker:
    """Remembers the stretches of time each subject spent in the Board Zone."""

    def __init__(self, camera: str, zone: str, pet_labels: Iterable[str]) -> None:
        self._camera = camera
        self._zone = zone
        # Several labels may stand for the Pet: a small cat is often labelled a dog.
        self._subject_by_label = {"person": HUMAN, **{label: PET for label in pet_labels}}
        self._present: Dict[str, Tuple[str, float]] = {}  # Frigate object id -> (subject, since)
        self._past: List[Tuple[str, float, float]] = []  # (subject, from, until)

    def handle_event(self, event: dict, now: float) -> None:
        """Take one message from Frigate's events topic."""
        after = event.get("after") or {}
        object_id = after.get("id")
        subject = self._subject_by_label.get(after.get("label"))
        if after.get("camera") != self._camera or subject is None or not object_id:
            return

        ended = event.get("type") == "end"
        in_zone = not ended and self._zone in (after.get("current_zones") or [])
        seen_at = float(after.get("frame_time") or now)

        if in_zone and object_id not in self._present:
            self._present[object_id] = (subject, seen_at)
        elif not in_zone and object_id in self._present:
            present_subject, since = self._present.pop(object_id)
            until = float(after.get("end_time") or seen_at) if ended else seen_at
            self._past.append((present_subject, since, max(since, until)))

    def clear_present(self, now: float) -> None:
        """Close every open stretch. Call when Frigate goes away, since its 'end' messages will be missed."""
        for subject, since in self._present.values():
            self._past.append((subject, since, max(since, now)))
        self._present.clear()

    def subjects_between(self, start: float, end: float) -> Set[str]:
        """The subjects that were in the Board Zone at any point between two times."""
        subjects = {subject for subject, since in self._present.values() if since <= end}
        subjects |= {subject for subject, since, until in self._past if since <= end and until >= start}
        return subjects

    def forget_before(self, time: float) -> None:
        self._past = [stretch for stretch in self._past if stretch[2] >= time]
