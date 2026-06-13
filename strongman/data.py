"""Typed access to the strongman domain data files.

These JSON files are the source of truth (ported verbatim from the standalone
app): the engine reads training/nutrition numbers from here, it never
re-derives them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

_DATA_DIR: Path = Path(__file__).resolve().parent / "seed"


def _load(name: str) -> Any:
    with open(_DATA_DIR / name, encoding="utf-8") as fh:
        return json.load(fh)


PLAN: dict = _load("plan_config.json")
_EXERCISES: dict = _load("exercises.json")
MEALS: dict = _load("meals.json")

START_DATE: str = PLAN["start_date"]            # "2026-06-15" (a Monday)
TOTAL_WEEKS: int = PLAN["weeks"]                # 52
SANDBAG_OVER_BAR_FROM_WEEK: int = PLAN["rep_schemes"]["sandbag_over_bar_starts_week"]  # 5
DEFAULT_BODYWEIGHT_LB: int = PLAN["athlete"]["bodyweight_lb"]   # 285
WATER_RANGE_L: list = PLAN["athlete"]["water_l_per_day"]        # [3.5, 4.0]
CREATINE_G: int = PLAN["athlete"]["creatine_g_per_day"]        # 10
REP_SCHEMES: dict = PLAN["rep_schemes"]
LOADING: dict = PLAN.get(
    "loading",
    {"trap_bar_lb": 45, "plate_pairs_lb": [45, 25, 10, 5, 2.5], "plate_aware_lifts": []},
)
DIETARY_RULES: dict = PLAN["dietary_rules"]
FLARE_PROTOCOL_SWAP: str = PLAN["dietary_rules"]["flare_protocol_swap"]

DOW_ORDER: list[str] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

_LIFTS: list[dict] = PLAN["lifts"]
_LIFTS_BY_ID: dict[str, dict] = {lift["id"]: lift for lift in _LIFTS}
_EX_BY_ID: dict[str, dict] = {ex["id"]: ex for ex in _EXERCISES["exercises"]}


def get_lift(lift_id: str) -> dict:
    lift = _LIFTS_BY_ID.get(lift_id)
    if lift is None:
        raise KeyError(f"Unknown lift id: {lift_id}")
    return lift


def all_lifts() -> list[dict]:
    return _LIFTS


def get_exercise(exercise_id: str) -> Optional[dict]:
    return _EX_BY_ID.get(exercise_id)


def all_exercises() -> list[dict]:
    return _EXERCISES["exercises"]


def session_kind_for_dow(dow: str) -> str:
    return PLAN["weekly_schedule"][dow]


def demo_search_url(query: str) -> str:
    from urllib.parse import quote_plus
    return f"https://www.youtube.com/results?search_query={quote_plus(query)}"
