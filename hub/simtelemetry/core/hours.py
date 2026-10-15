"""Opening hours and the business day.

A cafe may close after midnight: a closing hour of 0 to 6 that is not after the opening hour means the next day
("opens 16:00, closes 02:00 (next day)"). The business day then starts at the closing hour, so a lap at 01:30
still counts for the evening before: "today" boards, challenges, analytics and the closing-time auto-end all use it.
"""

from __future__ import annotations

import datetime as dt

LATEST_NEXT_DAY_CLOSE = 6     # closing at 00:00-06:00 may mean the next day


def closes_next_day(open_hour: int, close_hour: int) -> bool:
    return close_hour <= open_hour


def hours_problem(open_hour: int, close_hour: int) -> str | None:
    """Plain-English reason the hours can't be used, or None when they are fine."""
    if close_hour == open_hour or (close_hour < open_hour and close_hour > LATEST_NEXT_DAY_CLOSE):
        return ("the closing time must be after the opening time, or between 00:00 and "
                f"{LATEST_NEXT_DAY_CLOSE:02d}:00 for a cafe that closes after midnight")
    return None


def derived_day_start(open_hour: int, close_hour: int) -> int:
    """The hour the business day starts: the closing hour when the cafe closes after midnight, else midnight."""
    return close_hour % 24 if closes_next_day(open_hour, close_hour) else 0


def open_minutes(open_hour: int, close_hour: int) -> int:
    """Minutes the cafe is open per day."""
    span = close_hour - open_hour
    return (span if span > 0 else span + 24) * 60


def business_day(when: dt.datetime, day_start_hour: int) -> dt.date:
    return (when - dt.timedelta(hours=day_start_hour)).date()


def _next_at_hour(after: dt.datetime, hour: int) -> dt.datetime:
    """The first `hour`:00 strictly after `after` (hour 24 is the next midnight)."""
    at = after.replace(hour=hour % 24, minute=0, second=0, microsecond=0)
    while at <= after:
        at += dt.timedelta(days=1)
    return at


def auto_end_at(started: dt.datetime, close_hour: int, day_start_hour: int) -> dt.datetime:
    """When a session started at `started` is ended automatically at the latest: the first closing time after it
    started, or the start of the next business day if that comes first (a session started after closing time,
    or one left open from a previous day)."""
    return min(_next_at_hour(started, close_hour), _next_at_hour(started, day_start_hour))


def hour_label(hour: int, open_hour: int | None = None) -> str:
    """'02:00 (next day)' for a closing hour after midnight, else '22:00'."""
    text = f"{hour % 24:02d}:00"
    return text + " (next day)" if open_hour is not None and closes_next_day(open_hour, hour) else text
