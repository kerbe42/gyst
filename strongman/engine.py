"""Pure progression math, calendar, and date helpers.

A faithful port of the standalone app's `src/engine` (progression.ts,
dates.ts, calendar.ts). Given (lift, week, optional TM overrides) it returns
the day's prescribed working weight deterministically. No Reflex, no I/O.

Rules (verified against data/test_vectors.json `engine_rules`):
    q    = ceil(week / 13)
    wq   = week - (q-1)*13
    type : wq==13 -> test; wq in {4,8,12} -> deload; else build
    k    = wq - (wq>4) - (wq>8)                       (build index, 1..9)
    build  target = mround(TM[q] + (k-1)*increment, round_to), then cap
    deload target = mround(TM[q] * 0.6, round_to)
    flat (sandbag) = mround(TM[q], round_to)
    TM[q] suggestion = TM[q-1] + q_deltas[q-2]        (user-overridable per slot)
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Optional

from . import data

# A TM override map: lift_id -> [q1, q2, q3, q4], each int or None.
TmOverrides = dict


# ---- progression -----------------------------------------------------------
def mround(value: float, multiple: int) -> int:
    """Excel MROUND: round to nearest `multiple`, ties round up. Robust to
    IEEE754 drift like 335*0.6 == 200.99999999999997."""
    if multiple == 0:
        return int(value)
    return int(math.floor(value / multiple + 0.5) * multiple)


def quarter_of(week: int) -> int:
    return math.ceil(week / 13)


def week_in_quarter(week: int) -> int:
    return week - (quarter_of(week) - 1) * 13


def week_type(week: int) -> str:
    wq = week_in_quarter(week)
    if wq == 13:
        return "test"
    if wq in (4, 8, 12):
        return "deload"
    return "build"


def build_index(week: int) -> int:
    wq = week_in_quarter(week)
    return wq - (1 if wq > 4 else 0) - (1 if wq > 8 else 0)


def resolve_tm(lift_id: str, quarter: int, overrides: Optional[TmOverrides] = None) -> int:
    """Effective training max for a lift in a quarter, honoring a per-quarter
    override and otherwise chaining the suggestion off the effective prior
    quarter."""
    overrides = overrides or {}
    lift = data.get_lift(lift_id)
    slots = overrides.get(lift_id)
    slot = slots[quarter - 1] if slots and len(slots) >= quarter else None
    if slot is not None:
        return slot
    if quarter <= 1:
        return lift["tm_q1_placeholder"]
    deltas = lift["q_deltas"]
    delta = deltas[quarter - 2] if (quarter - 2) < len(deltas) else 0
    return resolve_tm(lift_id, quarter - 1, overrides) + delta


def target_weight(lift_id: str, week: int, overrides: Optional[TmOverrides] = None) -> int:
    """Prescribed working weight for a lift on a given week. Test weeks are
    RPE-driven; this returns the quarter's top build load as a reference."""
    overrides = overrides or {}
    lift = data.get_lift(lift_id)
    tm = resolve_tm(lift_id, quarter_of(week), overrides)
    typ = week_type(week)
    if lift.get("flat_within_quarter"):
        raw = mround(tm, lift["round_to"])
    elif typ == "deload":
        raw = mround(tm * 0.6, lift["round_to"])
    else:
        k = min(9, max(1, build_index(week)))
        raw = mround(tm + (k - 1) * lift["build_increment"], lift["round_to"])
    cap = lift.get("cap")
    return min(raw, cap) if cap is not None else raw


# ---- dates (calendar dates, ISO YYYY-MM-DD) --------------------------------
# Python date.weekday(): Monday == 0.
_DOW_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _parse(iso: str) -> date:
    y, m, d = (int(x) for x in iso.split("-"))
    return date(y, m, d)


def add_days(iso: str, n: int) -> str:
    return (_parse(iso) + timedelta(days=n)).isoformat()


def dow_of(iso: str) -> str:
    return _DOW_NAMES[_parse(iso).weekday()]


def day_index_of(iso: str) -> int:
    return (_parse(iso) - _parse(data.START_DATE)).days


def iso_for_day_index(i: int) -> str:
    return add_days(data.START_DATE, i)


def today_iso(today: Optional[date] = None) -> str:
    return (today or date.today()).isoformat()


# ---- the 52-week calendar --------------------------------------------------
_TOTAL_DAYS = data.TOTAL_WEEKS * 7  # 364
_calendar_cache: Optional[list] = None


def build_calendar() -> list[dict]:
    global _calendar_cache
    if _calendar_cache is not None:
        return _calendar_cache
    days: list[dict] = []
    for i in range(_TOTAL_DAYS):
        week = i // 7 + 1
        iso = iso_for_day_index(i)
        dow = dow_of(iso)
        typ = week_type(week)
        days.append(
            {
                "day_index": i,
                "date": iso,
                "week": week,
                "quarter": quarter_of(week),
                "week_type": typ,
                "dow": dow,
                "session_kind": data.session_kind_for_dow(dow),
                "is_calibration": week == 1,
                "is_test_week": typ == "test",
            }
        )
    _calendar_cache = days
    return days


def week_days(week: int) -> list[dict]:
    return [d for d in build_calendar() if d["week"] == week]


def day_for_date(iso: str) -> Optional[dict]:
    return next((d for d in build_calendar() if d["date"] == iso), None)


def day_for_index(i: int) -> Optional[dict]:
    cal = build_calendar()
    return cal[i] if 0 <= i < len(cal) else None
