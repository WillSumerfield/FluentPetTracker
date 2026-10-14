"""Utterances and the study's figures, worked out from Presses.

An Exchange is stored; its Utterances are not. They are worked out here from who is counted as
the Presser of each Press, so a Review Decision splits or joins them the moment it is made.
"""

from __future__ import annotations

import statistics
from bisect import bisect_right
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

PERIODS = ("day", "week", "month", "all")
PRESSERS = ("pet", "human")

# How many periods of the chosen size the trend charts look back over, the chosen one included.
TREND_LENGTH = {"day": 14, "week": 12, "month": 12}

WORD_GAP_BINS = ((1, "under 1 s"), (2, "1–2 s"), (5, "2–5 s"), (10, "5–10 s"), (20, "10–20 s"), (None, "over 20 s"))
UTTERANCE_GAP_BINS = (
    (30, "under 30 s"),
    (60, "30–60 s"),
    (300, "1–5 min"),
    (900, "5–15 min"),
    (3600, "15–60 min"),
    (3 * 3600, "1–3 h"),
    (None, "over 3 h"),
)

LONGEST_LENGTH_BAR = 12  # longer Utterances share the last bar of the length histogram
TOP_PHRASES = 15
TOP_REPLIES = 10
TRANSITION_WORDS = 12

Span = Tuple[float, float]


# ---- Utterances ---------------------------------------------------------------


def split_utterances(presses: Sequence[dict]) -> List[dict]:
    """Cut one Exchange's Presses, given in order, into Utterances.

    An Utterance ends where the Presser changes. A discarded Press is not real, so it is left out
    and does not end anything. An Ambiguous Press with no Review Decision stands on its own side
    of the cut: until someone decides it, it cannot be said to continue either neighbour.
    """
    utterances: List[dict] = []
    for press in presses:
        if press["presser"] == "discarded":
            continue
        if utterances and utterances[-1]["presser"] == press["presser"]:
            current = utterances[-1]
            current["press_ids"].append(press["id"])
            current["words"].append(press["word"])
            current["times"].append(press["pressed_at"])
            current["ended_at"] = press["pressed_at"]
        else:
            utterances.append(
                {
                    "presser": press["presser"],
                    "exchange_id": press["exchange_id"],
                    "press_ids": [press["id"]],
                    "words": [press["word"]],
                    "times": [press["pressed_at"]],
                    "started_at": press["pressed_at"],
                    "ended_at": press["pressed_at"],
                }
            )
    return utterances


def all_utterances(presses: Iterable[dict]) -> List[dict]:
    """Utterances of many Exchanges, oldest first. Presses must come ordered by Exchange, then position."""
    utterances: List[dict] = []
    exchange: List[dict] = []
    for press in presses:
        if exchange and exchange[-1]["exchange_id"] != press["exchange_id"]:
            utterances.extend(split_utterances(exchange))
            exchange = []
        exchange.append(press)
    utterances.extend(split_utterances(exchange))
    utterances.sort(key=lambda utterance: utterance["started_at"])
    return utterances


# ---- Time ---------------------------------------------------------------------


def start_of(day: date) -> float:
    return datetime.combine(day, datetime.min.time()).timestamp()


def split_by_hour(start: float, end: float) -> Iterator[Span]:
    """Cut a span into pieces that each lie inside one clock hour, in local time."""
    while start < end:
        moment = datetime.fromtimestamp(start)
        next_hour = start - (moment.minute * 60 + moment.second + moment.microsecond / 1e6) + 3600
        piece_end = min(end, next_hour)
        yield start, piece_end
        start = piece_end


def observed_hours_by_day(windows: Sequence[Span]) -> Dict[date, float]:
    observed: Dict[date, float] = {}
    for start, end in windows:
        for piece_start, piece_end in split_by_hour(start, end):
            day = date.fromtimestamp(piece_start)
            observed[day] = observed.get(day, 0.0) + (piece_end - piece_start) / 3600
    return observed


def period_bounds(period: str, anchor: date, first_day: date, today: date) -> Tuple[date, date]:
    """The first day of the period holding `anchor`, and the first day after it."""
    if period == "day":
        return anchor, anchor + timedelta(days=1)
    if period == "week":
        monday = anchor - timedelta(days=anchor.weekday())
        return monday, monday + timedelta(days=7)
    if period == "month":
        first = anchor.replace(day=1)
        return first, _next_month(first)
    return first_day, today + timedelta(days=1)


def _next_month(first: date) -> date:
    return (first.replace(day=28) + timedelta(days=4)).replace(day=1)


def _previous(period: str, start: date) -> date:
    if period == "day":
        return start - timedelta(days=1)
    if period == "week":
        return start - timedelta(days=7)
    return (start - timedelta(days=1)).replace(day=1)


def period_label(period: str, start: date, end: date) -> str:
    if period == "day":
        return f"{start:%a} {start.day} {start:%b %Y}"
    if period == "week":
        last = end - timedelta(days=1)
        return f"{start.day} {start:%b} – {last.day} {last:%b %Y}"
    if period == "month":
        return f"{start:%B %Y}"
    return "Whole study"


def _short_label(period: str, start: date) -> str:
    if period == "day":
        return f"{start.day} {start:%b}"
    if period == "week":
        return f"{start.day} {start:%b}"
    return f"{start:%b %y}"


def _trend_buckets(period: str, start: date, first_day: date, today: date) -> List[Tuple[date, date, str]]:
    """The periods a trend chart covers, oldest first, ending with the chosen one."""
    if period == "all":
        # The whole study has no earlier period to compare with, so its trend runs month by month.
        buckets = []
        month = first_day.replace(day=1)
        while month <= today:
            buckets.append((month, _next_month(month), _short_label("month", month)))
            month = _next_month(month)
        return buckets
    buckets = []
    bucket_start = start
    for _ in range(TREND_LENGTH[period]):
        bucket_end = period_bounds(period, bucket_start, first_day, today)[1]
        buckets.append((bucket_start, bucket_end, _short_label(period, bucket_start)))
        bucket_start = _previous(period, bucket_start)
    return list(reversed(buckets))


# ---- Figures ------------------------------------------------------------------


def build(
    presses: Sequence[dict],
    windows: Sequence[Span],
    period: str,
    anchor: date,
    today: date,
    response_seconds: float,
    counted_day_hours: float,
) -> dict:
    """Everything the Metrics page shows for the period holding `anchor`.

    `presses` is every Press of the study with its counted Presser, ordered by Exchange and
    position. A day counts towards "per day" figures only when more than `counted_day_hours`
    of it were observed.
    """
    utterances = all_utterances(presses)
    observed = observed_hours_by_day(windows)
    earliest = min([utterance["started_at"] for utterance in utterances[:1]] + [start for start, _ in windows[:1]],
                   default=start_of(today))
    first_day = min(date.fromtimestamp(earliest), today)
    anchor = min(max(anchor, first_day), today)

    start, end = period_bounds(period, anchor, first_day, today)
    counted_days = {day for day, hours in observed.items() if hours > counted_day_hours}
    days_in_period = [day for day in _days(start, min(end, today + timedelta(days=1)))]
    buckets = _trend_buckets(period, start, first_day, today)
    replies = _replies(utterances, response_seconds)

    undecided = [u for u in utterances if u["presser"] == "ambiguous" and _within(u, start, end)]
    result = {
        "period": period,
        "label": period_label(period, start, end),
        "start": start.isoformat(),
        "end": (end - timedelta(days=1)).isoformat(),
        "first_day": first_day.isoformat(),
        "today": today.isoformat(),
        "previous": _previous(period, start).isoformat() if period != "all" and start > first_day else None,
        "next": end.isoformat() if period != "all" and end <= today else None,
        "observed_hours": round(sum(observed.get(day, 0.0) for day in days_in_period), 1),
        "days_in_period": len(days_in_period),
        "counted_days": sum(1 for day in days_in_period if day in counted_days),
        "counted_day_hours": counted_day_hours,
        "response_seconds": response_seconds,
        "undecided_utterances": len(undecided),
        "undecided_presses": sum(len(u["words"]) for u in undecided),
        "trend_labels": [label for _start, _end, label in buckets],
        "trend_unit": "month" if period == "all" else period,
    }
    for presser in PRESSERS:
        own = [u for u in utterances if u["presser"] == presser]
        result[presser] = _section(
            own, replies[presser], windows, start, end, days_in_period, counted_days, buckets, today, period
        )
    return result


def _section(
    own: List[dict],
    replies: List[dict],
    windows: Sequence[Span],
    start: date,
    end: date,
    days_in_period: List[date],
    counted_days: set,
    buckets: List[Tuple[date, date, str]],
    today: date,
    period: str,
) -> dict:
    """One Presser's figures. `own` is every Utterance by that Presser in the study, oldest first."""
    chosen = [u for u in own if _within(u, start, end)]
    lengths = [len(u["words"]) for u in chosen]
    words = Counter(word for u in chosen for word in u["words"])

    first_use: Dict[str, float] = {}
    for utterance in own:
        for word, pressed_at in zip(utterance["words"], utterance["times"]):
            first_use.setdefault(word, pressed_at)
    period_start, period_end = start_of(start), start_of(end)
    new_words = sorted(word for word, at in first_use.items() if period_start <= at < period_end)
    known_before = {word for word, at in first_use.items() if at < period_start}

    by_hour = [0] * 24
    for utterance in chosen:
        for pressed_at in utterance["times"]:
            by_hour[datetime.fromtimestamp(pressed_at).hour] += 1

    in_period_replies = [reply for reply in replies if _within(reply["reply"], start, end)]
    longest = max(chosen, key=lambda u: len(u["words"]), default=None)

    return {
        "utterances": len(chosen),
        "words": sum(lengths),
        "distinct_words": len(words),
        "length": {
            "longest": len(longest["words"]) if longest else None,
            "longest_words": longest["words"] if longest else [],
            "longest_at": longest["started_at"] if longest else None,
            "mean": _rounded(statistics.fmean(lengths)) if lengths else None,
            "median": _rounded(statistics.median(lengths)) if lengths else None,
            "std_dev": _rounded(statistics.stdev(lengths)) if len(lengths) > 1 else None,
            "histogram": _length_histogram(lengths),
        },
        "word_gaps": _binned(_word_gaps(chosen), WORD_GAP_BINS),
        "utterance_gaps": _binned(_utterance_gaps(own, windows, start, end), UTTERANCE_GAP_BINS),
        "words_per_day": _words_per_day(chosen, days_in_period, counted_days),
        "word_frequency": [{"word": word, "count": count} for word, count in _ranked(words)],
        "phrases": [
            {"words": list(phrase), "count": count}
            for phrase, count in _ranked(Counter(tuple(u["words"]) for u in chosen))[:TOP_PHRASES]
        ],
        "length_by_word": _length_by_word(chosen),
        "repetition": _repetition(chosen),
        "by_hour": by_hour,
        "transitions": _transitions(chosen, words),
        "new_words": new_words,
        "dropped_words": sorted(known_before - set(words)) if period != "all" else [],
        "first_uses": [
            {"word": word, "at": at} for word, at in sorted(first_use.items(), key=lambda item: item[1])
        ],
        "replies": {
            "count": len(in_period_replies),
            "share": _rounded(len(in_period_replies) / len(chosen)) if chosen else None,
            "median_delay": _rounded(statistics.median(r["delay"] for r in in_period_replies), 1)
            if in_period_replies
            else None,
            "top": [
                {"prompt": list(prompt), "reply": list(reply), "count": count}
                for (prompt, reply), count in _ranked(
                    Counter((tuple(r["prompt"]["words"]), tuple(r["reply"]["words"])) for r in in_period_replies)
                )[:TOP_REPLIES]
            ],
        },
        "trend": _trend(own, first_use, buckets, counted_days, today),
    }


def _trend(
    own: List[dict],
    first_use: Dict[str, float],
    buckets: List[Tuple[date, date, str]],
    counted_days: set,
    today: date,
) -> List[dict]:
    points = []
    for start, end, label in buckets:
        chosen = [u for u in own if _within(u, start, end)]
        lengths = [len(u["words"]) for u in chosen]
        days = _days(start, min(end, today + timedelta(days=1)))
        points.append(
            {
                "label": label,
                "start": start.isoformat(),
                "words": sum(lengths),
                "utterances": len(chosen),
                "mean_length": _rounded(statistics.fmean(lengths)) if lengths else None,
                "longest": max(lengths, default=None),
                "words_per_day": _words_per_day(chosen, days, counted_days)["mean"],
                "vocabulary": sum(1 for at in first_use.values() if at < start_of(end)),
            }
        )
    return points


def _words_per_day(chosen: List[dict], days: List[date], counted_days: set) -> dict:
    """Mean Words per day over the days that were observed for long enough to count."""
    counted = [day for day in days if day in counted_days]
    by_day: Counter = Counter()
    for utterance in chosen:
        for pressed_at in utterance["times"]:
            by_day[date.fromtimestamp(pressed_at)] += 1
    return {
        "mean": _rounded(sum(by_day[day] for day in counted) / len(counted), 1) if counted else None,
        "counted_days": len(counted),
        "days": [{"date": day.isoformat(), "words": by_day[day], "counted": day in counted_days} for day in days],
    }


def _length_histogram(lengths: List[int]) -> List[dict]:
    if not lengths:
        return []
    counts = Counter(min(length, LONGEST_LENGTH_BAR) for length in lengths)
    top = max(counts)
    return [
        {"label": f"{length}+" if length == LONGEST_LENGTH_BAR else str(length), "count": counts[length]}
        for length in range(1, top + 1)
    ]


def _word_gaps(chosen: List[dict]) -> List[float]:
    """Seconds between one Press and the next inside the same Utterance."""
    return [later - earlier for u in chosen for earlier, later in zip(u["times"], u["times"][1:])]


def _utterance_gaps(own: List[dict], windows: Sequence[Span], start: date, end: date) -> List[float]:
    """Seconds from the end of an Utterance to the start of the same Presser's next one.

    Only counted when both lie in one Observation Window: across a gap in observation there may
    have been Utterances nobody recorded, so the pause cannot be measured.
    """
    window_starts = [window_start for window_start, _ in windows]
    gaps = []
    for earlier, later in zip(own, own[1:]):
        if not _within(later, start, end):
            continue
        index = bisect_right(window_starts, earlier["ended_at"]) - 1
        if index >= 0 and later["started_at"] <= windows[index][1]:
            gaps.append(later["started_at"] - earlier["ended_at"])
    return gaps


def _binned(values: List[float], bins: Sequence[Tuple[Optional[float], str]]) -> dict:
    counts = [0] * len(bins)
    for value in values:
        for index, (limit, _label) in enumerate(bins):
            if limit is None or value < limit:
                counts[index] += 1
                break
    return {
        "count": len(values),
        "median": _rounded(statistics.median(values), 1) if values else None,
        "mean": _rounded(statistics.fmean(values), 1) if values else None,
        "histogram": [{"label": label, "count": count} for (_limit, label), count in zip(bins, counts)],
    }


def _length_by_word(chosen: List[dict]) -> List[dict]:
    """For each Word, the mean length of the Utterances it appears in."""
    lengths: Dict[str, List[int]] = {}
    for utterance in chosen:
        for word in set(utterance["words"]):
            lengths.setdefault(word, []).append(len(utterance["words"]))
    rows = [
        {"word": word, "utterances": len(found), "mean_length": _rounded(statistics.fmean(found))}
        for word, found in lengths.items()
    ]
    return sorted(rows, key=lambda row: (-row["mean_length"], row["word"]))


def _repetition(chosen: List[dict]) -> dict:
    """How often a Word is pressed again straight after itself."""
    containing: Counter = Counter()
    repeating: Counter = Counter()
    repeated_utterances = 0
    for utterance in chosen:
        repeated = {word for word, following in zip(utterance["words"], utterance["words"][1:]) if word == following}
        containing.update(set(utterance["words"]))
        repeating.update(repeated)
        repeated_utterances += bool(repeated)
    rows = [
        {
            "word": word,
            "utterances": containing[word],
            "repeated": repeating[word],
            "share": _rounded(repeating[word] / containing[word]),
        }
        for word in containing
        if repeating[word]
    ]
    return {
        "utterances": repeated_utterances,
        "share": _rounded(repeated_utterances / len(chosen)) if chosen else None,
        "by_word": sorted(rows, key=lambda row: (-row["repeated"], row["word"])),
    }


def _transitions(chosen: List[dict], words: Counter) -> dict:
    """How often each of the most used Words is followed by each other inside an Utterance."""
    shown = [word for word, _count in _ranked(words)[:TRANSITION_WORDS]]
    index = {word: position for position, word in enumerate(shown)}
    counts = [[0] * len(shown) for _ in shown]
    for utterance in chosen:
        for word, following in zip(utterance["words"], utterance["words"][1:]):
            if word in index and following in index:
                counts[index[word]][index[following]] += 1
    return {"words": shown, "counts": counts}


def _replies(utterances: List[dict], response_seconds: float) -> Dict[str, List[dict]]:
    """Utterances that answer the other Presser: the next one said, within the response time.

    Undecided Ambiguous Utterances are passed over, since nobody yet knows whose they are.
    """
    replies: Dict[str, List[dict]] = {presser: [] for presser in PRESSERS}
    decided = [u for u in utterances if u["presser"] in PRESSERS]
    for prompt, reply in zip(decided, decided[1:]):
        delay = reply["started_at"] - prompt["ended_at"]
        if prompt["presser"] != reply["presser"] and 0 <= delay <= response_seconds:
            replies[reply["presser"]].append({"prompt": prompt, "reply": reply, "delay": delay})
    return replies


def _within(utterance: dict, start: date, end: date) -> bool:
    return start_of(start) <= utterance["started_at"] < start_of(end)


def _days(start: date, end: date) -> List[date]:
    return [start + timedelta(days=offset) for offset in range(max(0, (end - start).days))]


def _ranked(counts: Counter) -> List[tuple]:
    """Most common first; ties in a steady order."""
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _rounded(value: float, digits: int = 2) -> float:
    return round(value, digits)
