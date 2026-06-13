"""Parity tests for the ported strongman engine.

Proves the Python port reproduces every verified spreadsheet weight vector and
all calendar / nutrition / session invariants — the same contract the
standalone TypeScript engine satisfies.

Run from the gyst repo root:
    python -m strongman.tests.test_engine
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow direct execution (python strongman/tests/test_engine.py) too.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from strongman import data, nutrition  # noqa: E402
from strongman.engine import (  # noqa: E402
    add_days,
    build_calendar,
    build_index,
    day_for_date,
    dow_of,
    lift_trajectory,
    mround,
    quarter_of,
    target_weight,
    warmup_ramp,
    warmup_ramp_plated,
    warmup_sets,
    week_days,
    week_in_quarter,
    week_type,
)
from strongman.sessions import session_for  # noqa: E402

_FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        _FAILS.append(msg)


def eq(actual, expected, msg: str) -> None:
    check(actual == expected, f"{msg}: expected {expected!r}, got {actual!r}")


_VECTORS = json.loads((Path(data.__file__).resolve().parent / "seed" / "test_vectors.json").read_text())

OWNED = {"equipment": {"sandbag": True, "axle": True}}


def date_for(week: int, dow: str) -> str:
    return next(d["date"] for d in week_days(week) if d["dow"] == dow)


def _ids(session) -> list:
    return [i["exercise_id"] for i in session["items"]] if session else []


def test_mround():
    eq(mround(189, 5), 190, "mround 189")
    eq(mround(201, 5), 200, "mround 201")
    eq(mround(112, 25), 100, "mround 112/25")
    eq(mround(113, 25), 125, "mround 113/25")
    eq(mround(2.5, 5), 5, "mround tie 2.5")
    eq(mround(7.5, 5), 10, "mround tie 7.5")
    eq(mround(12.5, 5), 15, "mround tie 12.5")
    eq(mround(335 * 0.6, 5), 200, "mround float-drift 335*0.6")
    eq(mround(315 * 0.6, 5), 190, "mround float-drift 315*0.6")


def test_week_math():
    eq([quarter_of(w) for w in (1, 13, 14, 26, 27, 39, 40, 52)], [1, 1, 2, 2, 3, 3, 4, 4], "quarter_of")
    eq([week_in_quarter(w) for w in (1, 13, 14, 26, 40)], [1, 13, 1, 13, 1], "week_in_quarter")
    eq([week_type(w) for w in (1, 4, 8, 12, 13, 26, 39, 52, 5)],
       ["build", "deload", "deload", "deload", "test", "test", "test", "test", "build"], "week_type")
    eq([build_index(w) for w in (1, 3, 5, 7, 9, 11, 14, 40)], [1, 3, 4, 6, 7, 9, 1, 1], "build_index")


def test_vectors():
    for v in _VECTORS["vectors"]:
        label = f"week {v['week']} {v['lift']} ({v['week_type']})"
        eq(target_weight(v["lift"], v["week"]), v["expected_lb"], label)


def test_cap_and_overrides():
    eq(target_weight("suitcase_carry", 11), 90, "suitcase cap @wk11")
    tms = {"trap_bar_deadlift": [405, None, None, None]}
    eq(target_weight("trap_bar_deadlift", 1, tms), 405, "trap override q1 wk1")
    eq(target_weight("trap_bar_deadlift", 14, tms), 425, "trap override chains q2 wk14")


def test_lift_trajectory():
    t = lift_trajectory("trap_bar_deadlift")
    eq(len(t["weekly"]), 52, "trajectory weekly length")
    eq(t["weekly"][0], {"week": 1, "weight": 315, "type": "build", "quarter": 1}, "wk1 point")
    eq(t["weekly"][3], {"week": 4, "weight": 190, "type": "deload", "quarter": 1}, "wk4 deload point")
    eq(t["weekly"][10], {"week": 11, "weight": 395, "type": "build", "quarter": 1}, "wk11 top build point")
    eq(t["weekly"][12]["type"], "test", "wk13 test type")
    eq(len(t["quarters"]), 4, "4 quarter milestones")
    eq(t["quarters"][0], {"quarter": 1, "tm": 315, "top_build_set": 395}, "Q1 milestone")
    eq(t["quarters"][3], {"quarter": 4, "tm": 360, "top_build_set": 440}, "Q4 milestone")
    tms = {"trap_bar_deadlift": [405, None, None, None]}
    t2 = lift_trajectory("trap_bar_deadlift", tms)
    eq(t2["weekly"][0]["weight"], 405, "override wk1")
    eq(t2["quarters"][0]["tm"], 405, "override Q1 tm")
    eq(t2["quarters"][1]["tm"], 425, "override chains Q2 tm")
    sc = lift_trajectory("suitcase_carry")
    eq(max(p["weight"] for p in sc["weekly"]), 90, "suitcase capped at 90")
    sb = lift_trajectory("sandbag")
    q1w = {p["weight"] for p in sb["weekly"] if p["quarter"] == 1}
    eq(len(q1w), 1, "sandbag flat within quarter")


def test_warmup_sets():
    # warmup_ramp builds straight from a working weight (what the UI uses).
    eq(warmup_ramp(315),
       [{"weight": 130, "reps": 5}, {"weight": 170, "reps": 4},
        {"weight": 220, "reps": 3}, {"weight": 270, "reps": 2}], "warmup_ramp 315")
    eq(warmup_ramp(40), [{"weight": 20, "reps": 5}, {"weight": 30, "reps": 3}], "warmup_ramp 40 collapses")
    eq(warmup_ramp(0), [], "warmup_ramp 0 empty")
    eq(warmup_sets("trap_bar_deadlift", 1),
       [{"weight": 130, "reps": 5}, {"weight": 170, "reps": 4},
        {"weight": 220, "reps": 3}, {"weight": 270, "reps": 2}], "trap warmup wk1")
    eq(warmup_sets("db_split_squat", 1),
       [{"weight": 20, "reps": 5}, {"weight": 30, "reps": 3}], "db split warmup collapses")
    tms = {"trap_bar_deadlift": [405, None, None, None]}
    w = warmup_sets("trap_bar_deadlift", 1, tms)
    eq(w[0]["weight"], 160, "warmup honors override")
    check(all(s["weight"] < 405 for s in w), "warmups below working weight")
    for lid in ("trap_bar_deadlift", "smith_squat", "axle_dl_doh", "db_bench", "sandbag"):
        for wk in (1, 6, 11, 40):
            working = target_weight(lid, wk)
            ramp = warmup_sets(lid, wk)
            for i, s in enumerate(ramp):
                check(s["weight"] < working, f"{lid} wk{wk} warmup below working")
                if i > 0:
                    check(ramp[i]["weight"] > ramp[i - 1]["weight"], f"{lid} wk{wk} strictly increasing")


def test_warmup_ramp_plated():
    plates = [45, 25, 10, 5, 2.5]
    eq(warmup_ramp_plated(315, 54, plates),
       [{"weight": 124, "reps": 5, "per_side": [25, 10]},
        {"weight": 174, "reps": 4, "per_side": [45, 10, 5]},
        {"weight": 224, "reps": 3, "per_side": [45, 25, 10, 5]},
        {"weight": 264, "reps": 2, "per_side": [45, 45, 10, 5]}],
       "plated warmup 315 on 54lb bar")
    for working in (315, 235, 405):
        for s in warmup_ramp_plated(working, 54, plates):
            check(54 + 2 * sum(s["per_side"]) == s["weight"], f"{working} loadable")
            check(s["weight"] < working, f"{working} below working")
            check(s["weight"] > 54, f"{working} above bar")


def test_calendar():
    cal = build_calendar()
    eq(len(cal), 364, "calendar length")
    first = cal[0]
    eq((first["date"], first["dow"], first["week"], first["quarter"], first["is_calibration"]),
       ("2026-06-15", "mon", 1, 1, True), "first day")
    last = cal[363]
    eq((last["date"], last["dow"], last["week"], last["is_test_week"]),
       ("2027-06-13", "sun", 52, True), "last day")
    test_weeks = sorted({d["week"] for d in cal if d["is_test_week"]})
    eq(test_weeks, [13, 26, 39, 52], "test weeks")
    cal_weeks = sorted({d["week"] for d in cal if d["is_calibration"]})
    eq(cal_weeks, [1], "calibration weeks")
    valid = {"lower", "gpp_optional", "press_upper", "events", "rest"}
    check(all(d["session_kind"] in valid for d in cal), "every day has a valid session kind")
    for w in range(1, 53):
        days = week_days(w)
        eq(len(days), 7, f"week {w} has 7 days")
        eq((days[0]["dow"], days[6]["dow"]), ("mon", "sun"), f"week {w} mon-first")


def test_dates():
    eq(dow_of("2026-06-15"), "mon", "start is monday")
    eq(add_days("2026-06-15", 364), "2027-06-14", "add 364 days")
    eq(day_for_date("2026-06-14"), None, "before plan")
    eq(day_for_date("2027-06-14"), None, "after plan")


def test_nutrition():
    eq(nutrition.protein_target_g(285), 230, "protein target 285")
    eq(nutrition.protein_target_g(200), 160, "protein target 200")
    eq(nutrition.protein_target_g(250), 200, "protein target 250")
    eq(nutrition.protein_target_g(300), 240, "protein target 300")
    eq(nutrition.fixed_template_totals(), {"protein_g": 197, "kcal": 2535}, "fixed template totals")
    avg = nutrition.dinner_rotation_weekly_average()
    check(abs(avg["protein_g"] - 237) <= 1, f"rotation protein avg ~237 (got {avg['protein_g']})")
    check(abs(avg["kcal"] - 3308) <= 15, f"rotation kcal avg ~3308 (got {avg['kcal']})")
    eq(nutrition.scan_meals_for_violations(), [], "no excluded ingredients in library")
    hits = nutrition.find_excluded_ingredients("scrambled eggs with tofu and a side of beans")
    check("eggs" in hits and "tofu" in hits and "beans" in hits, "scanner catches eggs/tofu/beans")
    eq(nutrition.find_excluded_ingredients("Pork tenderloin, cooked"), [], "pork is allowed")


def test_meal_recipes():
    recipes = nutrition.meal_recipes()
    anchor = next(m for m in recipes if m["id"] == "anchor_bowl")
    eq(len(anchor["items"]), 5, "anchor bowl 5 items")
    thigh = next(m for m in recipes if m["id"] == "dinner_thigh")
    eq(len(thigh["items"]), 4, "dinner thigh = source + 3 sides")
    eq(sum(i.get("p", 0) for i in thigh["items"]), thigh["protein_g"], "thigh items sum protein")
    eq(sum(i.get("kcal", 0) for i in thigh["items"]), thigh["kcal"], "thigh items sum kcal")
    oats = next(m for m in recipes if m["id"] == "protein_oats")
    eq(oats["prep"], "Cook oats in milk, stir whey in off heat.", "protein oats prep")
    eq(len(nutrition.fixed_template_meals()), 5, "fixed template = 5 meals")
    eq(nutrition.dinner_for_dow("mon")["id"], "dinner_thigh", "mon dinner")
    eq(nutrition.dinner_for_dow("wed")["id"], "dinner_pork", "wed dinner")
    eq(nutrition.dinner_for_dow("sat")["id"], "dinner_turkey", "sat dinner")


def test_sessions():
    eq(session_for("2026-06-14"), None, "outside plan -> None")

    rest = session_for(date_for(1, "thu"))
    eq(rest["items"], [], "rest day no items")
    check(len(rest["recovery"]) > 0, "rest day has recovery")

    mon = session_for(date_for(1, "mon"), OWNED)
    main = mon["items"][0]
    eq(main["exercise_id"], "trap_bar_deadlift", "lower main id")
    eq((main["weight_lb"], main["sets"], main["reps"], main["rpe_cap"]), (315, 4, "5", "7"), "lower main scheme")
    check(mon["is_calibration"], "wk1 calibration")

    no_bag = session_for(date_for(1, "mon"), {"equipment": {"sandbag": False, "axle": True}})
    bag = next(i for i in no_bag["items"] if i["exercise_id"] == "sandbag_bear_hug_squat")
    check(bag["substitution_note"] and "smith" in bag["substitution_note"].lower(), "smith substitution when no bag")
    owned_bag = next(i for i in mon["items"] if i["exercise_id"] == "sandbag_bear_hug_squat")
    check(not owned_bag["substitution_note"], "no substitution when bag owned")

    no_axle = session_for(date_for(1, "wed"), {"equipment": {"sandbag": True, "axle": False}})
    press = next(i for i in no_axle["items"] if i["exercise_id"] == "axle_clean_strict_press")
    check(press["substitution_note"] and ("db" in press["substitution_note"].lower() or "dumbbell" in press["substitution_note"].lower()),
          "axle substitution when no axle")

    wed1 = session_for(date_for(1, "wed"), OWNED)
    presses = [i for i in wed1["items"] if i["exercise_id"] in ("axle_clean_strict_press", "axle_push_press")]
    eq(len(presses), 1, "Q1 k1-3 single strict press")
    eq((presses[0]["sets"], presses[0]["reps"], presses[0]["weight_lb"]), (5, "3", 105), "Q1 strict press scheme")

    wed5 = session_for(date_for(5, "wed"), OWNED)
    p5 = [i for i in wed5["items"] if i["exercise_id"] in ("axle_clean_strict_press", "axle_push_press")]
    eq([i["exercise_id"] for i in p5], ["axle_clean_strict_press", "axle_push_press"], "thereafter strict+push")
    eq((p5[0]["weight_lb"], p5[1]["weight_lb"]), (120, 120), "push uses same load")

    check("sandbag_over_bar" not in _ids(session_for(date_for(1, "sat"), OWNED)), "no over-bar before wk5")
    sat5 = session_for(date_for(5, "sat"), OWNED)
    sob = next((i for i in sat5["items"] if i["exercise_id"] == "sandbag_over_bar"), None)
    check(sob is not None and sob["weight_lb"] == 100, "over-bar from wk5 at flat sandbag")
    check("sandbag_over_bar" not in _ids(session_for(date_for(8, "sat"), OWNED)), "no over-bar on deload sat")

    mon4 = session_for(date_for(4, "mon"), OWNED)
    eq(mon4["week_type"], "deload", "wk4 deload")
    m4 = mon4["items"][0]
    eq((m4["weight_lb"], m4["sets"], m4["reps"]), (190, 3, "5"), "deload lower main")

    ev8 = _ids(session_for(date_for(8, "sat"), OWNED))
    for skipped in ("sandbag_to_shoulder", "sandbag_over_bar", "axle_deadlift_doh"):
        check(skipped not in ev8, f"deload events skip {skipped}")
    check("farmers_carry_trap_bar" in ev8, "deload events keep carries")

    t13 = session_for(date_for(13, "mon"), OWNED)
    check(t13["is_test_week"], "wk13 test")
    tm = t13["items"][0]
    eq(tm["weight_lb"], None, "test single no weight")
    check("single" in str(tm["sets"]).lower(), "test sets says single")
    check(any(w in (tm["notes"] or "").lower() for w in ("tm", "next quarter", "update")), "test note prompts TM update")
    eq(session_for(date_for(13, "tue"), OWNED)["items"], [], "test-week tue rest")

    sat5_items = session_for(date_for(5, "sat"), OWNED)["items"]
    axle = next(i for i in sat5_items if i["exercise_id"] == "axle_deadlift_doh")
    eq(axle["safety"], "Strapless permanently — this slot IS the grip training.", "axle safety verbatim")
    shoulder = next(i for i in sat5_items if i["exercise_id"] == "sandbag_to_shoulder")
    eq(shoulder["safety"],
       "NEVER reverse-curl the bag up. Lap, hug, hips. This rule is non-negotiable — it is the biceps-tear mechanism.",
       "shoulder safety verbatim")


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    if _FAILS:
        print(f"FAILED ({len(_FAILS)}):")
        for f in _FAILS:
            print("  -", f)
        return 1
    print(f"OK — {len(tests)} test groups, all assertions passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
