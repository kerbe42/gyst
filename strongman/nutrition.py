"""Nutrition math + dietary-compliance scanning + meal recipes.

A faithful port of the standalone app's nutrition.ts. Macro numbers come only
from data/meals.json; the protein formula and exclusion lists from
plan_config.json. Nothing is invented.
"""

from __future__ import annotations

import math
import re
from typing import Optional

from . import data

MEALS = data.MEALS


def protein_target_g(bodyweight_lb: float) -> int:
    """protein_g/day target = round(bodyweight_lb * 0.8 / 5) * 5 (ties round up)."""
    return int(math.floor((bodyweight_lb * 0.8) / 5 + 0.5)) * 5


def fixed_template_totals() -> dict:
    protein_g = 0
    kcal = 0
    for m in MEALS["fixed_template"]:
        protein_g += m["protein_g"]
        kcal += m["kcal"]
    return {"protein_g": protein_g, "kcal": kcal}


def dinner_rotation_weekly_average() -> dict:
    ft = fixed_template_totals()
    by_dow: dict[str, dict] = {}
    for d in MEALS["dinner_rotation"]:
        for day in d["default_days"]:
            by_dow[day] = d
    p_sum = 0.0
    k_sum = 0.0
    for dow in data.DOW_ORDER:
        dinner = by_dow.get(dow)
        if dinner is None:
            raise ValueError(f"Dinner rotation has no plate for {dow}")
        p_sum += ft["protein_g"] + dinner["protein_g"]
        k_sum += ft["kcal"] + dinner["kcal"]
    return {"protein_g": p_sum / 7, "kcal": k_sum / 7}


# ---- dietary compliance ----------------------------------------------------
def _build_banned_tokens() -> list[str]:
    rules = data.DIETARY_RULES
    tokens: set[str] = set()
    for entry in [*rules["excluded_user"], *rules["excluded_gout"]]:
        for piece in re.split(r"[:,/]", entry.lower()):
            token = re.sub(r"^all\s+", "", piece.strip())
            if token:
                tokens.add(token)
    return list(tokens)


_BANNED_TOKENS = _build_banned_tokens()


def find_excluded_ingredients(text: str) -> list[str]:
    """Which excluded ingredients (if any) a piece of text names. Used for the
    meals scan and the custom-meal soft warning."""
    hay = text.lower()
    return [token for token in _BANNED_TOKENS if token in hay]


def scan_meals_for_violations() -> list[dict]:
    """Walk every *ingredient* in the library (not notes/prep) against the
    excluded lists. Must return [] for the shipped data."""
    violations: list[dict] = []

    def check(where: str, food: str):
        matched = find_excluded_ingredients(food)
        if matched:
            violations.append({"where": where, "food": food, "matched": matched})

    for m in MEALS["fixed_template"]:
        for it in m["items"]:
            check(m["name"], it["food"])
    for d in MEALS["dinner_rotation"]:
        check(d["name"], d["protein_source"]["food"])
    for it in MEALS["dinner_fixed_sides"]["items"]:
        check("Dinner sides", it["food"])
    for m in MEALS["super_meals_extra"]:
        for it in m["items"]:
            check(m["name"], it["food"])
    for m in MEALS.get("big_meals", []):
        for it in m["items"]:
            check(m["name"], it["food"])
    return violations


# ---- meal recipes (what it is / what to make) ------------------------------
_DINNER_SIDES_NOTE = "Every dinner plate includes the fixed sides listed above."
BIG_MEALS_GROUP = "Big meals (1–2 a day)"


def meal_recipes() -> list[dict]:
    out: list[dict] = []
    for m in MEALS["fixed_template"]:
        out.append(
            {
                "id": m["id"],
                "name": m["name"],
                "group": "Fixed template",
                "protein_g": m["protein_g"],
                "kcal": m["kcal"],
                "items": m["items"],
                "prep": m.get("prep"),
                "note": m.get("note"),
            }
        )
    for d in MEALS["dinner_rotation"]:
        out.append(
            {
                "id": d["id"],
                "name": d["name"],
                "group": "Dinner plates",
                "protein_g": d["protein_g"],
                "kcal": d["kcal"],
                "items": [d["protein_source"], *MEALS["dinner_fixed_sides"]["items"]],
                "note": _DINNER_SIDES_NOTE,
            }
        )
    for m in MEALS["super_meals_extra"]:
        out.append(
            {
                "id": m["id"],
                "name": m["name"],
                "group": "Extra super meals",
                "protein_g": m["protein_g"],
                "kcal": m["kcal"],
                "items": m["items"],
                "prep": m.get("prep"),
                "note": m.get("note"),
            }
        )
    for m in MEALS.get("big_meals", []):
        out.append(
            {
                "id": m["id"],
                "name": m["name"],
                "group": BIG_MEALS_GROUP,
                "protein_g": m["protein_g"],
                "kcal": m["kcal"],
                "items": m["items"],
                "tag": m.get("tag"),
                "flesh_oz": m.get("flesh_oz"),
            }
        )
    return out


def fixed_template_meals() -> list[dict]:
    return [m for m in meal_recipes() if m["group"] == "Fixed template"]


def big_meals() -> list[dict]:
    """Big composite meals for a 1-2 meal/day pattern (tagged dairy/flesh/omad)."""
    return [m for m in meal_recipes() if m["group"] == BIG_MEALS_GROUP]


def dinner_for_dow(dow: str) -> Optional[dict]:
    plate = next((d for d in MEALS["dinner_rotation"] if dow in d["default_days"]), None)
    if plate is None:
        return None
    return next((m for m in meal_recipes() if m["id"] == plate["id"]), None)
