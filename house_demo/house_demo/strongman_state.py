"""Reflex state for the Strongman training + nutrition module.

All training/nutrition numbers come from the pure engine (`strongman.engine`,
`strongman.sessions`, `strongman.nutrition`); user state is persisted in
`strongman.db`. Display strings are computed server-side here so the pages
render plain values (no Var gymnastics over optional numbers).
"""

from __future__ import annotations

from datetime import date
from typing import Optional, TypedDict

import reflex as rx

from house_demo.states import _require_auth
from strongman import data as sm_data
from strongman import db as sm_db
from strongman import nutrition as sm_nutrition
from strongman.engine import (
    build_calendar,
    day_for_date,
    day_index_of,
    dow_of,
    iso_for_day_index,
    quarter_of,
    resolve_tm,
    today_iso,
)
from strongman.sessions import session_for

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_WDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_MULTIPLIERS = ["0.5", "0.75", "1", "1.5", "2"]


def _fmt_date(iso: str) -> str:
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{_WDAYS[date(y, m, d).weekday()]}, {_MONTHS[m - 1]} {d}"


def _fmt_weight(lb) -> str:
    return "—" if lb is None else f"{int(lb) if float(lb).is_integer() else lb} lb"


def _prescription(item: dict) -> str:
    sets, reps, w = item.get("sets"), item.get("reps"), item.get("weight_lb")
    head = ""
    if sets is not None:
        head = f"{sets}" + (f" × {reps}" if reps else "")
    elif reps:
        head = str(reps)
    if w is not None:
        head = (head + f" @ {_fmt_weight(w)}").strip()
    return head


def _numeric_reps(reps) -> str:
    if not reps:
        return ""
    s = str(reps)
    num = ""
    for ch in s:
        if ch.isdigit():
            num += ch
        else:
            break
    return num


# ---- display row shapes ----------------------------------------------------
class ItemRow(TypedDict, total=False):
    exercise_id: str
    name: str
    prescription: str
    rpe: str
    rest: str
    notes: str
    safety: str
    substitution_note: str
    cues_text: str
    demo_url: str
    is_logged: bool
    logged_summary: str


class CalRow(TypedDict):
    exercise_id: str
    name: str
    lift_id: str
    quarter: int
    top: float
    top_label: str
    already_set: bool


class CalCell(TypedDict):
    date: str
    dom: str
    dow_initial: str
    kind: str
    tone: str  # build | deload | test | rest


class WeekRow(TypedDict):
    week: int
    quarter: int
    tag: str
    cells: list[CalCell]


class MealRow(TypedDict, total=False):
    id: int
    name: str
    macros: str


class RecipeRow(TypedDict, total=False):
    id: str
    name: str
    group: str
    macros: str
    items_text: str
    prep: str
    note: str
    tag: str


class ExerciseRow(TypedDict, total=False):
    id: str
    name: str
    type: str
    safety: str
    cues_text: str
    equipment_text: str
    note: str
    substitution: str
    demo_url: str
    pinned: bool
    pinned_url: str


class TmRow(TypedDict):
    lift_id: str
    name: str
    cap: str
    q1: str
    q2: str
    q3: str
    q4: str
    q1_set: bool
    q2_set: bool
    q3_set: bool
    q4_set: bool


class Point(TypedDict):
    x: str
    y: float


def _item_row(item: dict, logged: list[dict]) -> ItemRow:
    my = [s for s in logged if s["exercise_id"] == item["exercise_id"]]
    summary = ", ".join(
        f"{int(s['weight_lb']) if s.get('weight_lb') is not None else '—'}×{s.get('reps') or '—'}"
        for s in my
    )
    return ItemRow(
        exercise_id=item["exercise_id"],
        name=item.get("name") or item["exercise_id"],
        prescription=_prescription(item),
        rpe=(f"RPE {item['rpe_cap']}" if item.get("rpe_cap") else ""),
        rest=(f"rest {item['rest']}" if item.get("rest") else ""),
        notes=item.get("notes") or "",
        safety=item.get("safety") or "",
        substitution_note=item.get("substitution_note") or "",
        cues_text=" · ".join(item.get("cues") or []),
        demo_url=(sm_data.demo_search_url(item["demo_search"]) if item.get("demo_search") else ""),
        is_logged=bool(my),
        logged_summary=summary,
    )


class StrongmanState(rx.State):
    # shared
    the_date: str = ""

    # ---- Today ----
    header_line: str = ""
    badge_week: str = ""
    badge_type: str = ""
    is_calibration: bool = False
    is_test_week: bool = False
    is_rest: bool = False
    pre_plan_msg: str = ""
    post_plan: bool = False
    session_title: str = ""
    today_items: list[ItemRow] = []
    recovery: list[str] = []
    cal_cards: list[CalRow] = []
    # daily checks
    water_l: float = 0.0
    creatine_on: bool = False
    flare_on: bool = False
    # log dialog
    log_open: bool = False
    log_exercise_id: str = ""
    log_exercise_name: str = ""
    log_weight: str = ""
    log_reps: str = ""
    log_rpe: str = ""
    log_sets: str = "1"
    log_note: str = ""

    # ---- Plan ----
    weeks: list[WeekRow] = []
    selected_date: str = ""
    detail_header: str = ""
    detail_badge: str = ""
    detail_items: list[ItemRow] = []
    detail_skipped: bool = False
    detail_skip_reason: str = ""

    # ---- Meals ----
    protein_total: int = 0
    kcal_total: int = 0
    protein_target: int = 0
    kcal_target_label: str = ""
    kcal_set: bool = False
    template_rows: list[RecipeRow] = []
    template_total_label: str = ""
    dinner_row: Optional[RecipeRow] = None
    library_rows: list[RecipeRow] = []
    library_open: bool = False
    big_dairy_rows: list[RecipeRow] = []
    big_flesh_rows: list[RecipeRow] = []
    big_omad_rows: list[RecipeRow] = []
    meals_per_day: int = 2
    protein_per_meal: int = 0
    logged_meals: list[MealRow] = []
    custom_name: str = ""
    custom_protein: str = ""
    custom_kcal: str = ""
    custom_warning: str = ""

    # ---- Exercises ----
    exercise_rows: list[ExerciseRow] = []
    ex_query: str = ""
    pin_open_id: str = ""
    pin_url: str = ""

    # ---- Progress ----
    bw_series: list[Point] = []
    bw_input: str = ""
    logged_ex_options: list[str] = []
    progress_ex: str = ""
    top_series: list[Point] = []
    protein_series: list[Point] = []
    tm_rows: list[TmRow] = []

    # ---- Settings ----
    bodyweight_input: str = ""
    kcal_input: str = ""
    equip_sandbag: bool = False
    equip_axle: bool = False
    settings_tm_rows: list[TmRow] = []
    confirm_reset: bool = False
    settings_msg: str = ""

    # ===================== shared helpers =====================
    def _eng(self) -> dict:
        return sm_db.engine_state()

    def _load_checks(self, iso: str):
        c = sm_db.get_checks(iso)
        self.water_l = c["water_l"]
        self.creatine_on = c["creatine"]
        self.flare_on = c["flare_protocol"]

    # explicit input setters (Reflex 0.9 doesn't auto-generate them)
    @rx.event
    def set_log_weight(self, v: str):
        self.log_weight = v

    @rx.event
    def set_log_reps(self, v: str):
        self.log_reps = v

    @rx.event
    def set_log_rpe(self, v: str):
        self.log_rpe = v

    @rx.event
    def set_log_sets(self, v: str):
        self.log_sets = v

    @rx.event
    def set_log_note(self, v: str):
        self.log_note = v

    @rx.event
    def set_bw_input(self, v: str):
        self.bw_input = v

    @rx.event
    def set_pin_url(self, v: str):
        self.pin_url = v

    @rx.event
    def set_custom_protein(self, v: str):
        self.custom_protein = v

    @rx.event
    def set_custom_kcal(self, v: str):
        self.custom_kcal = v

    @rx.event
    def set_bodyweight_input(self, v: str):
        self.bodyweight_input = v

    @rx.event
    def set_kcal_input(self, v: str):
        self.kcal_input = v

    # ===================== Today =====================
    @rx.event
    async def on_load_today(self):
        redir = await _require_auth(self)
        if redir is not None:
            return redir
        sm_db.init_db()
        self.the_date = today_iso()
        self._refresh_today()

    def _refresh_today(self):
        iso = self.the_date
        day = day_for_date(iso)
        self.cal_cards = []
        self.today_items = []
        self.recovery = []
        self.post_plan = False
        self.pre_plan_msg = ""
        if day is None:
            idx = day_index_of(iso)
            if idx < 0:
                days_until = -idx
                start = sm_data.START_DATE
                self.pre_plan_msg = (
                    f"Plan starts {_fmt_date(start)} — {days_until} "
                    f"{'day' if days_until == 1 else 'days'} out. Here's Day 1 so you can prep."
                )
                self._render_day(iso=iso_for_day_index(0))
                return
            self.post_plan = True
            self.header_line = "Plan complete"
            return
        self._load_checks(iso)
        self._render_day(iso)

    def _render_day(self, iso: str):
        day = day_for_date(iso)
        s = session_for(iso, self._eng())
        if day is None or s is None:
            return
        self.header_line = _fmt_date(iso)
        self.badge_week = f"Week {day['week']} · Q{day['quarter']}"
        self.badge_type = day["week_type"]
        self.is_calibration = day["is_calibration"]
        self.is_test_week = day["is_test_week"]
        self.is_rest = day["session_kind"] == "rest" or not s["items"]
        self.session_title = s["title"]
        logged = sm_db.list_sets(iso)
        self.today_items = [_item_row(it, logged) for it in s["items"]]
        self.recovery = s.get("recovery") or []
        self._refresh_calibration(iso, s, logged)

    def _refresh_calibration(self, iso: str, s: dict, logged: list[dict]):
        cards: list[CalRow] = []
        if s.get("is_calibration"):
            tms = sm_db.get_tms()
            for it in s["items"]:
                lift_id = it.get("lift_id")
                if not lift_id:
                    continue
                weights = [x["weight_lb"] for x in logged
                           if x["exercise_id"] == it["exercise_id"] and x["weight_lb"] is not None]
                if not weights:
                    continue
                top = max(weights)
                current = (tms.get(lift_id) or [None, None, None, None])[0]
                cards.append(CalRow(
                    exercise_id=it["exercise_id"], name=it.get("name") or it["exercise_id"],
                    lift_id=lift_id, quarter=quarter_of(s["week"]), top=top,
                    top_label=_fmt_weight(top), already_set=(current == top),
                ))
        self.cal_cards = cards

    @rx.event
    def open_log(self, exercise_id: str):
        item = next((i for i in self.today_items if i["exercise_id"] == exercise_id), None)
        if item is None:
            return
        # raw engine item for prefill
        s = session_for(self.the_date, self._eng()) or {"items": []}
        raw = next((i for i in s["items"] if i["exercise_id"] == exercise_id), {})
        existing = sm_db.list_sets(self.the_date, exercise_id)
        self.log_exercise_id = exercise_id
        self.log_exercise_name = item["name"]
        if existing:
            self.log_weight = "" if existing[0]["weight_lb"] is None else str(int(existing[0]["weight_lb"]))
            self.log_reps = "" if existing[0]["reps"] is None else str(existing[0]["reps"])
            self.log_rpe = "" if existing[0]["rpe"] is None else str(existing[0]["rpe"])
            self.log_sets = str(len(existing))
            self.log_note = existing[0].get("note") or ""
        else:
            self.log_weight = "" if raw.get("weight_lb") is None else str(int(raw["weight_lb"]))
            self.log_reps = _numeric_reps(raw.get("reps"))
            self.log_rpe = ""
            self.log_sets = str(raw["sets"]) if isinstance(raw.get("sets"), int) else "1"
            self.log_note = ""
        self.log_open = True

    @rx.event
    def save_log(self):
        try:
            n = max(1, int(self.log_sets or "1"))
        except ValueError:
            n = 1
        w = _parse_num(self.log_weight)
        reps = _parse_num(self.log_reps)
        rpe = _parse_num(self.log_rpe)
        rows = [{"set_num": i + 1, "weight_lb": w, "reps": int(reps) if reps is not None else None,
                 "rpe": rpe, "note": self.log_note or None} for i in range(n)]
        sm_db.set_exercise_sets(self.the_date, self.log_exercise_id, rows)
        self.log_open = False
        self._refresh_today()

    @rx.event
    def clear_log(self):
        sm_db.set_exercise_sets(self.the_date, self.log_exercise_id, [])
        self.log_open = False
        self._refresh_today()

    @rx.event
    def close_log(self):
        self.log_open = False

    @rx.event
    def save_calibration(self, lift_id: str, quarter: int, top: float):
        sm_db.set_tm(lift_id, int(quarter), int(top))
        self._refresh_today()
        return rx.toast.success(f"Saved {int(top)} lb as Q{quarter} TM.")

    # daily checks
    @rx.event
    def water_delta(self, delta: float):
        sm_db.set_checks(self.the_date, water_l=max(0.0, self.water_l + delta))
        self._load_checks(self.the_date)

    @rx.event
    def toggle_creatine(self, value: bool = False):
        sm_db.set_checks(self.the_date, creatine=bool(value))
        self._load_checks(self.the_date)

    @rx.event
    def toggle_flare(self, value: bool = False):
        sm_db.set_checks(self.the_date, flare_protocol=bool(value))
        self._load_checks(self.the_date)

    # ===================== Plan =====================
    @rx.event
    async def on_load_plan(self):
        redir = await _require_auth(self)
        if redir is not None:
            return redir
        sm_db.init_db()
        self.selected_date = ""
        self._build_weeks()

    def _build_weeks(self):
        cal = build_calendar()
        weeks: list[WeekRow] = []
        for w in range(1, 53):
            days = [d for d in cal if d["week"] == w]
            cells = [CalCell(
                date=d["date"], dom=d["date"][8:], dow_initial=d["dow"][0].upper(),
                kind=d["session_kind"],
                tone=("rest" if d["session_kind"] == "rest" else d["week_type"]),
            ) for d in days]
            tag = "" if days[0]["week_type"] == "build" else days[0]["week_type"].upper()
            weeks.append(WeekRow(week=w, quarter=days[0]["quarter"], tag=tag, cells=cells))
        self.weeks = weeks

    @rx.event
    def select_day(self, iso: str):
        self.selected_date = iso
        self._refresh_detail()

    @rx.event
    def back_to_calendar(self):
        self.selected_date = ""

    def _refresh_detail(self):
        iso = self.selected_date
        day = day_for_date(iso)
        s = session_for(iso, self._eng())
        if day is None or s is None:
            self.detail_items = []
            return
        ov = sm_db.get_override(iso) or {}
        self.detail_header = f"{_fmt_date(iso)} · Week {day['week']} · Q{day['quarter']}"
        self.detail_badge = day["week_type"]
        self.detail_skipped = bool(ov.get("skipped"))
        self.detail_skip_reason = ov.get("skip_reason") or ""
        logged = sm_db.list_sets(iso)
        self.detail_items = [_item_row(it, logged) for it in s["items"]]

    @rx.event
    def toggle_skip_day(self, value: bool = False):
        iso = self.selected_date
        ov = sm_db.get_override(iso) or {"skipped": False, "skip_reason": None, "exercises": {}}
        new_skipped = bool(value)
        if not new_skipped and not (ov.get("exercises") or {}):
            sm_db.set_override(iso, None)
        else:
            sm_db.set_override(iso, {"skipped": new_skipped, "skip_reason": ov.get("skip_reason"),
                                     "exercises": ov.get("exercises") or {}})
        self._refresh_detail()

    @rx.event
    def set_skip_reason(self, reason: str):
        iso = self.selected_date
        ov = sm_db.get_override(iso) or {"skipped": True, "exercises": {}}
        sm_db.set_override(iso, {"skipped": True, "skip_reason": reason,
                                 "exercises": ov.get("exercises") or {}})
        self.detail_skip_reason = reason

    # ===================== Meals =====================
    @rx.event
    async def on_load_meals(self):
        redir = await _require_auth(self)
        if redir is not None:
            return redir
        sm_db.init_db()
        self.the_date = today_iso()
        self._refresh_meals()

    def _refresh_meals(self):
        iso = self.the_date
        self._load_checks(iso)
        totals = sm_db.meal_totals(iso)
        self.protein_total = int(round(totals["protein_g"]))
        self.kcal_total = int(round(totals["kcal"]))
        s = sm_db.get_settings()
        self.protein_target = sm_nutrition.protein_target_g(s["bodyweight_lb"])
        self.kcal_set = s["kcal_target"] is not None
        self.kcal_target_label = ("target not set" if s["kcal_target"] is None
                                  else f"{int(s['kcal_target'])} kcal")
        tmpl = sm_nutrition.fixed_template_meals()
        self.template_rows = [_recipe_row(m) for m in tmpl]
        self.template_total_label = (
            f"{sum(m['protein_g'] for m in tmpl)} g · {sum(m['kcal'] for m in tmpl)} kcal"
        )
        dinner = sm_nutrition.dinner_for_dow(dow_of(iso))
        self.dinner_row = _recipe_row(dinner) if dinner else None
        self.library_rows = [_recipe_row(m) for m in sm_nutrition.meal_recipes()]
        self.meals_per_day = int(s.get("meals_per_day", 2) or 2)
        self.protein_per_meal = round(self.protein_target / self.meals_per_day / 5) * 5
        big = sm_nutrition.big_meals()
        self.big_dairy_rows = [_recipe_row(m) for m in big if m.get("tag") == "dairy"]
        self.big_flesh_rows = [_recipe_row(m) for m in big if m.get("tag") == "flesh"]
        self.big_omad_rows = [_recipe_row(m) for m in big if m.get("tag") == "omad"]
        self.logged_meals = [MealRow(id=m["id"], name=m["name"] or m["meal_id"],
                                     macros=f"{int(m['protein_g'])} g · {int(m['kcal'])} kcal")
                             for m in sm_db.list_meals(iso)]

    @rx.event
    def add_recipe_meal(self, meal_id: str, mult: str = "1"):
        try:
            m = float(mult)
        except ValueError:
            m = 1.0
        rec = next((r for r in sm_nutrition.meal_recipes() if r["id"] == meal_id), None)
        if rec is None:
            return
        sm_db.add_meal(self.the_date, rec["id"], rec["name"],
                       round(rec["protein_g"] * m), round(rec["kcal"] * m), m)
        self._refresh_meals()

    @rx.event
    def log_standard_day(self):
        for m in sm_nutrition.fixed_template_meals():
            sm_db.add_meal(self.the_date, m["id"], m["name"], m["protein_g"], m["kcal"], 1)
        self._refresh_meals()
        return rx.toast.success("Logged the standard day.")

    @rx.event
    def remove_logged_meal(self, meal_log_id: int):
        sm_db.remove_meal(int(meal_log_id))
        self._refresh_meals()

    @rx.event
    def set_custom_name(self, v: str):
        self.custom_name = v
        hits = sm_nutrition.find_excluded_ingredients(v) if v.strip() else []
        self.custom_warning = (
            f"Heads up — names an excluded ingredient ({', '.join(hits)})." if hits else ""
        )

    @rx.event
    def add_custom_meal(self):
        if not self.custom_name.strip():
            return
        sm_db.add_meal(self.the_date, "custom", self.custom_name.strip(),
                       _parse_num(self.custom_protein) or 0, _parse_num(self.custom_kcal) or 0, 1)
        self.custom_name = ""
        self.custom_protein = ""
        self.custom_kcal = ""
        self.custom_warning = ""
        self._refresh_meals()

    @rx.event
    def toggle_library(self):
        self.library_open = not self.library_open

    @rx.event
    def set_meals_per_day(self, n: int):
        sm_db.set_setting("meals_per_day", int(n))
        self._refresh_meals()

    # ===================== Exercises =====================
    @rx.event
    async def on_load_exercises(self):
        redir = await _require_auth(self)
        if redir is not None:
            return redir
        sm_db.init_db()
        self._refresh_exercises()

    def _refresh_exercises(self):
        pinned = sm_db.get_settings()["pinned_demos"]
        rows: list[ExerciseRow] = []
        q = self.ex_query.lower()
        for ex in sm_data.all_exercises():
            if q and q not in ex["name"].lower() and q not in ex.get("type", "").lower():
                continue
            pin = pinned.get(ex["id"])
            rows.append(ExerciseRow(
                id=ex["id"], name=ex["name"], type=ex.get("type", ""),
                safety=ex.get("safety") or "", cues_text=" · ".join(ex.get("cues") or []),
                equipment_text=", ".join(ex.get("equipment") or []),
                note=ex.get("note") or "", substitution=ex.get("substitution") or "",
                demo_url=(pin or sm_data.demo_search_url(ex["demo_search"])),
                pinned=bool(pin), pinned_url=pin or "",
            ))
        self.exercise_rows = rows

    @rx.event
    def set_ex_query(self, v: str):
        self.ex_query = v
        self._refresh_exercises()

    @rx.event
    def open_pin(self, exercise_id: str):
        self.pin_open_id = exercise_id
        self.pin_url = sm_db.get_settings()["pinned_demos"].get(exercise_id, "")

    @rx.event
    def save_pin(self):
        sm_db.set_pinned_demo(self.pin_open_id, self.pin_url or None)
        self.pin_open_id = ""
        self.pin_url = ""
        self._refresh_exercises()

    @rx.event
    def unpin(self, exercise_id: str):
        sm_db.set_pinned_demo(exercise_id, None)
        self.pin_open_id = ""
        self._refresh_exercises()

    # ===================== Progress =====================
    @rx.event
    async def on_load_progress(self):
        redir = await _require_auth(self)
        if redir is not None:
            return redir
        sm_db.init_db()
        self.logged_ex_options = sm_db.logged_exercise_ids()
        if self.logged_ex_options and not self.progress_ex:
            self.progress_ex = self.logged_ex_options[0]
        self._refresh_progress()

    def _refresh_progress(self):
        self.bw_series = [Point(x=b["date"][5:], y=b["lb"]) for b in sm_db.list_bodyweight()]
        if self.progress_ex:
            self.top_series = [Point(x=t["date"][5:], y=t["weight_lb"])
                               for t in sm_db.top_sets(self.progress_ex)]
        else:
            self.top_series = []
        # weekly protein average
        by_week: dict[int, list[float]] = {}
        # iterate logged meal dates by scanning bodyweight? Simpler: query meal_log dates.
        for d in _meal_dates():
            day = day_for_date(d)
            if not day:
                continue
            by_week.setdefault(day["week"], []).append(sm_db.meal_totals(d)["protein_g"])
        self.protein_series = [Point(x=f"W{w}", y=round(sum(v) / len(v)))
                               for w, v in sorted(by_week.items())]
        self.tm_rows = _tm_rows(sm_db.get_tms())

    @rx.event
    def set_progress_ex(self, v: str):
        self.progress_ex = v
        self._refresh_progress()

    @rx.event
    def log_bodyweight(self):
        lb = _parse_num(self.bw_input)
        if lb is None:
            return
        sm_db.set_bodyweight(today_iso(), lb)
        self.bw_input = ""
        self._refresh_progress()

    # ===================== Settings =====================
    @rx.event
    async def on_load_settings(self):
        redir = await _require_auth(self)
        if redir is not None:
            return redir
        sm_db.init_db()
        s = sm_db.get_settings()
        self.bodyweight_input = str(int(s["bodyweight_lb"]))
        self.kcal_input = "" if s["kcal_target"] is None else str(int(s["kcal_target"]))
        self.equip_sandbag = s["equipment"]["sandbag"]
        self.equip_axle = s["equipment"]["axle"]
        self.settings_tm_rows = _tm_rows(sm_db.get_tms())
        self.confirm_reset = False
        self.settings_msg = ""

    @rx.event
    def commit_bodyweight(self):
        v = _parse_num(self.bodyweight_input)
        if v is not None:
            sm_db.set_setting("bodyweight_lb", v)

    @rx.event
    def commit_kcal(self):
        v = _parse_num(self.kcal_input)
        sm_db.set_setting("kcal_target", v)

    @rx.event
    def clear_kcal(self):
        sm_db.set_setting("kcal_target", None)
        self.kcal_input = ""

    @rx.event
    def toggle_sandbag(self, value: bool = False):
        self.equip_sandbag = bool(value)
        sm_db.set_equipment(self.equip_sandbag, self.equip_axle)

    @rx.event
    def toggle_axle(self, value: bool = False):
        self.equip_axle = bool(value)
        sm_db.set_equipment(self.equip_sandbag, self.equip_axle)

    @rx.event
    def set_tm_value(self, lift_id: str, quarter: int, value: str):
        sm_db.set_tm(lift_id, int(quarter), _parse_num(value))
        self.settings_tm_rows = _tm_rows(sm_db.get_tms())

    @rx.event
    def ask_reset(self):
        self.confirm_reset = True

    @rx.event
    def cancel_reset(self):
        self.confirm_reset = False

    @rx.event
    def do_reset(self):
        sm_db.config.STRONGMAN_DB_PATH.unlink(missing_ok=True)
        sm_db.init_db()
        self.confirm_reset = False
        self.settings_msg = "All strongman data reset."
        return StrongmanState.on_load_settings


def _parse_num(s: str):
    if s is None:
        return None
    t = str(s).strip()
    if t == "":
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    if v != v or v in (float("inf"), float("-inf")):
        return None
    return int(v) if float(v).is_integer() else v


def _recipe_row(rec: dict) -> RecipeRow:
    items_text = "; ".join(
        f"{it['food']}" + (f" ({it['amount']})" if it.get("amount") else "")
        for it in rec.get("items", [])
    )
    return RecipeRow(
        id=rec["id"], name=rec["name"], group=rec.get("group", ""),
        macros=f"{int(rec['protein_g'])} g · {int(rec['kcal'])} kcal",
        items_text=items_text, prep=rec.get("prep") or "", note=rec.get("note") or "",
        tag=rec.get("tag") or "",
    )


def _tm_rows(tms: dict) -> list[TmRow]:
    rows: list[TmRow] = []
    for lift in sm_data.all_lifts():
        slots = tms.get(lift["id"]) or [None, None, None, None]
        vals = [resolve_tm(lift["id"], q, tms) for q in (1, 2, 3, 4)]
        rows.append(TmRow(
            lift_id=lift["id"], name=lift["name"],
            cap=(f"cap {lift['cap']}" if lift.get("cap") else ""),
            q1=str(vals[0]), q2=str(vals[1]), q3=str(vals[2]), q4=str(vals[3]),
            q1_set=slots[0] is not None, q2_set=slots[1] is not None,
            q3_set=slots[2] is not None, q4_set=slots[3] is not None,
        ))
    return rows


def _meal_dates() -> list[str]:
    with sm_db._cursor() as conn:
        rows = conn.execute("SELECT DISTINCT the_date FROM meal_log").fetchall()
        return [r["the_date"] for r in rows]
