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


def lift_trajectory(lift_id: str, overrides: Optional[TmOverrides] = None) -> dict:
    """Full 52-week projected climb: a per-week working-weight series (for
    charting the staircase) plus a per-quarter summary (TM + top build set).
    Honors saved per-quarter TM overrides. Faithful port of progression.ts
    ``liftTrajectory``."""
    overrides = overrides or {}
    weekly = [
        {
            "week": week,
            "weight": target_weight(lift_id, week, overrides),
            "type": week_type(week),
            "quarter": quarter_of(week),
        }
        for week in range(1, data.TOTAL_WEEKS + 1)
    ]
    quarters = []
    for q in range(1, math.ceil(data.TOTAL_WEEKS / 13) + 1):
        # The quarter's top build set is its last build week (wq 11, k=9).
        top_build_week = (q - 1) * 13 + 11
        quarters.append(
            {
                "quarter": q,
                "tm": resolve_tm(lift_id, q, overrides),
                "top_build_set": target_weight(lift_id, top_build_week, overrides),
            }
        )
    return {"weekly": weekly, "quarters": quarters}


# Percent-of-working-weight warm-up ramp, fewer reps as the bar gets heavier.
_WARMUP_STEPS = [(0.4, 5), (0.55, 4), (0.7, 3), (0.85, 2)]


def warmup_ramp(working_weight: float, round_to: int = 10) -> list[dict]:
    """Warm-up ramp up to a working weight. Rounds each set to the nearest 10 lb
    (fewer plate changes), drops any set that meets/exceeds the working weight,
    and collapses duplicate weights — so light lifts get fewer warm-up sets.
    Faithful port of progression.ts ``warmupRamp``."""
    out: list[dict] = []
    last = 0
    for pct, reps in _WARMUP_STEPS:
        weight = mround(working_weight * pct, round_to)
        if weight <= 0 or weight >= working_weight or weight <= last:
            continue
        out.append({"weight": weight, "reps": reps})
        last = weight
    return out


def warmup_sets(lift_id: str, week: int, overrides: Optional[TmOverrides] = None) -> list[dict]:
    """Warm-up ramp for a lift on a given week, from the resolved working weight
    (honors TM overrides). Faithful port of progression.ts ``warmupSets``."""
    return warmup_ramp(target_weight(lift_id, week, overrides or {}))


def _greedy_plates(per_side_target: float, stock: list) -> list:
    """Fill a per-side weight from largest plate down, never using more of a size
    than is available per side (floor(count/2)). `stock` = [{"lb", "count"}] of
    TOTAL plates owned. The returned plates' sum may fall short if you run out."""
    out: list = []
    rem = per_side_target
    for plate in sorted(stock, key=lambda p: p["lb"], reverse=True):
        avail = plate["count"] // 2
        while avail > 0 and rem >= plate["lb"] - 1e-9:
            out.append(plate["lb"])
            rem -= plate["lb"]
            avail -= 1
    return out


def warmup_ramp_plated(working_weight: float, bar_lb: float, stock: list) -> list[dict]:
    """Warm-up ramp for a lift on a real bar: each step snaps to a weight you can
    actually load (bar + a symmetric plate pair), rounding the per-side load to
    the nearest 5 lb, then loads it from the plates you own (capped by quantity
    per side). The set's weight reflects what's truly loadable. Skips anything
    at/below the empty bar or at/above the working weight, collapses duplicates.
    Port of progression.ts ``warmupRampPlated``."""
    out: list[dict] = []
    last = 0
    for pct, reps in _WARMUP_STEPS:
        per_side_raw = (working_weight * pct - bar_lb) / 2
        if per_side_raw <= 0:
            continue
        per_side_target = round(per_side_raw / 5) * 5
        if per_side_target <= 0:
            continue
        per_side = _greedy_plates(per_side_target, stock)
        loaded = sum(per_side)
        if loaded <= 0:
            continue
        weight = int(bar_lb + 2 * loaded)
        if weight >= working_weight or weight <= last:
            continue
        out.append({"weight": weight, "reps": reps, "per_side": per_side})
        last = weight
    return out


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
