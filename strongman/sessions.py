"""Day-session generation — a faithful port of the standalone app's
sessions.ts. Given (date, user state) it returns the day's session: which
exercises, at what computed weight, sets/reps/RPE, with verbatim safety
strings and equipment substitutions. Session *structure* is transcribed from
plan_config `sessions`; weights come from engine.target_weight; safety/cues/
names come from exercises.json. Nothing numeric is invented.
"""

from __future__ import annotations

from typing import Optional

from . import data
from .engine import (
    build_index,
    day_for_date,
    mround,
    resolve_tm,
    target_weight,
)

SMITH_SUB = "Until the bag arrives: Smith machine squat 3x10 off the Smith-squat TM, +10 lb/week."
AXLE_SUB = (
    "Until the axle arrives: DB clean & press at matching effort — continental clean kept tidy, "
    "no bicep yank."
)
SANDBAG_EVENT_SUB = (
    "Sandbag not owned yet — substitute a comparable odd-object/stone, or skip until it arrives."
)

LOWER = [
    {
        "exercise_id": "trap_bar_deadlift",
        "load_lift_id": "trap_bar_deadlift",
        "scheme": "mains",
        "rest": "3-4 min",
        "notes": "Straps allowed on top sets from week 3 on.",
    },
    {
        "exercise_id": "sandbag_bear_hug_squat",
        "load_lift_id": "sandbag",
        "sets": 3,
        "reps": "8",
        "rest": "2-3 min",
        "sub_when_unowned": "sandbag",
        "sub_load_lift_id": "smith_squat",
        "sub_note": SMITH_SUB,
    },
    {
        "exercise_id": "db_split_squat",
        "load_lift_id": "db_split_squat",
        "sets": 3,
        "reps": "8/leg",
        "rest": "90 sec",
    },
    {
        "exercise_id": "suitcase_carry",
        "load_lift_id": "suitcase_carry",
        "sets": 4,
        "reps": "50 ft/side",
        "rest": "2 min",
        "carry": True,
        "notes": "Hips and shoulders level — the work is refusing to lean.",
    },
]

PRESS_ACCESSORIES = [
    {"exercise_id": "db_bench", "load_lift_id": "db_bench", "sets": 3, "reps": "8-10", "rest": "2 min"},
    {"exercise_id": "db_row", "load_lift_id": "db_row", "sets": 4, "reps": "10/side", "rest": "90 sec"},
    {"exercise_id": "skullcrusher", "load_lift_id": "skullcrusher", "sets": 3, "reps": "12", "rest": "superset"},
    {
        "exercise_id": "curl",
        "load_lift_id": "curl",
        "sets": 3,
        "reps": "12",
        "rest": "90 sec",
        "notes": "Biceps tendon insurance for events. When 12 are clean, +5 lb.",
    },
]

EVENTS = [
    {
        "exercise_id": "sandbag_to_shoulder",
        "load_lift_id": "sandbag",
        "sets": 6,
        "reps": "2/side",
        "rest": "2-3 min",
        "skip_on_deload": True,
        "sub_when_unowned": "sandbag",
        "sub_note": SANDBAG_EVENT_SUB,
        "notes": "Lap, hug, hips. NEVER curl it up.",
    },
    {
        "exercise_id": "sandbag_over_bar",
        "load_lift_id": "sandbag",
        "sets": 3,
        "reps": "3",
        "rest": "2 min",
        "from_week": 5,
        "skip_on_deload": True,
        "sub_when_unowned": "sandbag",
        "sub_note": SANDBAG_EVENT_SUB,
        "notes": "Smith bar pinned 48-52 in.",
    },
    {
        "exercise_id": "farmers_carry_trap_bar",
        "load_lift_id": "farmers_carry",
        "sets": 4,
        "reps": "50 ft (Q2+: 2x50 ft timed)",
        "rest": "2-3 min",
        "carry": True,
    },
    {
        "exercise_id": "sandbag_bear_hug_carry",
        "load_lift_id": "sandbag",
        "sets": 4,
        "reps": "50 ft",
        "rest": "2 min",
        "carry": True,
        "sub_when_unowned": "sandbag",
        "sub_note": SANDBAG_EVENT_SUB,
    },
    {
        "exercise_id": "axle_deadlift_doh",
        "load_lift_id": "axle_dl_doh",
        "sets": 3,
        "reps": "5",
        "rest": "2 min",
        "skip_on_deload": True,
        "notes": "NO STRAPS ever — this is the grip work.",
    },
    {"exercise_id": "kb_swing", "load_lift_id": "kb_swing", "sets": 5, "reps": "15", "rest": "60-90 sec"},
]

GPP = [
    {
        "exercise_id": "kb_swing",
        "load_lift_id": "kb_swing",
        "sets": 10,
        "reps": "30s on / 90s off",
        "notes": "Intervals — keep the hinge crisp.",
    },
    {
        "exercise_id": "sandbag_bear_hug_carry",
        "load_half_sandbag": True,
        "sets": 4,
        "reps": "100 ft",
        "sub_when_unowned": "sandbag",
        "sub_note": SANDBAG_EVENT_SUB,
    },
    {"exercise_id": "walk", "reps": "20-30 min"},
]

BLUEPRINTS = {"lower": LOWER, "events": EVENTS, "gpp_optional": GPP}

REST_RECOVERY = ["Easy walk 20-30 min", "Water 3.5-4 L across the day", "Creatine 10 g"]


def _title_case(slug: str) -> str:
    return " ".join(w[:1].upper() + w[1:] for w in slug.split("_"))


def _mains_scheme(k: int) -> dict:
    for r in data.REP_SCHEMES["mains"]:
        lo, hi = r["k_range"][0], r["k_range"][1]
        if lo <= k <= hi:
            return {"sets": r["sets"], "reps": str(r["reps"]), "rpe_cap": r["rpe_cap"]}
    return {"sets": 4, "reps": "3", "rpe_cap": "8"}


def _lib_fields(exercise_id: str) -> dict:
    lib = data.get_exercise(exercise_id)
    return {
        "name": lib["name"] if lib else _title_case(exercise_id),
        "safety": lib.get("safety") if lib else None,
        "cues": lib.get("cues") if lib else None,
        "equipment": lib.get("equipment") if lib else None,
        "demo_search": lib.get("demo_search") if lib else None,
    }


def _build_item(b: dict, day: dict, st: dict) -> Optional[dict]:
    week = day["week"]
    from_week = b.get("from_week")
    if from_week and week < from_week:
        return None
    deload = day["week_type"] == "deload"
    if deload and b.get("skip_on_deload"):
        return None

    load_lift_id = b.get("load_lift_id")
    substitution_note = None
    equip = st["equipment"]
    if b.get("sub_when_unowned") == "sandbag" and not equip["sandbag"]:
        substitution_note = b.get("sub_note") or SANDBAG_EVENT_SUB
        if b.get("sub_load_lift_id"):
            load_lift_id = b["sub_load_lift_id"]
    elif b.get("sub_when_unowned") == "axle" and not equip["axle"]:
        substitution_note = b.get("sub_note") or AXLE_SUB

    weight_lb: Optional[int] = None
    if b.get("load_half_sandbag"):
        weight_lb = mround(resolve_tm("sandbag", day["quarter"], st["tms"]) * 0.5, 25)
    elif load_lift_id:
        weight_lb = target_weight(load_lift_id, week, st["tms"])

    sets = b.get("sets")
    reps = b.get("reps")
    rpe_cap = b.get("rpe_cap")
    notes = b.get("notes")

    if b.get("scheme") == "mains":
        if deload:
            d = data.REP_SCHEMES["deload"]
            sets, reps, rpe_cap = d["sets"], str(d["reps"]), d["rpe_cap"]
        else:
            m = _mains_scheme(build_index(week))
            sets, reps, rpe_cap = m["sets"], m["reps"], m["rpe_cap"]
        if day["is_calibration"]:
            notes = (
                (notes or "")
                + " Week 1 is calibration — find your RPE-7 x5 and save it as your Q1 TM."
            ).strip()
    elif deload:
        if b.get("carry"):
            sets = 2
        elif isinstance(b.get("sets"), int):
            sets = min(b["sets"], 3)
        rpe_cap = "<=6"

    item = {
        "exercise_id": b["exercise_id"],
        "lift_id": load_lift_id,
        "sets": sets,
        "reps": reps,
        "weight_lb": weight_lb,
        "rpe_cap": rpe_cap,
        "rest": b.get("rest"),
        "notes": notes,
        "substitution_note": substitution_note,
    }
    item.update(_lib_fields(b["exercise_id"]))
    return item


def _press_block(day: dict, st: dict) -> list:
    load = target_weight("axle_press", day["week"], st["tms"])
    sub = AXLE_SUB if not st["equipment"]["axle"] else None

    def make(exercise_id, sets, reps, rpe_cap, notes=None, skip_warmup=False):
        item = {
            "exercise_id": exercise_id,
            "lift_id": "axle_press",
            "sets": sets,
            "reps": reps,
            "weight_lb": load,
            "rpe_cap": rpe_cap,
            "rest": "3 min",
            "notes": notes,
            "substitution_note": sub,
            # The push press runs at the SAME load right after the strict press;
            # it shares the strict press's warm-up, so don't repeat the ramp.
            "skip_warmup": skip_warmup,
        }
        item.update(_lib_fields(exercise_id))
        return item

    if day["week_type"] == "deload":
        return [make("axle_clean_strict_press", 3, "5", "<=6", "Deload — keep it crisp and light.")]
    k = build_index(day["week"])
    if day["quarter"] == 1 and k <= 3:
        q1 = data.REP_SCHEMES["press_q1_k1to3"]
        return [make("axle_clean_strict_press", q1["sets"], str(q1["reps"]), q1["rpe_cap"])]
    strict = data.REP_SCHEMES["press_thereafter"][0]
    push = data.REP_SCHEMES["press_thereafter"][1]
    return [
        make("axle_clean_strict_press", strict["sets"], str(strict["reps"]), strict["rpe_cap"]),
        make(
            "axle_push_press",
            push["sets"],
            str(push["reps"]),
            push["rpe_cap"],
            "Same load as the strict target; the legs buy the extra reps.",
            skip_warmup=True,
        ),
    ]


def _base(day: dict, title: str) -> dict:
    return {
        "date": day["date"],
        "week": day["week"],
        "quarter": day["quarter"],
        "week_type": day["week_type"],
        "session_kind": day["session_kind"],
        "is_calibration": day["is_calibration"],
        "is_test_week": day["is_test_week"],
        "title": title,
        "items": [],
        "recovery": [],
    }


def _heavy_single(exercise_id: str, lift_id: str, label: str, notes: str) -> dict:
    item = {
        "exercise_id": exercise_id,
        "lift_id": lift_id,
        "sets": "Work to heavy single",
        "reps": "1 @ RPE 8",
        "weight_lb": None,
        "rest": "as needed",
        "notes": f"{label} {notes}",
        "substitution_note": None,
    }
    item.update(_lib_fields(exercise_id))
    return item


def _test_week_session(day: dict, st: dict) -> dict:
    if day["dow"] == "mon":
        s = _base(day, "Test week — deadlift heavy single")
        s["items"] = [
            _heavy_single(
                "trap_bar_deadlift",
                "trap_bar_deadlift",
                "Trap bar deadlift — work up to a heavy single @ RPE 8.",
                "Log the single, then set next quarter's TM (~85-90% of it, or your new clean 5RM).",
            )
        ]
        return s
    if day["dow"] == "wed":
        s = _base(day, "Test week — press heavy single")
        s["items"] = [
            _heavy_single(
                "axle_clean_strict_press",
                "axle_press",
                "Axle strict press — heavy single @ RPE 8.",
                "Log it, then update the press TM for next quarter.",
            )
        ]
        return s
    if day["dow"] == "sat":
        s = _base(day, "Test week — events")
        farm = data.get_lift("farmers_carry")
        farmers = {
            "exercise_id": "farmers_carry_trap_bar",
            "lift_id": "farmers_carry",
            "sets": "Max distance",
            "reps": "1 run @ TM",
            "weight_lb": mround(resolve_tm("farmers_carry", day["quarter"], st["tms"]), farm["round_to"]),
            "rest": "full",
            "notes": "Carry max distance at your farmer TM. Log the distance.",
            "substitution_note": None,
        }
        farmers.update(_lib_fields("farmers_carry_trap_bar"))
        over_bar = {
            "exercise_id": "sandbag_over_bar",
            "lift_id": "sandbag",
            "sets": "60 s",
            "reps": "Max reps",
            "weight_lb": target_weight("sandbag", day["week"], st["tms"]),
            "rest": "full",
            "notes": "Max reps over the bar in 60 seconds. Log reps, then set the next sandbag tier.",
            "substitution_note": None,
        }
        over_bar.update(_lib_fields("sandbag_over_bar"))
        s["items"] = [farmers, over_bar]
        return s
    s = _base(day, "Test week — rest")
    s["recovery"] = list(REST_RECOVERY)
    return s


def session_for(date_iso: str, state: Optional[dict] = None) -> Optional[dict]:
    day = day_for_date(date_iso)
    if day is None:
        return None
    state = state or {}
    st = {
        "tms": state.get("tms") or {},
        "equipment": state.get("equipment") or {"sandbag": False, "axle": False},
    }

    if day["week_type"] == "test":
        return _test_week_session(day, st)

    if day["session_kind"] == "rest":
        s = _base(day, "Rest & recovery")
        s["recovery"] = list(REST_RECOVERY)
        return s

    s = _base(day, f"{_title_case(day['session_kind'])} ({day['week_type']})")
    items: list = []
    if day["session_kind"] == "press_upper":
        items.extend(_press_block(day, st))
        for b in PRESS_ACCESSORIES:
            it = _build_item(b, day, st)
            if it:
                items.append(it)
    else:
        for b in BLUEPRINTS.get(day["session_kind"], []):
            it = _build_item(b, day, st)
            if it:
                items.append(it)
    s["items"] = items
    return s
