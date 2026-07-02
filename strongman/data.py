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


class SeedError(RuntimeError):
    """A strongman seed file is missing or malformed. Raised with a message
    that names the file and the underlying cause, so a broken deploy (e.g. the
    seed dir dropped by an over-broad rsync exclude — see commit 17993cc) fails
    loudly here instead of surfacing as an opaque KeyError three layers up."""


def _load(name: str) -> Any:
    path = _DATA_DIR / name
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        raise SeedError(
            f"Strongman seed file missing: {path}. The seed/ directory must "
            f"ship with the module (check deploy rsync excludes)."
        ) from exc
    except json.JSONDecodeError as exc:
        raise SeedError(f"Strongman seed file {name} is not valid JSON: {exc}") from exc


def _require_keys(obj: dict, keys: list[str], where: str) -> None:
    missing = [k for k in keys if k not in obj]
    if missing:
        raise SeedError(f"{where} is missing required key(s): {', '.join(missing)}")


PLAN: dict = _load("plan_config.json")
_EXERCISES: dict = _load("exercises.json")
MEALS: dict = _load("meals.json")

# Fail fast on a structurally broken plan config rather than KeyError-ing deep
# in the engine on the first prescription.
_require_keys(
    PLAN,
    ["start_date", "weeks", "rep_schemes", "lifts", "weekly_schedule", "dietary_rules"],
    "plan_config.json",
)
if not isinstance(_EXERCISES.get("exercises"), list):
    raise SeedError("exercises.json must contain an 'exercises' list.")

START_DATE: str = PLAN["start_date"]            # "2026-06-15" (a Monday)
TOTAL_WEEKS: int = PLAN["weeks"]                # 52
SANDBAG_OVER_BAR_FROM_WEEK: int = PLAN["rep_schemes"]["sandbag_over_bar_starts_week"]  # 5
DEFAULT_BODYWEIGHT_LB: int = PLAN["athlete"]["bodyweight_lb"]   # 285
WATER_RANGE_L: list = PLAN["athlete"]["water_l_per_day"]        # [3.5, 4.0]
CREATINE_G: int = PLAN["athlete"]["creatine_g_per_day"]        # 10
REP_SCHEMES: dict = PLAN["rep_schemes"]
LOADING: dict = PLAN.get(
    "loading",
    {"trap_bar_lb": 45, "plates": [], "plate_aware_lifts": [], "warmup_lifts": {}},
)
# lift_id -> empty-implement (bar) weight in lb, for the lifts that get a
# progressive warm-up ramp at all. Fixed implements (sandbag, kettlebell,
# fixed dumbbells, hand carries) are absent and get NO ramp.
WARMUP_LIFTS: dict = LOADING.get("warmup_lifts", {})
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
