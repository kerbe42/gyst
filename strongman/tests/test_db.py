"""Round-trip tests for the strongman SQLite layer. Uses a throwaway DB.

Run from the gyst repo root:
    python -m strongman.tests.test_db
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import config  # noqa: E402

config.STRONGMAN_DB_PATH = Path(tempfile.mkdtemp()) / "strongman.db"

from strongman import db  # noqa: E402

_FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _FAILS.append(msg)


def run() -> int:
    db.init_db()

    # settings
    s = db.get_settings()
    check(s["bodyweight_lb"] == 285, "default bodyweight 285")
    check(s["kcal_target"] is None, "default kcal None")
    check(s["equipment"] == {"sandbag": False, "axle": False}, "default equipment")
    db.set_setting("bodyweight_lb", 290)
    db.set_setting("kcal_target", 3300)
    db.set_equipment(True, False)
    s = db.get_settings()
    check(s["bodyweight_lb"] == 290 and s["kcal_target"] == 3300 and s["equipment"]["sandbag"] is True,
          "settings round-trip")
    db.set_pinned_demo("trap_bar_deadlift", "https://x")
    check(db.get_settings()["pinned_demos"].get("trap_bar_deadlift") == "https://x", "pin demo")
    db.set_pinned_demo("trap_bar_deadlift", None)
    check("trap_bar_deadlift" not in db.get_settings()["pinned_demos"], "unpin demo")

    # tms
    db.set_tm("trap_bar_deadlift", 1, 320)
    db.set_tm("trap_bar_deadlift", 3, 360)
    check(db.get_tms().get("trap_bar_deadlift") == [320, None, 360, None], "tm set")
    db.set_tm("trap_bar_deadlift", 1, None)
    db.set_tm("trap_bar_deadlift", 3, None)
    check("trap_bar_deadlift" not in db.get_tms(), "tm fully cleared drops row")

    # overrides
    db.set_override("2026-06-15", {"skipped": True, "skip_reason": "tweak", "exercises": {}})
    ov = db.get_override("2026-06-15")
    check(ov and ov["skipped"] and ov["skip_reason"] == "tweak", "override set")
    db.set_override("2026-06-15", {"skipped": False, "skip_reason": None,
                                   "exercises": {"trap_bar_deadlift": {"weightLb": 300}}})
    ov = db.get_override("2026-06-15")
    check(ov["exercises"]["trap_bar_deadlift"]["weightLb"] == 300, "override exercises json")
    db.set_override("2026-06-15", None)
    check(db.get_override("2026-06-15") is None, "override cleared")

    # training log
    db.set_exercise_sets("2026-06-15", "trap_bar_deadlift", [
        {"set_num": 1, "weight_lb": 315, "reps": 5, "rpe": 7, "note": None},
        {"set_num": 2, "weight_lb": 315, "reps": 5, "rpe": 7, "note": None},
    ])
    sets = db.list_sets("2026-06-15", "trap_bar_deadlift")
    check(len(sets) == 2 and sets[0]["weight_lb"] == 315, "sets logged")
    check(db.top_sets("trap_bar_deadlift") == [{"date": "2026-06-15", "weight_lb": 315}], "top sets")
    check("trap_bar_deadlift" in db.logged_exercise_ids(), "logged exercise ids")
    db.set_exercise_sets("2026-06-15", "trap_bar_deadlift", [])
    check(db.list_sets("2026-06-15", "trap_bar_deadlift") == [], "sets cleared")

    # meal log
    mid = db.add_meal("2026-06-15", "anchor_bowl", "Anchor Bowl", 53, 855, 1)
    check(len(db.list_meals("2026-06-15")) == 1, "meal added")
    check(db.meal_totals("2026-06-15")["protein_g"] == 53, "meal totals")
    db.remove_meal(mid)
    check(db.list_meals("2026-06-15") == [], "meal removed")

    # daily checks
    db.set_checks("2026-06-15", creatine=True)
    db.set_checks("2026-06-15", flare_protocol=True)
    c = db.get_checks("2026-06-15")
    check(c["creatine"] and c["flare_protocol"] and c["water_l"] == 0, "checks merge without clobber")

    # bodyweight
    db.set_bodyweight("2026-06-20", 284)
    db.set_bodyweight("2026-06-15", 285)
    db.set_bodyweight("2026-06-15", 283)
    bw = db.list_bodyweight()
    check([b["date"] for b in bw] == ["2026-06-15", "2026-06-20"], "bodyweight sorted")
    check(bw[0]["lb"] == 283, "bodyweight upsert same date")

    es = db.engine_state()
    check("tms" in es and "equipment" in es, "engine_state shape")

    if _FAILS:
        print(f"FAILED ({len(_FAILS)}):")
        for f in _FAILS:
            print("  -", f)
        return 1
    print("OK — db round-trips passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
