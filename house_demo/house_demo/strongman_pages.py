"""Reflex pages for the Strongman module: Today, Plan, Meals, Exercises,
Progress, Settings. They render display-ready data from StrongmanState; all
numbers originate in the pure engine.
"""

from __future__ import annotations

import reflex as rx

from house_demo.layout import layout
from house_demo.strongman_state import StrongmanState as S

_TONE = lambda v: rx.match(v, ("deload", "teal"), ("test", "amber"), "blue")  # noqa: E731


def _type_badge(type_var) -> rx.Component:
    return rx.badge(type_var, color_scheme=_TONE(type_var), variant="soft")


def _subnav() -> rx.Component:
    links = [
        ("Today", "/strongman", "dumbbell"),
        ("Plan", "/strongman/plan", "calendar-days"),
        ("Meals", "/strongman/meals", "utensils"),
        ("Lifts", "/strongman/exercises", "book-open"),
        ("Progress", "/strongman/progress", "trending-up"),
        ("Settings", "/strongman/settings", "settings"),
    ]
    return rx.hstack(
        *[
            rx.link(rx.hstack(rx.icon(icon, size=14), rx.text(label, size="2"), spacing="1", align="center"),
                    href=href, underline="none")
            for label, href, icon in links
        ],
        spacing="4", wrap="wrap", padding_y="2", style={"opacity": 0.85},
    )


# ---- shared exercise card --------------------------------------------------
def _exercise_card(item) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.cond(item["is_logged"], rx.icon("check", size=16, color="var(--green-9)"), rx.fragment()),
                rx.heading(item["name"], size="3"),
                rx.spacer(),
                rx.button("Log", size="1", on_click=S.open_log(item["exercise_id"])),
                width="100%", align="center", spacing="2",
            ),
            rx.text(item["prescription"], weight="medium"),
            rx.hstack(
                rx.cond(item["rpe"], rx.badge(item["rpe"], variant="surface", color_scheme="gray"), rx.fragment()),
                rx.cond(item["rest"], rx.badge(item["rest"], variant="surface", color_scheme="gray"), rx.fragment()),
                spacing="2", wrap="wrap",
            ),
            rx.cond(item["substitution_note"],
                    rx.callout(item["substitution_note"], icon="repeat", size="1", color_scheme="gray"),
                    rx.fragment()),
            rx.cond(item["notes"], rx.text(item["notes"], size="2", color_scheme="gray"), rx.fragment()),
            rx.cond(item["safety"],
                    rx.callout(item["safety"], icon="triangle-alert", size="1", color_scheme="amber"),
                    rx.fragment()),
            rx.cond(item["cues_text"], rx.text(item["cues_text"], size="1", color_scheme="gray"), rx.fragment()),
            rx.cond(item["logged_summary"],
                    rx.text("Logged: " + item["logged_summary"], size="1", color_scheme="green"),
                    rx.fragment()),
            rx.cond(item["demo_url"],
                    rx.link("Watch demo ↗", href=item["demo_url"], is_external=True, size="1"),
                    rx.fragment()),
            spacing="2", align="start", width="100%",
        ),
        width="100%",
    )


def _log_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(S.log_exercise_name),
            rx.vstack(
                rx.hstack(
                    rx.input(placeholder="weight", value=S.log_weight, on_change=S.set_log_weight, type="number"),
                    rx.input(placeholder="reps", value=S.log_reps, on_change=S.set_log_reps, type="number"),
                    rx.input(placeholder="RPE", value=S.log_rpe, on_change=S.set_log_rpe, type="number"),
                    spacing="2", width="100%",
                ),
                rx.hstack(
                    rx.text("Sets:", size="2"),
                    rx.input(value=S.log_sets, on_change=S.set_log_sets, type="number", width="5rem"),
                    spacing="2", align="center",
                ),
                rx.input(placeholder="note (optional)", value=S.log_note, on_change=S.set_log_note),
                rx.hstack(
                    rx.button("Save log", on_click=S.save_log),
                    rx.button("Clear", on_click=S.clear_log, variant="soft", color_scheme="gray"),
                    rx.button("Cancel", on_click=S.close_log, variant="soft", color_scheme="gray"),
                    spacing="2",
                ),
                spacing="3", width="100%",
            ),
        ),
        open=S.log_open,
    )


# ===================== Today =====================
def strongman_today_page() -> rx.Component:
    body = rx.vstack(
        _subnav(),
        rx.cond(
            S.post_plan,
            rx.card(rx.vstack(rx.heading("Plan complete 🎉", size="5"),
                              rx.text("52 weeks done. Review Progress, then set the next block.",
                                      color_scheme="gray"), align="center", spacing="2"), width="100%"),
            rx.vstack(
                rx.hstack(rx.heading(S.badge_week, size="6"), _type_badge(S.badge_type),
                          rx.cond(S.is_calibration, rx.badge("Calibration", color_scheme="amber"), rx.fragment()),
                          rx.cond(S.is_test_week, rx.badge("Test week", color_scheme="amber"), rx.fragment()),
                          spacing="2", align="center", wrap="wrap"),
                rx.text(S.header_line, color_scheme="gray", size="2"),
                rx.cond(S.pre_plan_msg, rx.callout(S.pre_plan_msg, icon="info", color_scheme="blue"), rx.fragment()),
                _checks_card(),
                rx.cond(
                    S.is_rest,
                    rx.card(rx.vstack(rx.heading("Recovery", size="3"),
                                      rx.foreach(S.recovery, lambda t: rx.text("· " + t, size="2")),
                                      align="start", spacing="1"), width="100%"),
                    rx.vstack(rx.foreach(S.today_items, _exercise_card), spacing="3", width="100%"),
                ),
                rx.cond(
                    S.cal_cards,
                    rx.vstack(rx.foreach(S.cal_cards, _cal_card), spacing="2", width="100%"),
                    rx.fragment(),
                ),
                spacing="4", align="stretch", width="100%",
            ),
        ),
        _log_dialog(),
        spacing="4", align="stretch", width="100%",
    )
    return layout(body, title="Strongman — Today")


def _checks_card() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.text("Water ", S.water_l.to(str), " L", weight="medium"),
                rx.spacer(),
                rx.button("−", on_click=S.water_delta(-0.5), variant="soft", size="1"),
                rx.button("+", on_click=S.water_delta(0.5), variant="soft", size="1"),
                width="100%", align="center",
            ),
            rx.hstack(rx.text("Creatine (10 g)", weight="medium"), rx.spacer(),
                      rx.switch(checked=S.creatine_on, on_change=S.toggle_creatine),
                      width="100%", align="center"),
            rx.hstack(rx.text("Flare protocol", weight="medium", color_scheme="amber"), rx.spacer(),
                      rx.switch(checked=S.flare_on, on_change=S.toggle_flare),
                      width="100%", align="center"),
            spacing="2", width="100%",
        ),
        width="100%",
    )


def _cal_card(c) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.text("Calibration: top " + c["name"] + " set was " + c["top_label"], size="2"),
            rx.button(
                rx.cond(c["already_set"], "Saved ✓", "Save " + c["top_label"] + " as Q" + c["quarter"].to(str) + " TM"),
                on_click=S.save_calibration(c["lift_id"], c["quarter"], c["top"]),
                disabled=c["already_set"], size="2",
            ),
            spacing="2", align="start",
        ),
        width="100%", style={"borderColor": "var(--amber-6)"},
    )


# ===================== Plan =====================
def strongman_plan_page() -> rx.Component:
    body = rx.vstack(
        _subnav(),
        rx.cond(
            S.selected_date,
            _plan_detail(),
            rx.vstack(
                rx.heading("Plan", size="6"),
                rx.foreach(S.weeks, _week_row),
                spacing="2", align="stretch", width="100%",
            ),
        ),
        spacing="4", align="stretch", width="100%",
    )
    return layout(body, title="Strongman — Plan")


def _week_row(w) -> rx.Component:
    return rx.hstack(
        rx.text("W" + w["week"].to(str), size="1", color_scheme="gray", width="2.5rem"),
        rx.grid(rx.foreach(w["cells"], _cal_cell), columns="7", spacing="1", flex="1"),
        rx.text(w["tag"], size="1", color_scheme="gray", width="3.5rem"),
        align="center", spacing="2", width="100%",
    )


def _cal_cell(c) -> rx.Component:
    return rx.button(
        rx.vstack(rx.text(c["dow_initial"], size="1", weight="bold"), rx.text(c["dom"], size="1"),
                  spacing="0", align="center"),
        on_click=S.select_day(c["date"]),
        variant=rx.cond(c["tone"] == "rest", "surface", "soft"),
        color_scheme=rx.match(c["tone"], ("deload", "teal"), ("test", "amber"), ("rest", "gray"), "blue"),
        size="1", height="3rem", padding="0",
    )


def _plan_detail() -> rx.Component:
    return rx.vstack(
        rx.button("‹ Calendar", on_click=S.back_to_calendar, variant="ghost", size="2"),
        rx.hstack(rx.heading(S.detail_header, size="4"), _type_badge(S.detail_badge), spacing="2",
                  align="center", wrap="wrap"),
        rx.card(
            rx.hstack(rx.text("Skip this day", weight="medium"), rx.spacer(),
                      rx.switch(checked=S.detail_skipped, on_change=S.toggle_skip_day),
                      width="100%", align="center"),
            width="100%",
        ),
        rx.cond(
            S.detail_skipped,
            rx.input(placeholder="Reason (optional)", value=S.detail_skip_reason, on_change=S.set_skip_reason),
            rx.vstack(rx.foreach(S.detail_items, _exercise_card), spacing="3", width="100%"),
        ),
        spacing="3", align="stretch", width="100%",
    )


# ===================== Meals =====================
def strongman_meals_page() -> rx.Component:
    body = rx.vstack(
        _subnav(),
        rx.heading("Meals", size="6"),
        rx.card(
            rx.vstack(
                rx.text("Protein  " + S.protein_total.to(str) + " / " + S.protein_target.to(str) + " g",
                        weight="medium"),
                rx.progress(value=S.protein_total, max=S.protein_target),
                rx.text("Calories  " + S.kcal_total.to(str) + " kcal · " + S.kcal_target_label,
                        weight="medium"),
                spacing="2", width="100%",
            ),
            width="100%",
        ),
        _checks_card(),
        rx.cond(
            S.flare_on,
            rx.callout("Flare protocol active — day flagged. Drop dinner flesh; whey + Greek yogurt instead.",
                       icon="triangle-alert", color_scheme="amber"),
            rx.fragment(),
        ),
        rx.cond(
            S.logged_meals,
            rx.vstack(rx.heading("Today's meals", size="3"),
                      rx.foreach(S.logged_meals, _logged_meal_row), spacing="1", width="100%", align="stretch"),
            rx.fragment(),
        ),
        _big_meals_block(),
        rx.heading("Or the 6-small-meal standard day", size="3"),
        rx.text("Your standard day, plus tonight's dinner. " + S.template_total_label + " before dinner.",
                size="2", color_scheme="gray"),
        rx.button("Log the standard day", on_click=S.log_standard_day, variant="soft", width="100%"),
        rx.foreach(S.template_rows, _recipe_card),
        rx.cond(S.dinner_row, rx.vstack(rx.text("Tonight's dinner", size="1", weight="bold", color_scheme="gray"),
                                        _recipe_card(S.dinner_row), width="100%", align="stretch", spacing="1"),
                rx.fragment()),
        rx.button(rx.cond(S.library_open, "Hide all meals", "Browse all meals (recipes)"),
                  on_click=S.toggle_library, variant="ghost", width="100%"),
        rx.cond(S.library_open, rx.vstack(rx.foreach(S.library_rows, _recipe_card), spacing="2", width="100%"),
                rx.fragment()),
        _custom_meal_card(),
        spacing="3", align="stretch", width="100%",
    )
    return layout(body, title="Strongman — Meals")


def _logged_meal_row(m) -> rx.Component:
    return rx.card(
        rx.hstack(rx.vstack(rx.text(m["name"], size="2"), rx.text(m["macros"], size="1", color_scheme="gray"),
                            spacing="0", align="start"),
                  rx.spacer(),
                  rx.icon_button(rx.icon("x", size=14), on_click=S.remove_logged_meal(m["id"]),
                                 variant="soft", color_scheme="gray", size="1"),
                  width="100%", align="center"),
        size="1", width="100%",
    )


def _big_meals_block() -> rx.Component:
    def day_btn(n: int) -> rx.Component:
        return rx.button(
            str(n), size="2",
            variant=rx.cond(S.meals_per_day == n, "solid", "soft"),
            color_scheme=rx.cond(S.meals_per_day == n, "indigo", "gray"),
            on_click=S.set_meals_per_day(n),
        )

    def group(label: str, rows) -> rx.Component:
        return rx.cond(
            rows,
            rx.vstack(
                rx.text(label, size="1", weight="bold", color_scheme="gray"),
                rx.foreach(rows, _recipe_card),
                spacing="1", width="100%", align="stretch",
            ),
            rx.fragment(),
        )

    return rx.vstack(
        rx.heading("Big meals — 1 or 2 a day", size="3"),
        rx.card(
            rx.vstack(
                rx.hstack(rx.text("Meals today", weight="medium"), rx.spacer(),
                          day_btn(1), day_btn(2), width="100%", align="center"),
                rx.text("Target " + S.protein_target.to(str) + " g protein · "
                        + S.meals_per_day.to(str) + " meal(s) → ~" + S.protein_per_meal.to(str)
                        + " g each.", size="2"),
                rx.text("Pair one dairy + one flesh meal for a 2-meal day — keeps you under the "
                        "8 oz/day flesh cap. Tap a meal for the recipe.", size="1", color_scheme="gray"),
                spacing="2", width="100%",
            ),
            width="100%",
        ),
        group("Dairy-forward (no flesh)", S.big_dairy_rows),
        group("With flesh (uses your 8 oz/day)", S.big_flesh_rows),
        group("One meal (OMAD — a full day in one)", S.big_omad_rows),
        spacing="2", width="100%", align="stretch",
    )


def _recipe_card(r) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.vstack(rx.text(r["name"], weight="medium", size="2"),
                          rx.text(r["macros"], size="1", color_scheme="gray"), spacing="0", align="start"),
                rx.spacer(),
                rx.button("Add", size="1", on_click=S.add_recipe_meal(r["id"], "1")),
                width="100%", align="center",
            ),
            rx.text(r["items_text"], size="1", color_scheme="gray"),
            rx.cond(r["prep"], rx.text("Prep: " + r["prep"], size="1", color_scheme="gray"), rx.fragment()),
            spacing="1", align="start", width="100%",
        ),
        size="1", width="100%",
    )


def _custom_meal_card() -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.heading("Custom meal", size="3"),
            rx.input(placeholder="Name (e.g. Tuna sandwich)", value=S.custom_name, on_change=S.set_custom_name),
            rx.hstack(
                rx.input(placeholder="protein g", value=S.custom_protein, on_change=S.set_custom_protein, type="number"),
                rx.input(placeholder="kcal", value=S.custom_kcal, on_change=S.set_custom_kcal, type="number"),
                spacing="2", width="100%",
            ),
            rx.cond(S.custom_warning, rx.callout(S.custom_warning, icon="triangle-alert", color_scheme="amber", size="1"),
                    rx.fragment()),
            rx.button("Add custom meal", on_click=S.add_custom_meal, width="100%"),
            spacing="2", width="100%",
        ),
        width="100%",
    )


# ===================== Exercises =====================
def strongman_exercises_page() -> rx.Component:
    body = rx.vstack(
        _subnav(),
        rx.heading("Exercise library", size="6"),
        rx.input(placeholder="Search lifts…", value=S.ex_query, on_change=S.set_ex_query),
        rx.foreach(S.exercise_rows, _exercise_lib_card),
        spacing="3", align="stretch", width="100%",
    )
    return layout(body, title="Strongman — Lifts")


def _exercise_lib_card(ex) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(rx.heading(ex["name"], size="3"), rx.spacer(),
                      rx.badge(ex["type"], color_scheme="gray", variant="surface"), width="100%", align="center"),
            rx.cond(ex["safety"], rx.callout(ex["safety"], icon="triangle-alert", color_scheme="amber", size="1"),
                    rx.fragment()),
            rx.cond(ex["cues_text"], rx.text(ex["cues_text"], size="2", color_scheme="gray"), rx.fragment()),
            rx.cond(ex["note"], rx.text(ex["note"], size="1", color_scheme="gray"), rx.fragment()),
            rx.cond(ex["substitution"], rx.text("↻ " + ex["substitution"], size="1", color_scheme="gray"), rx.fragment()),
            rx.cond(ex["equipment_text"], rx.text(ex["equipment_text"], size="1", color_scheme="gray"), rx.fragment()),
            rx.hstack(
                rx.link("▶ Watch demo", href=ex["demo_url"], is_external=True, size="2"),
                rx.button(rx.cond(ex["pinned"], "Edit pin", "Pin a video"), variant="ghost", size="1",
                          on_click=S.open_pin(ex["id"])),
                spacing="3", align="center",
            ),
            rx.cond(
                S.pin_open_id == ex["id"],
                rx.hstack(
                    rx.input(placeholder="https://youtu.be/…", value=S.pin_url, on_change=S.set_pin_url, flex="1"),
                    rx.button("Save", size="1", on_click=S.save_pin),
                    rx.button("Unpin", size="1", variant="soft", color_scheme="gray", on_click=S.unpin(ex["id"])),
                    spacing="2", width="100%",
                ),
                rx.fragment(),
            ),
            spacing="2", align="start", width="100%",
        ),
        width="100%",
    )


# ===================== Progress =====================
def strongman_progress_page() -> rx.Component:
    body = rx.vstack(
        _subnav(),
        rx.heading("Progress", size="6"),
        rx.card(
            rx.vstack(
                rx.heading("Bodyweight", size="3"),
                _line_chart(S.bw_series),
                rx.hstack(rx.input(placeholder="Today's bodyweight (lb)", value=S.bw_input,
                                   on_change=S.set_bw_input, type="number", flex="1"),
                          rx.button("Log", on_click=S.log_bodyweight), spacing="2", width="100%"),
                spacing="3", width="100%",
            ),
            width="100%",
        ),
        rx.card(
            rx.vstack(
                rx.heading("Top set over time", size="3"),
                rx.cond(
                    S.logged_ex_options,
                    rx.vstack(
                        rx.select(S.logged_ex_options, value=S.progress_ex, on_change=S.set_progress_ex),
                        _line_chart(S.top_series), spacing="2", width="100%",
                    ),
                    rx.text("Log training sets and they'll chart here.", size="2", color_scheme="gray"),
                ),
                spacing="2", width="100%",
            ),
            width="100%",
        ),
        rx.card(
            rx.vstack(
                rx.heading("Projected climb (52 weeks)", size="3"),
                rx.select.root(
                    rx.select.trigger(width="100%"),
                    rx.select.content(
                        rx.foreach(
                            S.proj_lift_options,
                            lambda o: rx.select.item(o["name"], value=o["id"]),
                        ),
                    ),
                    value=S.proj_lift,
                    on_change=S.set_proj_lift,
                ),
                _line_chart(S.proj_series),
                rx.hstack(rx.foreach(S.proj_quarter_rows, _proj_quarter_cell), spacing="1", width="100%"),
                rx.text(
                    "Top working-set weight across the plan. Saw-teeth are deload weeks; each quarter "
                    "peaks higher, and the line redraws upward as you log heavier test weeks.",
                    size="1", color_scheme="gray",
                ),
                rx.cond(
                    S.current_week > 0,
                    rx.text("You're in week ", S.current_week.to(str), " of 52.",
                            size="1", color_scheme="gray"),
                    rx.fragment(),
                ),
                spacing="2", width="100%",
            ),
            width="100%",
        ),
        rx.card(rx.vstack(rx.heading("Weekly protein average", size="3"), _line_chart(S.protein_series),
                          spacing="2", width="100%"), width="100%"),
        rx.card(rx.vstack(rx.heading("Training-max progression", size="3"),
                          rx.foreach(S.tm_rows, _tm_progress_row), spacing="1", width="100%"), width="100%"),
        spacing="3", align="stretch", width="100%",
    )
    return layout(body, title="Strongman — Progress")


def _line_chart(series) -> rx.Component:
    return rx.cond(
        series,
        rx.recharts.line_chart(
            rx.recharts.line(data_key="y", stroke="#3b82f6", type_="monotone"),
            rx.recharts.x_axis(data_key="x"),
            rx.recharts.y_axis(domain=["auto", "auto"]),
            data=series, height=160, width="100%",
        ),
        rx.text("No data yet.", size="2", color_scheme="gray"),
    )


def _proj_quarter_cell(row) -> rx.Component:
    return rx.vstack(
        rx.text(row["label"], size="1", color_scheme="gray"),
        rx.text(row["top"].to(str), weight="bold", size="3"),
        rx.text("top set", size="1", color_scheme="gray"),
        spacing="0", align="center", flex="1",
        padding_y="6px", background_color=rx.color("gray", 3), border_radius="6px",
    )


def _tm_progress_row(row) -> rx.Component:
    return rx.hstack(
        rx.text(row["name"], size="2", flex="1"),
        rx.badge(row["q1"], color_scheme=rx.cond(row["q1_set"], "blue", "gray"), variant="soft"),
        rx.badge(row["q2"], color_scheme=rx.cond(row["q2_set"], "blue", "gray"), variant="soft"),
        rx.badge(row["q3"], color_scheme=rx.cond(row["q3_set"], "blue", "gray"), variant="soft"),
        rx.badge(row["q4"], color_scheme=rx.cond(row["q4_set"], "blue", "gray"), variant="soft"),
        spacing="1", align="center", width="100%",
    )


# ===================== Settings =====================
def strongman_settings_page() -> rx.Component:
    body = rx.vstack(
        _subnav(),
        rx.heading("Strongman settings", size="6"),
        rx.card(
            rx.vstack(
                rx.heading("Athlete", size="3"),
                rx.text("Bodyweight (lb) — drives protein target", size="2", color_scheme="gray"),
                rx.input(value=S.bodyweight_input, on_change=S.set_bodyweight_input, on_blur=S.commit_bodyweight,
                         type="number", width="10rem"),
                rx.text("Daily kcal target (stays unset until you measure maintenance)", size="2", color_scheme="gray"),
                rx.hstack(
                    rx.input(placeholder="unset", value=S.kcal_input, on_change=S.set_kcal_input,
                             on_blur=S.commit_kcal, type="number", width="10rem"),
                    rx.button("Clear", on_click=S.clear_kcal, variant="soft", color_scheme="gray", size="2"),
                    spacing="2", align="center",
                ),
                spacing="2", width="100%", align="start",
            ),
            width="100%",
        ),
        rx.card(
            rx.vstack(
                rx.heading("Equipment owned (gates substitutions)", size="3"),
                rx.hstack(rx.text("Sandbag", weight="medium"), rx.spacer(),
                          rx.switch(checked=S.equip_sandbag, on_change=S.toggle_sandbag),
                          width="100%", align="center"),
                rx.hstack(rx.text("Axle", weight="medium"), rx.spacer(),
                          rx.switch(checked=S.equip_axle, on_change=S.toggle_axle),
                          width="100%", align="center"),
                spacing="2", width="100%",
            ),
            width="100%",
        ),
        rx.card(
            rx.vstack(
                rx.heading("Training maxes", size="3"),
                rx.text("Placeholders are estimates; confirm Q1 during calibration. Blue = confirmed.",
                        size="1", color_scheme="gray"),
                rx.foreach(S.settings_tm_rows, _tm_edit_row),
                spacing="2", width="100%",
            ),
            width="100%",
        ),
        rx.card(
            rx.vstack(
                rx.heading("Danger zone", size="3"),
                rx.cond(
                    S.confirm_reset,
                    rx.vstack(
                        rx.text("Erase every strongman log, override and TM in this app?", size="2"),
                        rx.hstack(rx.button("Yes, erase", color_scheme="red", on_click=S.do_reset),
                                  rx.button("Cancel", variant="soft", color_scheme="gray", on_click=S.cancel_reset),
                                  spacing="2"),
                        spacing="2",
                    ),
                    rx.button("Reset strongman data", color_scheme="red", variant="soft", on_click=S.ask_reset),
                ),
                rx.cond(S.settings_msg, rx.text(S.settings_msg, size="2", color_scheme="gray"), rx.fragment()),
                spacing="2", width="100%", align="start",
            ),
            width="100%",
        ),
        spacing="3", align="stretch", width="100%",
    )
    return layout(body, title="Strongman — Settings")


def _tm_edit_row(row) -> rx.Component:
    return rx.hstack(
        rx.text(row["name"], size="2", flex="1"),
        rx.input(default_value=row["q1"], on_blur=lambda v: S.set_tm_value(row["lift_id"], 1, v),
                 type="number", width="3.5rem", size="1"),
        rx.input(default_value=row["q2"], on_blur=lambda v: S.set_tm_value(row["lift_id"], 2, v),
                 type="number", width="3.5rem", size="1"),
        rx.input(default_value=row["q3"], on_blur=lambda v: S.set_tm_value(row["lift_id"], 3, v),
                 type="number", width="3.5rem", size="1"),
        rx.input(default_value=row["q4"], on_blur=lambda v: S.set_tm_value(row["lift_id"], 4, v),
                 type="number", width="3.5rem", size="1"),
        spacing="1", align="center", width="100%",
    )
