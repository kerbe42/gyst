"""Page components for the House App demo."""

from __future__ import annotations

import reflex as rx
# `set_color_mode` isn't re-exported on the top-level `rx` namespace in
# Reflex 0.9 — pull it from the underlying module.
from reflex_base.style import set_color_mode

import config
from house_demo.layout import layout
from house_demo.states import (
    AnnouncementsState,
    AppointmentsState,
    AuthState,
    CalendarState,
    ChoresAddState,
    ChoresPeopleState,
    ChoresTasksState,
    GroceriesState,
    HomeState,
    InventoryBrowseState,
    InventoryCaptureState,
    InventoryEditState,
    InventoryFoodState,
    InventoryForSaleState,
    InventorySearchState,
    InventoryTrashState,
    AssistantState,
    ItemDetailState,
    MealsState,
    NotesState,
    SettingsState,
    ShareHandoffState,
)


def share_handoff_page() -> rx.Component:
    """PWA Web Share Target disambiguator. Reads the `text` query param
    (set by /share-target's redirect) and offers three sinks."""
    return layout(
        rx.vstack(
            rx.heading("Share to GYST", size="6"),
            rx.text(
                "Where should this go?",
                color_scheme="gray",
                size="2",
            ),
            rx.card(
                rx.vstack(
                    rx.text("Shared text", size="1", color_scheme="gray"),
                    rx.text(
                        ShareHandoffState.shared_text,
                        size="2",
                        style={"white_space": "pre-wrap"},
                    ),
                    spacing="2",
                    align="start",
                ),
                width="100%",
            ),
            rx.vstack(
                rx.button(
                    rx.icon("notebook-pen", size=18),
                    "Save as note",
                    on_click=ShareHandoffState.save_as_note,
                    size="4",
                    width="100%",
                ),
                rx.button(
                    rx.icon("shopping-cart", size=18),
                    "Add to grocery list",
                    on_click=ShareHandoffState.add_to_groceries,
                    size="4",
                    width="100%",
                    color_scheme="green",
                ),
                rx.button(
                    rx.icon("list-checks", size=18),
                    "Create a task",
                    on_click=ShareHandoffState.create_task,
                    size="4",
                    width="100%",
                ),
                spacing="3",
                width="100%",
            ),
            spacing="4",
            width="100%",
            max_width="32em",
            margin="0 auto",
            padding="1em",
        ),
        title="Share to GYST",
    )


# ---- Shared helpers ----------------------------------------------------------
def _person_chip(name, color) -> rx.Component:
    return rx.hstack(
        rx.box(
            width="10px",
            height="10px",
            border_radius="50%",
            background_color=color,
            flex_shrink="0",
        ),
        rx.text(name, size="2"),
        spacing="2",
        align="center",
    )


def _empty(message: str) -> rx.Component:
    return rx.callout(message, icon="info", color_scheme="gray")


def _empty_cta(
    icon: str, message: str, cta_label: str, cta_href: str,
) -> rx.Component:
    """Friendly empty state with a single primary CTA button."""
    return rx.card(
        rx.vstack(
            rx.icon(icon, size=32, color=rx.color("gray", 9)),
            rx.text(message, size="3", color_scheme="gray", text_align="center"),
            rx.button(
                cta_label,
                on_click=rx.redirect(cta_href),
                size="3",
            ),
            spacing="3",
            align="center",
            width="100%",
            padding_y="6",
        ),
        size="2",
        width="100%",
    )


# ---- Home --------------------------------------------------------------------
def _stat_card(
    icon: str,
    label: str,
    value,
    *,
    sublabel=None,
    accent: str = "indigo",
    href: str | None = None,
) -> rx.Component:
    """Headline stat card. Three fixed-height rows so every card lines up
    in the grid regardless of whether it has a sublabel."""
    body = rx.card(
        rx.vstack(
            rx.hstack(
                rx.icon(icon, size=18, color=rx.color(accent, 10)),
                rx.text(
                    label,
                    size="1",
                    weight="bold",
                    color_scheme="gray",
                    text_transform="uppercase",
                    letter_spacing="0.06em",
                ),
                spacing="2",
                align="center",
                height="1.5rem",
            ),
            rx.text(
                value,
                size="8",
                weight="bold",
                line_height="1",
                class_name="stat-value",
            ),
            rx.box(
                rx.cond(
                    sublabel is not None,
                    rx.text(sublabel, size="1", color_scheme="gray"),
                    rx.text(" ", size="1", color_scheme="gray"),
                ),
                height="1.25rem",
                width="100%",
            ),
            spacing="2",
            align="start",
            width="100%",
            height="100%",
            justify="between",
        ),
        size="3",
        width="100%",
        height="100%",
        class_name="inv-card stat-card",
    )
    if href:
        return rx.link(
            body,
            href=href,
            underline="none",
            width="100%",
            height="100%",
            class_name="stat-card-link",
        )
    return body

def _bar_chart(data, *, x_key: str = "name", y_key: str = "count", color: str = "indigo") -> rx.Component:
    return rx.recharts.bar_chart(
        rx.recharts.bar(data_key=y_key, fill=rx.color(color, 9), radius=6),
        rx.recharts.x_axis(
            data_key=x_key,
            interval=0,
            angle=-30,
            text_anchor="end",
            height=70,
        ),
        rx.recharts.y_axis(allow_decimals=False),
        rx.recharts.cartesian_grid(stroke_dasharray="3 3", stroke_opacity=0.2),
        rx.recharts.graphing_tooltip(),
        data=data,
        width="100%",
        height=280,
    )


def _person_bar(p) -> rx.Component:
    """A horizontal row showing one person's open/done counts."""
    return rx.hstack(
        rx.box(
            width="10px",
            height="10px",
            border_radius="50%",
            background_color=p["color"],
            flex_shrink="0",
        ),
        rx.text(p["name"], weight="medium", size="2", min_width="120px"),
        rx.badge(p["open"], " open", color_scheme="orange", variant="soft"),
        rx.badge(p["done"], " done", color_scheme="green", variant="soft"),
        spacing="3",
        align="center",
        width="100%",
    )


def _briefing_pill(icon: str, name: str, detail: str, href: str) -> rx.Component:
    """One line in the heads-up card."""
    return rx.link(
        rx.hstack(
            rx.icon(icon, size=14, color=rx.color("gray", 10)),
            rx.text(name, size="2", weight="medium"),
            rx.text(detail, size="1", color_scheme="gray"),
            spacing="2",
            align="center",
            width="100%",
        ),
        href=href,
        underline="none",
        width="100%",
    )


def _agenda_row(row) -> rx.Component:
    return rx.link(
        rx.hstack(
            rx.match(
                row["kind"],
                ("task", rx.icon("list-checks", size=16, color=rx.color("indigo", 10))),
                ("appointment", rx.icon("calendar", size=16, color=rx.color("indigo", 10))),
                rx.icon("dot", size=16, color=rx.color("indigo", 10)),
            ),
            rx.vstack(
                rx.text(row["title"], size="2", weight="medium"),
                rx.text(row["subtitle"], size="1", color_scheme="gray"),
                spacing="0",
                align="start",
            ),
            spacing="3",
            align="center",
            width="100%",
        ),
        href=row["href"],
        underline="none",
        width="100%",
    )


def _activity_row(row) -> rx.Component:
    inner = rx.hstack(
        rx.match(
            row["icon"],
            ("package", rx.icon("package", size=14, color=rx.color("gray", 10))),
            ("list-checks", rx.icon("list-checks", size=14, color=rx.color("gray", 10))),
            ("sticky-note", rx.icon("sticky-note", size=14, color=rx.color("gray", 10))),
            ("shopping-cart", rx.icon("shopping-cart", size=14, color=rx.color("gray", 10))),
            ("calendar", rx.icon("calendar", size=14, color=rx.color("gray", 10))),
            rx.icon("dot", size=14, color=rx.color("gray", 10)),
        ),
        rx.text(row["text"], size="2", flex="1"),
        rx.text(row["ts_rel"], size="1", color_scheme="gray"),
        spacing="2",
        align="center",
        width="100%",
    )
    return rx.link(
        inner,
        href=row["href"],
        underline="none",
        width="100%",
    )


def _heads_up_bucket(
    label: str, see_all_href: str, rows, icon: str,
) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text(
                label,
                size="1",
                weight="bold",
                color_scheme="gray",
                text_transform="uppercase",
                letter_spacing="0.06em",
            ),
            rx.spacer(),
            rx.link(
                rx.text("see all", size="1"),
                href=see_all_href,
                underline="hover",
            ),
            align="center",
            width="100%",
        ),
        rx.cond(
            rows,
            rx.vstack(
                rx.foreach(
                    rows,
                    lambda r: _briefing_pill(icon, r["name"], r["detail"], r["href"]),
                ),
                spacing="1",
                align="stretch",
                width="100%",
            ),
            rx.text("Nothing pending.", size="1", color_scheme="gray"),
        ),
        spacing="1",
        align="stretch",
        width="100%",
    )


def _low_stock_row(row) -> rx.Component:
    return rx.hstack(
        rx.icon("shopping-cart", size=14, color=rx.color("gray", 10)),
        rx.text(row["name"], size="2", flex="1"),
        rx.text("re-add?", size="1", color_scheme="gray"),
        spacing="2",
        align="center",
        width="100%",
    )


def _heads_up_chip(label, href, icon: str) -> rx.Component:
    return rx.link(
        rx.hstack(
            rx.icon(icon, size=14, color=rx.color("amber", 10)),
            rx.text(label, size="1"),
            spacing="1",
            align="center",
        ),
        href=href,
        underline="hover",
        class_name="heads-up-chip",
    )


def home_page() -> rx.Component:
    return layout(
        rx.vstack(
            rx.vstack(
                rx.heading(
                    HomeState.greeting,
                    size="6",
                    weight="bold",
                    class_name="home-greeting",
                ),
                rx.text(
                    HomeState.greeting_time,
                    size="2",
                    color_scheme="gray",
                    class_name="home-greeting-time",
                ),
                spacing="0",
                align="start",
                class_name="home-greeting-stack",
            ),
            rx.card(
                rx.vstack(
                    rx.heading("Today's agenda", size="4"),
                    rx.cond(
                        HomeState.agenda,
                        rx.vstack(
                            rx.foreach(HomeState.agenda, _agenda_row),
                            spacing="2",
                            align="stretch",
                            width="100%",
                        ),
                        rx.text(
                            "Nothing on the books today — enjoy it.",
                            size="2",
                            color_scheme="gray",
                        ),
                    ),
                    spacing="3",
                    align="stretch",
                ),
                size="3",
                width="100%",
            ),
            rx.cond(
                HomeState.heads_up_any,
                rx.card(
                    rx.vstack(
                        rx.heading("Heads-up", size="4"),
                        rx.hstack(
                            rx.cond(
                                HomeState.expiring_food_count > 0,
                                _heads_up_chip(
                                    HomeState.expiring_food_count.to_string()
                                    + " expiring",
                                    "/inventory/food",
                                    "apple",
                                ),
                                rx.fragment(),
                            ),
                            rx.cond(
                                HomeState.returnable_soon_count > 0,
                                _heads_up_chip(
                                    HomeState.returnable_soon_count.to_string()
                                    + " return windows closing",
                                    "/inventory/browse",
                                    "undo-2",
                                ),
                                rx.fragment(),
                            ),
                            rx.cond(
                                HomeState.warranty_soon_count > 0,
                                _heads_up_chip(
                                    HomeState.warranty_soon_count.to_string()
                                    + " warranties soon",
                                    "/inventory/browse",
                                    "shield-check",
                                ),
                                rx.fragment(),
                            ),
                            spacing="2",
                            wrap="wrap",
                            align="center",
                        ),
                        spacing="2",
                        align="stretch",
                    ),
                    size="3",
                    width="100%",
                ),
                rx.fragment(),
            ),
            rx.card(
                rx.vstack(
                    rx.heading("Low-stock prompts", size="4"),
                    rx.cond(
                        HomeState.low_stock,
                        rx.vstack(
                            rx.foreach(HomeState.low_stock, _low_stock_row),
                            spacing="2",
                            align="stretch",
                            width="100%",
                        ),
                        rx.text(
                            "Pantry's looking topped up.",
                            size="2",
                            color_scheme="gray",
                        ),
                    ),
                    rx.link(
                        rx.text("Open shopping list →", size="1"),
                        href="/groceries",
                        underline="hover",
                    ),
                    spacing="3",
                    align="stretch",
                ),
                size="3",
                width="100%",
            ),
            rx.card(
                rx.vstack(
                    rx.heading("Recent activity", size="4"),
                    rx.cond(
                        HomeState.activity,
                        rx.vstack(
                            rx.foreach(HomeState.activity, _activity_row),
                            spacing="2",
                            align="stretch",
                            width="100%",
                        ),
                        rx.text(
                            "Nothing's happened yet — get started below.",
                            size="2",
                            color_scheme="gray",
                        ),
                    ),
                    spacing="3",
                    align="stretch",
                ),
                size="3",
                width="100%",
            ),
            spacing="4",
            align="stretch",
            width="100%",
        ),
        title=None,
    )



# ---- Inventory cards ---------------------------------------------------------
def _qty_overlay(qty) -> rx.Component:
    return rx.cond(
        qty.to(int) > 1,
        rx.box(rx.text("×", qty), class_name="inv-qty-badge"),
        rx.fragment(),
    )


def _value_and_sale(item) -> rx.Component:
    return rx.hstack(
        rx.cond(
            item["value_display"],
            rx.badge(
                item["value_display"],
                color_scheme="gray",
                variant="soft",
            ),
            rx.fragment(),
        ),
        rx.cond(
            item["for_sale_bool"],
            rx.badge("For sale", color_scheme="green", variant="solid"),
            rx.fragment(),
        ),
        spacing="2",
        align="center",
        wrap="wrap",
    )


def _meta_line(icon: str, text_var) -> rx.Component:
    return rx.hstack(
        rx.icon(icon, size=14, color=rx.color("gray", 10)),
        rx.text(text_var, size="2"),
        spacing="2",
        align="center",
    )


def _history_row(row) -> rx.Component:
    """One row in the item-history collapsible inside the edit dialog."""
    return rx.hstack(
        rx.badge(row["kind"], variant="soft", size="1"),
        rx.text(row["text"], size="2", flex="1"),
        rx.text(row["ts_rel"], size="1", color_scheme="gray"),
        spacing="2",
        align="center",
        width="100%",
    )


def _inventory_edit_dialog() -> rx.Component:
    """Shared edit dialog used by both Search and Browse pages."""
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Edit item"),
            rx.vstack(
                rx.text("Name", size="2", weight="bold"),
                rx.input(
                    value=InventoryEditState.editing_name,
                    on_change=InventoryEditState.set_editing_name,
                    size="3",
                ),
                rx.hstack(
                    rx.vstack(
                        rx.text("Quantity", size="2", weight="bold"),
                        rx.input(
                            value=InventoryEditState.editing_quantity.to(str),
                            on_change=InventoryEditState.set_editing_quantity,
                            type="number",
                            size="3",
                            width="100px",
                        ),
                        spacing="1",
                        align="start",
                    ),
                    rx.vstack(
                        rx.text("Category", size="2", weight="bold"),
                        rx.select(
                            InventoryEditState.category_options,
                            value=InventoryEditState.editing_category,
                            on_change=InventoryEditState.set_editing_category,
                            size="3",
                        ),
                        spacing="1",
                        align="start",
                        flex="1",
                    ),
                    spacing="3",
                    align="start",
                ),
                rx.vstack(
                    rx.text("Estimated value (USD)", size="2", weight="bold"),
                    rx.input(
                        value=InventoryEditState.editing_value.to(str),
                        on_change=InventoryEditState.set_editing_value,
                        type="number",
                        size="3",
                        width="160px",
                    ),
                    spacing="1",
                    align="start",
                ),
                rx.vstack(
                    rx.text("Room", size="2", weight="bold"),
                    rx.badge(
                        "Affects all items from this photo",
                        color_scheme="orange",
                        variant="soft",
                    ),
                    rx.select(
                        InventoryEditState.room_options,
                        value=InventoryEditState.editing_room,
                        on_change=InventoryEditState.set_editing_room,
                        size="3",
                    ),
                    spacing="1",
                    align="start",
                ),
                rx.checkbox(
                    "For sale",
                    checked=InventoryEditState.editing_for_sale,
                    on_change=InventoryEditState.set_editing_for_sale,
                ),
                # ---- Purchase / warranty subsection ----
                rx.divider(margin_y="0.25em"),
                rx.text("Purchase", size="2", weight="bold"),
                rx.hstack(
                    rx.vstack(
                        rx.text("Purchase date", size="1", color_scheme="gray"),
                        rx.input(
                            value=InventoryEditState.editing_purchase_date,
                            on_change=InventoryEditState.set_editing_purchase_date,
                            type="date",
                            size="2",
                        ),
                        spacing="1", align="start",
                    ),
                    rx.vstack(
                        rx.text("Price ($)", size="1", color_scheme="gray"),
                        rx.input(
                            value=InventoryEditState.editing_purchase_price.to(str),
                            on_change=InventoryEditState.set_editing_purchase_price,
                            type="number",
                            size="2",
                            width="100px",
                        ),
                        spacing="1", align="start",
                    ),
                    spacing="3", align="start",
                ),
                rx.vstack(
                    rx.text("Store", size="1", color_scheme="gray"),
                    rx.input(
                        value=InventoryEditState.editing_purchase_store,
                        on_change=InventoryEditState.set_editing_purchase_store,
                        size="2",
                    ),
                    spacing="1", align="start", width="100%",
                ),
                rx.hstack(
                    rx.vstack(
                        rx.text("Return by", size="1", color_scheme="gray"),
                        rx.input(
                            value=InventoryEditState.editing_return_until,
                            on_change=InventoryEditState.set_editing_return_until,
                            type="date",
                            size="2",
                        ),
                        spacing="1", align="start",
                    ),
                    rx.vstack(
                        rx.text("Warranty until", size="1", color_scheme="gray"),
                        rx.input(
                            value=InventoryEditState.editing_warranty_until,
                            on_change=InventoryEditState.set_editing_warranty_until,
                            type="date",
                            size="2",
                        ),
                        spacing="1", align="start",
                    ),
                    spacing="3", align="start",
                ),
                # ---- History collapsible ----
                rx.cond(
                    InventoryEditState.history_rows,
                    rx.box(
                        rx.el.details(
                            rx.el.summary(
                                rx.text("History", size="2", weight="bold"),
                            ),
                            rx.vstack(
                                rx.foreach(
                                    InventoryEditState.history_rows,
                                    _history_row,
                                ),
                                spacing="1",
                                align="stretch",
                                width="100%",
                                margin_top="0.5em",
                            ),
                        ),
                        width="100%",
                    ),
                    rx.fragment(),
                ),
                rx.cond(
                    InventoryEditState.error,
                    rx.callout(
                        InventoryEditState.error,
                        icon="triangle_alert",
                        color_scheme="red",
                    ),
                    rx.fragment(),
                ),
                rx.cond(
                    InventoryEditState.pending_room_change_count > 0,
                    rx.callout(
                        rx.vstack(
                            rx.text(
                                "Changing the room will move every item from "
                                "this photo into the new room.",
                                size="2",
                            ),
                            rx.hstack(
                                rx.button(
                                    "Move all ",
                                    InventoryEditState.pending_room_change_count.to(str),
                                    " items",
                                    on_click=InventoryEditState.confirm_room_change,
                                    color_scheme="orange",
                                ),
                                rx.button(
                                    "Cancel",
                                    on_click=InventoryEditState.cancel_room_change,
                                    variant="soft",
                                    color_scheme="gray",
                                ),
                                spacing="2",
                            ),
                            spacing="2",
                            align="start",
                        ),
                        icon="triangle_alert",
                        color_scheme="orange",
                    ),
                    rx.fragment(),
                ),
                rx.divider(margin_y="0.5em"),
                rx.hstack(
                    rx.button(
                        "Cancel",
                        on_click=InventoryEditState.close_edit,
                        variant="soft",
                        color_scheme="gray",
                        flex="1",
                    ),
                    rx.button(
                        "Save",
                        on_click=InventoryEditState.save_edit,
                        flex="1",
                    ),
                    spacing="2",
                    width="100%",
                    class_name="edit-dialog-footer",
                ),
                spacing="3",
                align="stretch",
                width="100%",
            ),
            max_width="500px",
            max_height="85vh",
            overflow_y="auto",
        ),
        open=InventoryEditState.editing_id != 0,
        on_open_change=InventoryEditState.handle_open_change,
    )


def _item_link(item_id, child: rx.Component) -> rx.Component:
    """Wrap a child in a link to the item detail page."""
    return rx.link(
        child,
        href=f"/inventory/item/{item_id}",
        underline="none",
        color="inherit",
    )


def _view_mode_switcher(state) -> rx.Component:
    """Three-button group for switching between List / Grid / Compact."""
    return rx.hstack(
        rx.button(
            rx.icon("list", size=14),
            on_click=state.set_view_mode("list"),
            variant=rx.cond(state.view_mode == "list", "solid", "soft"),
            color_scheme="indigo",
            size="2",
            title="List view",
        ),
        rx.button(
            rx.icon("layout-grid", size=14),
            on_click=state.set_view_mode("grid"),
            variant=rx.cond(state.view_mode == "grid", "solid", "soft"),
            color_scheme="indigo",
            size="2",
            title="Grid view",
        ),
        rx.button(
            rx.icon("rows-3", size=14),
            on_click=state.set_view_mode("compact"),
            variant=rx.cond(state.view_mode == "compact", "solid", "soft"),
            color_scheme="indigo",
            size="2",
            title="Compact view",
        ),
        spacing="1",
        align="center",
    )


def _grid_card(item, delete_handler) -> rx.Component:
    """Compact grid tile — photo on top, name + badges below."""
    return rx.card(
        rx.vstack(
            _item_link(
                item["id"],
                rx.box(
                    rx.image(
                        src=item["crop_url"],
                        width="100%",
                        height="160px",
                        object_fit="cover",
                        key=item["id"].to(str),
                        loading="eager",
                    ),
                    _qty_overlay(item["quantity"]),
                    class_name="inv-photo-wrap",
                ),
            ),
            _item_link(
                item["id"],
                rx.heading(item["name"], size="3", line_height="1.2"),
            ),
            rx.hstack(
                rx.badge(
                    item["category"], color_scheme="indigo", variant="soft"
                ),
                rx.cond(
                    item["value_display"],
                    rx.badge(
                        item["value_display"],
                        color_scheme="gray",
                        variant="soft",
                    ),
                    rx.fragment(),
                ),
                rx.cond(
                    item["for_sale_bool"],
                    rx.badge("For sale", color_scheme="green", variant="solid"),
                    rx.fragment(),
                ),
                spacing="1",
                wrap="wrap",
            ),
            _meta_line("map-pin", item["room"]),
            rx.hstack(
                rx.button(
                    rx.icon("pencil", size=14),
                    on_click=InventoryEditState.open_edit(item["id"]),
                    variant="soft",
                    size="1",
                ),
                rx.button(
                    rx.icon("trash-2", size=14),
                    on_click=delete_handler,
                    color_scheme="red",
                    variant="soft",
                    size="1",
                    aria_label='Delete',
                ),
                spacing="1",
            ),
            spacing="2",
            align="stretch",
            width="100%",
        ),
        class_name="inv-card",
        size="2",
        width="100%",
    )


def _compact_card(item, delete_handler) -> rx.Component:
    """Dense single-row layout — tiny photo, then name / room / actions."""
    return rx.card(
        rx.hstack(
            _item_link(
                item["id"],
                rx.image(
                    src=item["crop_url"],
                    width="56px",
                    height="56px",
                    object_fit="cover",
                    border_radius="0.4em",
                    key=item["id"].to(str),
                    loading="eager",
                ),
            ),
            _item_link(
                item["id"],
                rx.vstack(
                    rx.text(item["name"], weight="bold", size="3"),
                    rx.hstack(
                        rx.text(item["room"], size="1", color_scheme="gray"),
                        rx.cond(
                            item["value_display"],
                            rx.text(
                                item["value_display"],
                                size="1",
                                color_scheme="gray",
                            ),
                            rx.fragment(),
                        ),
                        rx.cond(
                            item["for_sale_bool"],
                            rx.badge(
                                "For sale",
                                color_scheme="green",
                                variant="solid",
                                size="1",
                            ),
                            rx.fragment(),
                        ),
                        spacing="2",
                        align="center",
                    ),
                    spacing="0",
                    align="start",
                    flex="1",
                ),
            ),
            rx.spacer(),
            rx.hstack(
                rx.button(
                    rx.icon("pencil", size=12),
                    on_click=InventoryEditState.open_edit(item["id"]),
                    variant="soft",
                    size="1",
                ),
                rx.button(
                    rx.icon("trash-2", size=12),
                    on_click=delete_handler,
                    color_scheme="red",
                    variant="soft",
                    size="1",
                    aria_label='Delete',
                ),
                spacing="1",
            ),
            spacing="3",
            align="center",
            width="100%",
        ),
        class_name="inv-card",
        size="1",
        width="100%",
    )


def _item_actions(item_id, delete_handler) -> rx.Component:
    return rx.hstack(
        rx.button(
            rx.icon("pencil", size=14),
            "Edit",
            on_click=InventoryEditState.open_edit(item_id),
            variant="soft",
            size="2",
        ),
        rx.button(
            rx.icon("trash-2", size=14),
            "Delete",
            on_click=delete_handler,
            color_scheme="red",
            variant="soft",
            size="2",
        ),
        spacing="2",
        align="center",
    )


def _search_card(r) -> rx.Component:
    return rx.card(
        rx.hstack(
            _item_link(
                r["id"],
                rx.box(
                    rx.image(
                        src=r["crop_url"],
                        width="200px",
                        height="200px",
                        object_fit="cover",
                        key=r["id"].to(str),
                        loading="eager",
                    ),
                    _qty_overlay(r["quantity"]),
                    class_name="inv-photo-wrap",
                ),
            ),
            rx.vstack(
                _item_link(
                    r["id"],
                    rx.heading(r["name"], size="6", line_height="1.2"),
                ),
                rx.hstack(
                    rx.badge(
                        r["category"], color_scheme="indigo", variant="soft"
                    ),
                    rx.cond(
                        r["value_display"],
                        rx.badge(
                            r["value_display"],
                            color_scheme="gray",
                            variant="soft",
                        ),
                        rx.fragment(),
                    ),
                    rx.cond(
                        r["for_sale_bool"],
                        rx.badge(
                            "For sale", color_scheme="green", variant="solid"
                        ),
                        rx.fragment(),
                    ),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                _meta_line("map-pin", r["room"]),
                _meta_line("clock", r["created_at"]),
                rx.spacer(),
                _item_actions(
                    r["id"], InventorySearchState.delete_item(r["id"])
                ),
                spacing="3",
                align="start",
                flex="1",
                height="100%",
                padding_y="0.25em",
            ),
            spacing="4",
            align="stretch",
            width="100%",
        ),
        class_name="inv-card",
        size="3",
        width="100%",
    )


def _search_grid_card(item) -> rx.Component:
    return _grid_card(
        item, InventorySearchState.delete_item(item["id"])
    )


def _search_compact_card(item) -> rx.Component:
    return _compact_card(
        item, InventorySearchState.delete_item(item["id"])
    )


def _browse_grid_card(item) -> rx.Component:
    return _grid_card(
        item, InventoryBrowseState.delete_item(item["id"])
    )


def _browse_compact_card(item) -> rx.Component:
    return _compact_card(
        item, InventoryBrowseState.delete_item(item["id"])
    )


def inventory_search_page() -> rx.Component:
    return layout(
        rx.fragment(
            _inventory_edit_dialog(),
            rx.vstack(
                rx.hstack(
                    rx.input(
                        placeholder="e.g. drill, scissors, charger",
                        value=InventorySearchState.query,
                        on_change=InventorySearchState.set_query,
                        size="3",
                        flex="1",
                    ),
                    _view_mode_switcher(InventorySearchState),
                    spacing="3",
                    align="center",
                    width="100%",
                ),
                rx.cond(
                    InventorySearchState.results,
                    rx.vstack(
                        rx.text(
                            "Found ",
                            InventorySearchState.results.length(),
                            " sighting(s) — most recent first.",
                            color_scheme="gray",
                            size="2",
                        ),
                        rx.match(
                            InventorySearchState.view_mode,
                            (
                                "grid",
                                rx.grid(
                                    rx.foreach(
                                        InventorySearchState.results,
                                        _search_grid_card,
                                    ),
                                    columns=rx.breakpoints(
                                        initial="2", sm="3", md="4"
                                    ),
                                    spacing="3",
                                    width="100%",
                                ),
                            ),
                            (
                                "compact",
                                rx.vstack(
                                    rx.foreach(
                                        InventorySearchState.results,
                                        _search_compact_card,
                                    ),
                                    spacing="2",
                                    align="stretch",
                                    width="100%",
                                ),
                            ),
                            rx.vstack(
                                rx.foreach(
                                    InventorySearchState.results, _search_card
                                ),
                                spacing="3",
                                align="stretch",
                                width="100%",
                            ),
                        ),
                        spacing="3",
                        align="stretch",
                        width="100%",
                    ),
                    rx.cond(
                        InventorySearchState.query,
                        _empty("Nothing found for that query."),
                        _empty("Type to search the inventory."),
                    ),
                ),
                spacing="4",
                align="stretch",
                width="100%",
            ),
        ),
        title="Where is my…",
    )


# ---- Inventory Browse --------------------------------------------------------
def _browse_card(item) -> rx.Component:
    return rx.card(
        rx.hstack(
            _item_link(
                item["id"],
                rx.box(
                    rx.image(
                        src=item["crop_url"],
                        width="200px",
                        height="200px",
                        object_fit="cover",
                        key=item["id"].to(str),
                        loading="eager",
                    ),
                    _qty_overlay(item["quantity"]),
                    class_name="inv-photo-wrap",
                ),
            ),
            rx.vstack(
                _item_link(
                    item["id"],
                    rx.heading(item["name"], size="6", line_height="1.2"),
                ),
                rx.hstack(
                    rx.badge(
                        item["category"], color_scheme="indigo", variant="soft"
                    ),
                    rx.cond(
                        item["value_display"],
                        rx.badge(
                            item["value_display"],
                            color_scheme="gray",
                            variant="soft",
                        ),
                        rx.fragment(),
                    ),
                    rx.cond(
                        item["for_sale_bool"],
                        rx.badge(
                            "For sale", color_scheme="green", variant="solid"
                        ),
                        rx.fragment(),
                    ),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                _meta_line("map-pin", item["room"]),
                _meta_line("clock", item["photo_taken_at"]),
                rx.spacer(),
                _item_actions(
                    item["id"], InventoryBrowseState.delete_item(item["id"])
                ),
                spacing="3",
                align="start",
                flex="1",
                height="100%",
                padding_y="0.25em",
            ),
            spacing="4",
            align="stretch",
            width="100%",
        ),
        class_name="inv-card",
        size="3",
        width="100%",
    )


def _room_stat(row) -> rx.Component:
    # Compact two-line chip: room name on top, count below. CSS class
    # `inv-stat-card` is keyed to a responsive grid in styles.css so
    # the strip wraps instead of scrolling horizontally.
    return rx.box(
        rx.text(row["room"], class_name="inv-stat-room"),
        rx.text(row["count"], class_name="inv-stat-count"),
        class_name="inv-stat-card",
    )


def inventory_browse_page() -> rx.Component:
    return layout(
        rx.fragment(
            _inventory_edit_dialog(),
            rx.vstack(
                rx.cond(
                    InventoryBrowseState.room_summary,
                    rx.box(
                        rx.foreach(
                            InventoryBrowseState.room_summary, _room_stat
                        ),
                        class_name="inv-stat-strip",
                    ),
                    rx.fragment(),
                ),
                rx.hstack(
                    rx.vstack(
                        rx.text("Room", size="1", weight="bold"),
                        rx.select(
                            InventoryBrowseState.room_options,
                            value=InventoryBrowseState.room,
                            on_change=InventoryBrowseState.set_room,
                            size="3",
                        ),
                        spacing="1",
                        align="stretch",
                    ),
                    rx.vstack(
                        rx.text("Category", size="1", weight="bold"),
                        rx.select(
                            InventoryBrowseState.category_options,
                            value=InventoryBrowseState.category_filter,
                            on_change=InventoryBrowseState.set_category,
                            size="3",
                        ),
                        spacing="1",
                        align="stretch",
                    ),
                    rx.vstack(
                        rx.text("Listing", size="1", weight="bold"),
                        rx.select(
                            InventoryBrowseState.for_sale_options,
                            value=InventoryBrowseState.for_sale_filter,
                            on_change=InventoryBrowseState.set_for_sale,
                            size="3",
                        ),
                        spacing="1",
                        align="stretch",
                    ),
                    rx.vstack(
                        rx.text("Sort by", size="1", weight="bold"),
                        rx.select(
                            InventoryBrowseState.sort_options,
                            value=InventoryBrowseState.sort_by,
                            on_change=InventoryBrowseState.set_sort,
                            size="3",
                        ),
                        spacing="1",
                        align="stretch",
                    ),
                    spacing="3",
                    wrap="wrap",
                    align="end",
                ),
                rx.hstack(
                    rx.spacer(),
                    _view_mode_switcher(InventoryBrowseState),
                    align="center",
                    width="100%",
                ),
                rx.cond(
                    InventoryBrowseState.items,
                    rx.vstack(
                        rx.text(
                            InventoryBrowseState.items.length(),
                            " item(s) in ",
                            rx.text.strong(InventoryBrowseState.room),
                            ".",
                            color_scheme="gray",
                            size="2",
                        ),
                        rx.match(
                            InventoryBrowseState.view_mode,
                            (
                                "grid",
                                rx.grid(
                                    rx.foreach(
                                        InventoryBrowseState.items,
                                        _browse_grid_card,
                                    ),
                                    columns=rx.breakpoints(
                                        initial="2", sm="3", md="4"
                                    ),
                                    spacing="3",
                                    width="100%",
                                ),
                            ),
                            (
                                "compact",
                                rx.vstack(
                                    rx.foreach(
                                        InventoryBrowseState.items,
                                        _browse_compact_card,
                                    ),
                                    spacing="2",
                                    align="stretch",
                                    width="100%",
                                ),
                            ),
                            rx.vstack(
                                rx.foreach(
                                    InventoryBrowseState.items, _browse_card
                                ),
                                spacing="3",
                                align="stretch",
                                width="100%",
                            ),
                        ),
                        spacing="3",
                        align="stretch",
                        width="100%",
                    ),
                    _empty_cta("package-open", "No items match. Clear filters or add items.", "Capture item", "/inventory/capture"),
                ),
                spacing="4",
                align="stretch",
                width="100%",
            ),
        ),
        title="Browse inventory",
    )


# ---- Inventory Trash ---------------------------------------------------------
def _trash_card(item) -> rx.Component:
    return rx.card(
        rx.hstack(
            rx.box(
                rx.image(
                    src=item["crop_url"],
                    width="180px",
                    height="180px",
                    object_fit="cover",
                    key=item["id"].to(str),
                    loading="eager",
                ),
                _qty_overlay(item["quantity"]),
                class_name="inv-photo-wrap",
            ),
            rx.vstack(
                rx.hstack(
                    rx.heading(item["name"], size="5"),
                    rx.badge(
                        item["category"], color_scheme="indigo", variant="soft"
                    ),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                rx.hstack(
                    rx.icon("map-pin", size=14),
                    rx.text(item["room"], size="2"),
                    spacing="1",
                    align="center",
                ),
                rx.hstack(
                    rx.icon("trash-2", size=14),
                    rx.text(
                        "Deleted ", item["deleted_at"],
                        color_scheme="gray", size="2",
                    ),
                    spacing="1",
                    align="center",
                ),
                rx.spacer(),
                rx.hstack(
                    rx.button(
                        rx.icon("rotate-ccw", size=14),
                        "Restore",
                        on_click=InventoryTrashState.restore(item["id"]),
                        color_scheme="indigo",
                        variant="soft",
                        size="2",
                    ),
                    rx.popover.root(
                        rx.popover.trigger(
                            rx.button(
                                rx.icon("x", size=14),
                                "Delete forever",
                                color_scheme="red",
                                variant="soft",
                                size="2",
                            ),
                        ),
                        rx.popover.content(
                            rx.vstack(
                                rx.text(
                                    "Permanently delete ",
                                    rx.text.strong(item["name"]),
                                    "?",
                                ),
                                rx.text(
                                    "This can't be undone.",
                                    color_scheme="gray",
                                    size="1",
                                ),
                                rx.button(
                                    "Yes, delete forever",
                                    on_click=InventoryTrashState.purge(
                                        item["id"]
                                    ),
                                    color_scheme="red",
                                    width="100%",
                                ),
                                spacing="2",
                                align="stretch",
                            ),
                        ),
                    ),
                    spacing="2",
                ),
                spacing="2",
                align="start",
                flex="1",
                height="100%",
            ),
            spacing="4",
            align="start",
            width="100%",
        ),
        class_name="inv-card",
        size="3",
        width="100%",
    )


def inventory_trash_page() -> rx.Component:
    return layout(
        rx.vstack(
            rx.hstack(
                rx.text(
                    "Soft-deleted items live here until you restore or "
                    "permanently delete them.",
                    color_scheme="gray",
                    size="2",
                    flex="1",
                ),
                rx.cond(
                    InventoryTrashState.items,
                    rx.popover.root(
                        rx.popover.trigger(
                            rx.button(
                                rx.icon("trash-2", size=14),
                                "Empty trash",
                                color_scheme="red",
                                variant="soft",
                                size="2",
                            ),
                        ),
                        rx.popover.content(
                            rx.vstack(
                                rx.text(
                                    "Permanently delete all items in trash?"
                                ),
                                rx.text(
                                    "This can't be undone.",
                                    color_scheme="gray",
                                    size="1",
                                ),
                                rx.button(
                                    "Yes, empty trash",
                                    on_click=InventoryTrashState.empty_trash,
                                    color_scheme="red",
                                    width="100%",
                                ),
                                spacing="2",
                                align="stretch",
                            ),
                        ),
                    ),
                    rx.fragment(),
                ),
                spacing="3",
                align="center",
                width="100%",
            ),
            rx.cond(
                InventoryTrashState.items,
                rx.vstack(
                    rx.foreach(InventoryTrashState.items, _trash_card),
                    spacing="3",
                    align="stretch",
                    width="100%",
                ),
                _empty("Trash is empty."),
            ),
            spacing="4",
            align="stretch",
            width="100%",
        ),
        title="Trash",
    )


# ---- Inventory Capture -------------------------------------------------------
def _saved_summary_row(item) -> rx.Component:
    """One row in the post-capture summary. Items are already saved; the
    user can fix a wrong count with ± or yank it entirely with the trash."""
    crop_url = "/photo_crop/" + item["item_id"].to(str)
    return rx.box(
        rx.hstack(
            # Crop thumbnail — sized to ~64px square.
            rx.box(
                rx.image(
                    src=crop_url,
                    alt=item["name"],
                    width="100%",
                    height="100%",
                    object_fit="cover",
                    loading="lazy",
                ),
                class_name="capture-summary-thumb",
            ),
            # Name + category.
            rx.vstack(
                rx.text(item["name"], weight="bold", size="3"),
                rx.text(item["category"], size="1", color_scheme="gray"),
                spacing="0",
                align="start",
                flex="1",
                min_width="0",
            ),
            # ± quantity controls.
            rx.hstack(
                rx.icon_button(
                    rx.icon("minus", size=18),
                    on_click=InventoryCaptureState.adjust_saved_quantity(
                        item["idx"], -1
                    ),
                    variant="soft",
                    size="3",
                    title="Decrease quantity",
                    aria_label="Decrease quantity",
                ),
                rx.box(
                    rx.text(
                        item["quantity"].to(str),
                        size="3",
                        weight="bold",
                    ),
                    class_name="capture-summary-qty",
                ),
                rx.icon_button(
                    rx.icon("plus", size=18),
                    on_click=InventoryCaptureState.adjust_saved_quantity(
                        item["idx"], 1
                    ),
                    variant="soft",
                    size="3",
                    title="Increase quantity",
                    aria_label="Increase quantity",
                ),
                spacing="1",
                align="center",
            ),
            # Delete.
            rx.icon_button(
                rx.icon("trash-2", size=18),
                on_click=InventoryCaptureState.delete_saved_item(item["idx"]),
                variant="soft",
                color_scheme="red",
                size="3",
                title="Remove from inventory",
                aria_label="Remove from inventory",
            ),
            spacing="3",
            align="center",
            width="100%",
        ),
        class_name="capture-summary-row",
    )

def _barcode_dialog() -> rx.Component:
    """Fixed-position dialog with a <video> preview. Driven entirely by
    window.gystBarcode in barcode.js — Reflex's job here is just to render
    the markup and wire the open/close buttons via rx.call_script."""
    on_open = """
        try {
          window.gystBarcode.open(async (name, upc) => {
            const ev = {name, upc};
            // Stash on window so the Reflex button can read it via the
            // 'Add this product' click handler.
            window.__lastBarcode = ev;
            const status = document.getElementById('barcode-status');
            if (status) status.textContent = 'Found: ' + name + '. Tap Use to add.';
          });
        } catch (e) { alert('Could not open camera: ' + e.message); }
    """
    on_close = "window.gystBarcode.close();"
    # One Add handler that does the right thing whether the user
    # scanned a code OR typed a UPC manually. If both are present,
    # the manual field wins (explicit user input beats stale stage).
    on_add = """
        // Wrapped in a sync body because rx.call_script does not give
        // us a module context — top-level `await` here is a syntax
        // error that would silently disable the button entirely.
        // Everything that needs to await runs inside an async IIFE.
        const status = document.getElementById('barcode-status');
        const upcEl = document.getElementById('barcode-manual-upc');
        const manual = (upcEl && upcEl.value || '').trim();
        function setStatus(s){ if (status) status.textContent = s; }

        if (manual) {
          // Manual UPC path: run the full lookup, then commit.
          (async () => {
            setStatus('Looking up ' + manual + '…');
            try {
              const hit = window.gystBarcode && window.gystBarcode.lookupBarcode
                ? await window.gystBarcode.lookupBarcode(manual) : null;
              if (hit) {
                window.__lastBarcode = {
                  name: hit.name, upc: manual,
                  image_url: hit.image_url || '',
                  est_price_usd: hit.est_price_usd || 0,
                  category: hit.category || 'other',
                  source: hit.source || '',
                };
              } else {
                window.__lastBarcode = {
                  name: manual, upc: manual, image_url: '',
                  est_price_usd: 0, category: 'other', source: ''
                };
              }
              await window.gystBarcode.useCurrentMatch();
            } catch (e) {
              setStatus('Add failed: ' + (e && e.message || e));
            }
          })();
        } else if (window.__lastBarcode && window.__lastBarcode.name) {
          // Scanned-and-staged path: fire and forget; useCurrentMatch
          // handles its own status updates and reload.
          try {
            window.gystBarcode.useCurrentMatch();
          } catch (e) {
            setStatus('Add failed: ' + (e && e.message || e));
          }
        } else {
          setStatus('Aim at a barcode or type a UPC first.');
        }
    """
    return rx.el.div(
        rx.el.div(
            # ---- Header ----
            rx.el.div(
                rx.el.div(
                    "Scan barcode",
                    style={
                        "fontSize": "1.05rem",
                        "fontWeight": "700",
                        "color": "var(--gray-12)",
                    },
                ),
                rx.el.div(
                    "UPC / EAN / ISBN / QR — auto-lookup across food, "
                    "general items, and books.",
                    style={
                        "fontSize": "0.78rem",
                        "color": "var(--gray-11)",
                        "marginTop": "0.2rem",
                    },
                ),
                style={"marginBottom": "0.85rem"},
            ),
            # ---- Viewfinder ----
            rx.el.video(
                id="barcode-video",
                autoplay=True,
                playsinline=True,
                muted=True,
                style={
                    "width": "100%",
                    "aspectRatio": "4/3",
                    "objectFit": "cover",
                    "borderRadius": "0.6rem",
                    "background": "#000",
                    "display": "block",
                },
            ),
            # ---- Status line ----
            rx.el.div(
                "Point the camera at a barcode…",
                id="barcode-status",
                style={
                    "marginTop": "0.7rem",
                    "color": "var(--gray-12)",
                    "fontSize": "0.85rem",
                    "minHeight": "2.6em",
                    "lineHeight": "1.35",
                },
            ),
            # ---- Manual UPC entry ----
            rx.el.div(
                rx.el.label(
                    "Or type a UPC / EAN / ISBN",
                    html_for="barcode-manual-upc",
                    style={
                        "display": "block",
                        "fontSize": "0.78rem",
                        "fontWeight": "600",
                        "color": "var(--gray-11)",
                        "marginBottom": "0.35rem",
                    },
                ),
                rx.el.input(
                    id="barcode-manual-upc",
                    type="text",
                    inputmode="numeric",
                    placeholder="e.g. 0049000028904",
                    style={
                        "width": "100%",
                        "padding": "0.55rem 0.7rem",
                        "borderRadius": "0.5rem",
                        "border": "1px solid var(--gray-6)",
                        "background": "var(--gray-1)",
                        "color": "var(--gray-12)",
                        "fontSize": "0.95rem",
                        "boxSizing": "border-box",
                    },
                ),
                style={
                    "marginTop": "0.85rem",
                    "marginBottom": "0.25rem",
                },
            ),
            # ---- Action row: one Add for both paths, plus Scan again + Cancel ----
            rx.el.div(
                rx.el.button(
                    "Add",
                    on_click=rx.call_script(on_add),
                    class_name="rt-Button rt-r-size-3",
                    style={"flex": "1", "fontWeight": "600"},
                    custom_attrs={"aria-label": "Add scanned or typed barcode"},
                ),
                rx.el.button(
                    "Scan again",
                    id="barcode-rescan-btn",
                    on_click=rx.call_script("window.gystBarcode.rescan();"),
                    class_name="rt-Button rt-r-size-3 rt-variant-soft",
                    style={"display": "none"},
                ),
                rx.el.button(
                    "Cancel",
                    on_click=rx.call_script(on_close),
                    class_name="rt-Button rt-r-size-3 rt-variant-soft rt-r-color-gray",
                ),
                style={
                    "marginTop": "0.85rem",
                    "display": "flex",
                    "gap": "0.5rem",
                    "alignItems": "stretch",
                },
            ),
            style={
                "background": "var(--gray-2)",
                "padding": "1.1rem",
                "borderRadius": "0.9rem",
                "border": "1px solid var(--gray-5)",
                "boxShadow": "0 12px 32px -8px rgba(0,0,0,0.5)",
                "maxWidth": "440px",
                "width": "100%",
                "boxSizing": "border-box",
            },
        ),
        id="barcode-dialog",
        style={
            "display": "none",
            "position": "fixed",
            "inset": "0",
            "zIndex": "9000",
            "background": "rgba(0,0,0,0.75)",
            "alignItems": "center",
            "justifyContent": "center",
            "padding": "1rem",
        },
    )


def inventory_capture_page() -> rx.Component:
    # JS shim: hands a successful barcode scan straight to the server via
    # /api/scan-product. The room comes from the currently-selected option
    # in the room <select> on the page (read directly from the DOM so we
    # don't need a round-trip into Reflex state).
    # wire_barcode moved to /scan-product.js (React doesn't run inline JS)
    return layout(
        rx.fragment(
            _barcode_dialog(),
            rx.vstack(
                # ---- Mode segmented slider ----
                rx.hstack(
                    rx.text(
                        "Mode:", weight="medium",
                        class_name="capture-row-label",
                    ),
                    rx.box(
                        rx.el.button(
                            rx.icon("package", size=14),
                            "Objects",
                            on_click=InventoryCaptureState.set_mode("objects"),
                            class_name=rx.cond(
                                InventoryCaptureState.mode == "objects",
                                "mode-seg-btn active",
                                "mode-seg-btn",
                            ),
                            type="button",
                        ),
                        rx.el.button(
                            rx.icon("receipt", size=14),
                            "Receipt",
                            on_click=InventoryCaptureState.set_mode("receipt"),
                            class_name=rx.cond(
                                InventoryCaptureState.mode == "receipt",
                                "mode-seg-btn active",
                                "mode-seg-btn",
                            ),
                            type="button",
                        ),
                        class_name="mode-seg",
                    ),
                    rx.text(
                        rx.cond(
                            InventoryCaptureState.mode == "receipt",
                            "Photo a paper receipt — line items will be extracted.",
                            "Photo of physical items — detector counts each kind.",
                        ),
                        size="1",
                        color_scheme="gray",
                        class_name="capture-row-hint",
                    ),
                    spacing="3",
                    align="center",
                    width="100%",
                    wrap="wrap",
                ),
                # ---- Room picker ----
                rx.hstack(
                    rx.text(
                        "Room:", weight="medium",
                        class_name="capture-row-label",
                    ),
                    rx.select(
                        InventoryCaptureState.room_options,
                        value=InventoryCaptureState.room,
                        on_change=InventoryCaptureState.set_room,
                        placeholder="Select a room",
                        size="3",
                        class_name="capture-room-select",
                    ),
                    spacing="3",
                    align="center",
                    width="100%",
                ),

            # ---- Camera button (in-page getUserMedia camera) ----
            # The system camera intent ("capture" attribute on a file
            # input) OOMs memory-tight Android PWAs the moment the
            # intent returns with a multi-megapixel photo. Instead we
            # use the browser's in-page camera: getUserMedia → live
            # preview overlay → canvas snapshot → POST. Everything
            # stays inside the WebView, the captured frame is
            # immediately re-encoded as a small JPEG, and memory
            # pressure stays low.
            rx.el.button(
                rx.box(
                    rx.icon("camera", size=22),
                    class_name="cap-btn-icon",
                ),
                rx.box(
                    rx.el.span("Take photo", class_name="cap-btn-label"),
                    rx.el.span(
                        "Open the camera",
                        class_name="cap-btn-sub",
                    ),
                    class_name="cap-btn-text",
                ),
                type="button",
                id="gyst-cam-btn",
                class_name="cap-btn cap-btn-primary",
                on_click=rx.call_script(
                    "window.gystCamera && window.gystCamera.openForCapture()"
                ),
            ),
            # ---- Pick from gallery (rx.upload → handle_upload via WS) ----
            # rx.upload routes the file through Reflex's own /_upload
            # pipeline, which calls InventoryCaptureState.handle_upload.
            # Each yield in that handler streams a state update over the
            # WS, so the photo + items populate underneath without a
            # page reload. The previous fetch-and-redirect path forced a
            # jarring full refresh after analysis.
            rx.upload(
                rx.box(
                    rx.icon("image", size=22),
                    class_name="cap-btn-icon",
                ),
                rx.box(
                    rx.el.span("Pick from gallery", class_name="cap-btn-label"),
                    rx.el.span(
                        "Choose an existing photo",
                        class_name="cap-btn-sub",
                    ),
                    class_name="cap-btn-text",
                ),
                id="cap-gallery-upload",
                accept={
                    "image/*": [".jpg", ".jpeg", ".png", ".heic", ".webp"]
                },
                multiple=False,
                no_drag=False,
                on_drop=InventoryCaptureState.handle_upload(
                    rx.upload_files("cap-gallery-upload")
                ),
                # Strip rx.upload's default dropzone styling — we want
                # the cap-btn look identical to Take photo / Scan barcode.
                border="0",
                padding="0",
                class_name="cap-btn cap-btn-secondary",
                custom_attrs={"aria-label": "Pick photo from gallery"},
            ),
            # ---- Scan barcode (same shape/treatment as the two above) ----
            # Opens the in-page barcode dialog; lookup chain + camera
            # snapshot + price-in-CAD all happen in barcode.js.
            rx.el.button(
                rx.box(
                    rx.icon("scan-barcode", size=22),
                    class_name="cap-btn-icon",
                ),
                rx.box(
                    rx.el.span("Scan barcode", class_name="cap-btn-label"),
                    rx.el.span(
                        "Identify by UPC / EAN / ISBN",
                        class_name="cap-btn-sub",
                    ),
                    class_name="cap-btn-text",
                ),
                type="button",
                id="gyst-scan-barcode-btn",
                class_name="cap-btn cap-btn-secondary",
                on_click=rx.call_script(
                    "window.gystBarcode && window.gystBarcode.open()"
                ),
                custom_attrs={"aria-label": "Open the barcode scanner"},
            ),
            # Status line — used by the in-page camera flow + camera-capture.js
            rx.el.div(
                "",
                id="capture-handoff-status",
                style={
                    "fontSize": "0.85rem",
                    "color": "var(--gray-11)",
                    "minHeight": "1.2rem",
                    "marginTop": "0.5rem",
                    "opacity": "0",
                    "transition": "opacity 0.2s ease",
                },
            ),
            # Preview of the just-captured photo. gyst-camera.js sets
            # src to a blob URL on capture so the user sees what they
            # shot while recognition runs. Hidden until populated.
            rx.el.img(
                id="capture-preview-img",
                alt="Captured photo",
                style={
                    "display": "none",
                    "width": "100%",
                    "maxHeight": "40vh",
                    "objectFit": "contain",
                    "borderRadius": "0.5rem",
                    "marginTop": "0.5rem",
                    "background": "var(--gray-3)",
                },
            ),
            rx.cond(
                InventoryCaptureState.in_progress,
                rx.card(
                    rx.vstack(
                        rx.hstack(
                            rx.spinner(size="3"),
                            rx.text(
                                InventoryCaptureState.status,
                                size="3",
                                weight="medium",
                            ),
                            spacing="3",
                            align="center",
                        ),
                        rx.progress(
                            value=InventoryCaptureState.progress, width="100%"
                        ),
                        spacing="3",
                        align="stretch",
                        width="100%",
                    ),
                    size="2",
                    width="100%",
                ),
                rx.fragment(),
            ),
            rx.cond(
                InventoryCaptureState.error,
                rx.callout(
                    InventoryCaptureState.error, icon="triangle_alert", color_scheme="red"
                ),
                rx.fragment(),
            ),
            rx.cond(
                InventoryCaptureState.saved_message,
                rx.callout(
                    InventoryCaptureState.saved_message,
                    icon="check",
                    color_scheme="green",
                ),
                rx.fragment(),
            ),
            rx.cond(
                InventoryCaptureState.grocery_matches,
                rx.box(
                    rx.el.details(
                        rx.el.summary(
                            rx.hstack(
                                rx.icon("check", size=16),
                                rx.text(
                                    "Auto-checked ",
                                    InventoryCaptureState.grocery_matches.length(),
                                    " item(s) from your grocery list",
                                    weight="bold", size="2",
                                ),
                                spacing="2", align="center",
                            ),
                        ),
                        rx.vstack(
                            rx.foreach(
                                InventoryCaptureState.grocery_matches,
                                lambda m: rx.hstack(
                                    rx.text(m["name"], size="2", flex="1"),
                                    rx.button(
                                        "Undo",
                                        on_click=InventoryCaptureState.undo_grocery_match(
                                            m["id"]
                                        ),
                                        variant="soft",
                                        size="1",
                                    ),
                                    width="100%", align="center", spacing="2",
                                ),
                            ),
                            spacing="1", align="stretch", width="100%",
                            margin_top="0.5em",
                        ),
                    ),
                    padding="0.75em",
                    background_color="var(--green-3)",
                    border_radius="0.5em",
                    width="100%",
                ),
                rx.fragment(),
            ),
            # Instant local preview: shown the moment the gallery file input
            # picks a file (set via FileReader → data: URL in the bound
            # script below). CSS class hides it by default; the script
            # sets src + adds .visible the moment a file is selected.
            # Hidden entirely once handle_upload has saved the photo
            # (then the real rx.image inside the has_photo block takes
            # over).
            rx.cond(
                InventoryCaptureState.photo_url == "",
                rx.el.img(
                    id="cap-instant-preview",
                    class_name="cap-instant-preview",
                    alt="Selected photo preview",
                ),
                rx.fragment(),
            ),
            # One-shot listener on the rx.upload's inner file input that
            # paints the instant preview the moment a file is chosen,
            # without waiting for the WS roundtrip. Uses FileReader for
            # max CSP compatibility (data: URLs are universally allowed).
            rx.script("""
                (function arm() {
                  var root = document.getElementById('cap-gallery-upload');
                  if (!root) { setTimeout(arm, 200); return; }
                  if (root.dataset.previewBound === '1') return;
                  root.dataset.previewBound = '1';
                  // Listen in capture phase so react-dropzone can't
                  // swallow the event before we see it.
                  root.addEventListener('change', function (e) {
                    var t = e.target;
                    if (!t || t.type !== 'file') return;
                    var f = t.files && t.files[0];
                    if (!f) return;
                    var prev = document.getElementById('cap-instant-preview');
                    if (!prev) return;
                    var reader = new FileReader();
                    reader.onload = function () {
                      prev.src = reader.result;
                      prev.classList.add('visible');
                    };
                    try { reader.readAsDataURL(f); } catch (_) {}
                  }, true);
                })();
            """),
            rx.cond(
                InventoryCaptureState.has_photo,
                rx.vstack(
                    rx.image(
                        src=InventoryCaptureState.photo_url,
                        width="100%",
                        max_width="600px",
                        border_radius="0.5em",
                    ),
                    rx.cond(
                        InventoryCaptureState.items,
                        rx.vstack(
                            rx.heading(
                                "Added ",
                                InventoryCaptureState.items.length(),
                                " item(s)",
                                size="4",
                            ),
                            rx.text(
                                "These are already in your inventory. Tap the "
                                "trash on any row to remove ones the AI got wrong.",
                                color_scheme="gray",
                                size="2",
                            ),
                            rx.foreach(
                                InventoryCaptureState.items, _saved_summary_row,
                            ),
                            spacing="3",
                            align="stretch",
                            width="100%",
                        ),
                        rx.fragment(),
                    ),
                    spacing="4",
                    align="stretch",
                    width="100%",
                ),
                rx.fragment(),
            ),
            spacing="4",
            align="stretch",
            width="100%",
            ),  # vstack
        ),  # rx.fragment
        title="Add items",
    )


# ---- Chores Tasks ------------------------------------------------------------
def _task_row(t) -> rx.Component:
    return rx.card(
        rx.hstack(
            rx.checkbox(
                checked=t["completed_bool"],
                on_change=ChoresTasksState.toggle_complete(t["id"]),
                size="3",
            ),
            rx.vstack(
                rx.heading(t["title"], size="4"),
                rx.cond(
                    t["description"],
                    rx.text(t["description"], color_scheme="gray", size="2"),
                    rx.fragment(),
                ),
                rx.hstack(
                    _person_chip(t["assignee_label"], t["assignee_color"]),
                    rx.cond(
                        t["due_display"],
                        rx.text(t["due_display"], size="2"),
                        rx.fragment(),
                    ),
                    rx.cond(
                        t["has_photo"],
                        rx.badge(
                            rx.icon("camera", size=12),
                            "proof attached",
                            color_scheme="green",
                            variant="soft",
                        ),
                        rx.fragment(),
                    ),
                    spacing="4",
                    align="center",
                    wrap="wrap",
                ),
                rx.cond(
                    t["has_photo"],
                    rx.image(
                        src=t["completion_photo_url"],
                        width="120px",
                        height="120px",
                        object_fit="cover",
                        border_radius="0.5em",
                    ),
                    rx.fragment(),
                ),
                spacing="2",
                align="start",
                flex="1",
            ),
            rx.vstack(
                rx.button(
                    rx.icon("pencil", size=14),
                    on_click=ChoresTasksState.open_task_edit(t["id"]),
                    variant="soft",
                    size="1",
                    title="Edit task",
                ),
                rx.button(
                    rx.icon("camera", size=14),
                    on_click=ChoresTasksState.start_photo(t["id"]),
                    variant="soft",
                    size="1",
                    title="Attach proof photo",
                ),
                rx.cond(
                    t["has_photo"],
                    rx.button(
                        rx.icon("image-off", size=14),
                        on_click=ChoresTasksState.clear_photo(t["id"]),
                        variant="soft",
                        color_scheme="gray",
                        size="1",
                        title="Remove proof photo",
                    ),
                    rx.fragment(),
                ),
                rx.button(
                    rx.icon("trash-2", size=14),
                    on_click=ChoresTasksState.delete_task(t["id"]),
                    color_scheme="red",
                    variant="soft",
                    size="1",
                    aria_label='Delete task',
                ),
                spacing="1",
                align="end",
            ),
            spacing="3",
            align="start",
            width="100%",
        ),
        size="2",
        width="100%",
    )


def _task_edit_dialog() -> rx.Component:
    """Full edit dialog — title, notes, assignee re-assignment, due date."""
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Edit task"),
            rx.vstack(
                rx.text("Title", size="2", weight="bold"),
                rx.input(
                    value=ChoresTasksState.editing_task_title,
                    on_change=ChoresTasksState.set_editing_task_title,
                    size="3",
                ),
                rx.text("Notes", size="2", weight="bold"),
                rx.text_area(
                    value=ChoresTasksState.editing_task_description,
                    on_change=ChoresTasksState.set_editing_task_description,
                    size="3",
                ),
                rx.text("Assignee", size="2", weight="bold"),
                rx.select(
                    ChoresTasksState.assignee_options,
                    value=ChoresTasksState.editing_task_assignee_name,
                    on_change=ChoresTasksState.set_editing_task_assignee,
                    size="3",
                ),
                rx.hstack(
                    rx.checkbox(
                        "Has a due date",
                        checked=ChoresTasksState.editing_task_has_due,
                        on_change=ChoresTasksState.set_editing_task_has_due,
                    ),
                    rx.cond(
                        ChoresTasksState.editing_task_has_due,
                        rx.input(
                            type="date",
                            value=ChoresTasksState.editing_task_due_date,
                            on_change=ChoresTasksState.set_editing_task_due_date,
                            size="3",
                        ),
                        rx.fragment(),
                    ),
                    spacing="3",
                    align="center",
                ),
                rx.cond(
                    ChoresTasksState.edit_task_error,
                    rx.callout(
                        ChoresTasksState.edit_task_error,
                        icon="triangle_alert",
                        color_scheme="red",
                    ),
                    rx.fragment(),
                ),
                rx.divider(margin_y="0.5em"),
                rx.hstack(
                    rx.button(
                        "Cancel",
                        on_click=ChoresTasksState.close_task_edit,
                        variant="soft",
                        color_scheme="gray",
                        flex="1",
                    ),
                    rx.button(
                        "Save",
                        on_click=ChoresTasksState.save_task_edit,
                        flex="1",
                    ),
                    spacing="2",
                    width="100%",
                ),
                spacing="3",
                align="stretch",
                width="100%",
            ),
            max_width="500px",
        ),
        open=ChoresTasksState.editing_task_id != 0,
        on_open_change=ChoresTasksState.handle_task_edit_open_change,
    )


def _chore_photo_upload_card() -> rx.Component:
    """Top-of-page card visible only when a task is targeted for a photo."""
    return rx.cond(
        ChoresTasksState.photo_target_task_id != 0,
        rx.card(
            rx.vstack(
                rx.hstack(
                    rx.icon("camera", size=20),
                    rx.text(
                        "Attaching proof photo for: ",
                        rx.text.strong(ChoresTasksState.photo_target_title),
                    ),
                    rx.spacer(),
                    rx.button(
                        "Cancel",
                        on_click=ChoresTasksState.cancel_photo,
                        variant="soft",
                        color_scheme="gray",
                        size="2",
                    ),
                    align="center",
                    width="100%",
                ),
                rx.upload(
                    rx.vstack(
                        rx.icon("camera", size=24),
                        rx.text(
                            "Tap to take a photo or pick from library",
                            size="2",
                            weight="medium",
                        ),
                        align="center",
                        spacing="2",
                    ),
                    id="chore_proof_upload",
                    accept={
                        "image/*": [".jpg", ".jpeg", ".png", ".heic", ".webp"]
                    },
                    multiple=False,
                    on_drop=ChoresTasksState.handle_photo_upload(
                        rx.upload_files("chore_proof_upload")
                    ),
                    border="2px dashed",
                    border_color=rx.color("gray", 6),
                    padding="1.5em",
                    border_radius="0.75em",
                    width="100%",
                ),
                rx.cond(
                    ChoresTasksState.photo_uploading,
                    rx.callout(
                        "Uploading…", icon="upload", color_scheme="gray"
                    ),
                    rx.fragment(),
                ),
                rx.cond(
                    ChoresTasksState.photo_error,
                    rx.callout(
                        ChoresTasksState.photo_error,
                        icon="triangle_alert",
                        color_scheme="red",
                    ),
                    rx.fragment(),
                ),
                spacing="3",
                align="stretch",
                width="100%",
            ),
            size="2",
            width="100%",
        ),
        rx.fragment(),
    )


def chores_tasks_page() -> rx.Component:
    return layout(
        rx.fragment(
            _task_edit_dialog(),
            rx.vstack(
                _chore_photo_upload_card(),
                rx.select(
                    ChoresTasksState.filter_options,
                    value=ChoresTasksState.filter_value,
                    on_change=ChoresTasksState.set_filter,
                    size="3",
                ),
                rx.cond(
                    ChoresTasksState.tasks,
                    rx.foreach(ChoresTasksState.tasks, _task_row),
                    _empty_cta("list-checks", "No tasks. Add one.", "Add task", "/chores/add"),
                ),
                spacing="4",
                align="stretch",
                width="100%",
            ),
        ),
        title="Tasks",
    )


# ---- Chores Add Task ---------------------------------------------------------
def chores_add_page() -> rx.Component:
    return layout(
        rx.vstack(
            rx.vstack(
                rx.text("Quick pick", size="1", weight="bold", color_scheme="gray"),
                rx.select(
                    ChoresAddState.template_options,
                    value=ChoresAddState.template,
                    on_change=ChoresAddState.set_template,
                    size="3",
                    width="100%",
                ),
                spacing="1",
                align="stretch",
                width="100%",
            ),
            rx.vstack(
                rx.text("Title", size="1", weight="bold"),
                rx.input(
                    placeholder="Title (e.g. take out the trash)",
                    value=ChoresAddState.title,
                    on_change=ChoresAddState.set_title,
                    size="3",
                    width="100%",
                    aria_label="Task title",
                ),
                spacing="1", align="stretch", width="100%",
            ),
            rx.vstack(
                rx.text("Notes", size="1", weight="bold"),
                rx.text_area(
                    placeholder="Notes (optional)",
                    value=ChoresAddState.description,
                    on_change=ChoresAddState.set_description,
                    size="3",
                    width="100%",
                    aria_label="Task notes",
                ),
                spacing="1", align="stretch", width="100%",
            ),
            rx.hstack(
                rx.text("Assign to:", weight="medium"),
                rx.select(
                    ChoresAddState.assignee_options,
                    value=ChoresAddState.assignee_name,
                    on_change=ChoresAddState.set_assignee,
                    size="3",
                ),
                spacing="3",
                align="center",
            ),
            rx.hstack(
                rx.checkbox(
                    "Has a due date",
                    checked=ChoresAddState.has_due,
                    on_change=ChoresAddState.set_has_due,
                ),
                rx.cond(
                    ChoresAddState.has_due,
                    rx.input(
                        type="date",
                        value=ChoresAddState.due_date,
                        on_change=ChoresAddState.set_due_date,
                    ),
                    rx.fragment(),
                ),
                spacing="3",
                align="center",
            ),
            rx.hstack(
                rx.icon("repeat", size=14),
                rx.text("Repeats:", weight="medium"),
                rx.select(
                    ChoresAddState.recurrence_options,
                    value=ChoresAddState.recurrence_label,
                    on_change=ChoresAddState.set_recurrence_label,
                    size="3",
                ),
                spacing="2",
                align="center",
            ),
            rx.button(
                "Add task",
                on_click=ChoresAddState.submit,
                size="3",
                width="100%",
            ),
            spacing="4",
            align="stretch",
            width="100%",
            max_width="600px",
        ),
        title="Add task",
    )


# ---- Chores People -----------------------------------------------------------
def _person_row(p) -> rx.Component:
    return rx.card(
        rx.hstack(
            rx.box(
                width="14px",
                height="14px",
                border_radius="50%",
                background_color=p["color"],
                flex_shrink="0",
            ),
            rx.vstack(
                rx.heading(p["name"], size="4"),
                rx.text(
                    p["task_count"],
                    " task(s) assigned · added ",
                    p["created_at"],
                    size="1",
                    color_scheme="gray",
                ),
                spacing="1",
                align="start",
                flex="1",
            ),
            rx.button(
                "Delete",
                on_click=ChoresPeopleState.delete_person(p["id"]),
                color_scheme="red",
                variant="soft",
                size="2",
            ),
            spacing="3",
            align="center",
            width="100%",
        ),
        size="2",
        width="100%",
    )


def chores_people_page() -> rx.Component:
    return layout(
        rx.vstack(
            rx.cond(
                ChoresPeopleState.people,
                rx.vstack(
                    rx.foreach(ChoresPeopleState.people, _person_row),
                    spacing="3",
                    align="stretch",
                    width="100%",
                ),
                _empty("No household members yet. Add one below."),
            ),
            rx.divider(margin_y="1em"),
            rx.heading("Add a person", size="4"),
            rx.input(
                placeholder="Name",
                value=ChoresPeopleState.new_name,
                on_change=ChoresPeopleState.set_new_name,
                size="3",
                width="100%",
            ),
            rx.hstack(
                rx.text("Color:", weight="medium"),
                rx.select(
                    ChoresPeopleState.color_options,
                    value=ChoresPeopleState.new_color,
                    on_change=ChoresPeopleState.set_new_color,
                    size="3",
                ),
                spacing="3",
                align="center",
            ),
            rx.button(
                "Add",
                on_click=ChoresPeopleState.add_person,
                size="3",
                width="100%",
            ),
            rx.cond(
                ChoresPeopleState.error,
                rx.callout(
                    ChoresPeopleState.error,
                    icon="triangle_alert",
                    color_scheme="red",
                ),
                rx.fragment(),
            ),
            spacing="4",
            align="stretch",
            width="100%",
            max_width="600px",
        ),
        title="👥 People",
    )


# ---- Settings ----------------------------------------------------------------
def _user_avatar(u) -> rx.Component:
    """Initial-letter circle. Background is the deterministic per-user color
    so chore-assignment chips stay consistent across the app."""
    return rx.box(
        rx.text(u["initial"], class_name="user-avatar-letter"),
        style={"background_color": u["color"]},
        class_name="user-avatar",
    )


def _user_row(u) -> rx.Component:
    return rx.box(
        rx.hstack(
            _user_avatar(u),
            rx.vstack(
                rx.hstack(
                    rx.text(u["name"], class_name="user-card-name"),
                    rx.cond(
                        u["is_admin_bool"],
                        rx.badge(
                            rx.icon("shield", size=11),
                            "Admin",
                            color_scheme="indigo",
                            variant="soft",
                        ),
                        rx.fragment(),
                    ),
                    rx.cond(
                        u["has_username"],
                        rx.fragment(),
                        rx.badge(
                            "No login", color_scheme="amber", variant="soft",
                        ),
                    ),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                rx.hstack(
                    rx.cond(
                        u["username"],
                        rx.hstack(
                            rx.icon("at-sign", size=12),
                            rx.text(u["username"], size="1"),
                            spacing="1", align="center",
                        ),
                        rx.fragment(),
                    ),
                    rx.cond(
                        u["email"],
                        rx.hstack(
                            rx.icon("mail", size=12),
                            rx.text(u["email"], size="1"),
                            spacing="1", align="center",
                        ),
                        rx.fragment(),
                    ),
                    rx.hstack(
                        rx.icon("list-checks", size=12),
                        rx.text(u["task_count"], " tasks", size="1"),
                        spacing="1", align="center",
                    ),
                    spacing="3",
                    align="center",
                    wrap="wrap",
                    class_name="user-card-meta",
                ),
                spacing="1",
                align="start",
                flex="1",
                min_width="0",
            ),
            rx.icon_button(
                rx.icon("pencil", size=15),
                on_click=SettingsState.open_manage(u["id"]),
                variant="soft",
                size="2",
                title="Edit user",
                aria_label='Edit user',
            ),
            rx.icon_button(
                rx.icon("trash-2", size=15),
                on_click=SettingsState.delete_user(u["id"]),
                color_scheme="red",
                variant="soft",
                size="2",
                title="Delete user",
                aria_label='Delete user',
            ),
            spacing="3",
            align="center",
            width="100%",
        ),
        class_name="user-card",
    )


def _manage_section_header(title: str, hint: str) -> rx.Component:
    return rx.vstack(
        rx.text(title, class_name="manage-section-title"),
        rx.text(hint, size="1", color_scheme="gray"),
        spacing="0",
        align="start",
        width="100%",
    )


def _manage_perm_toggle(label: str, hint: str, checked, on_change) -> rx.Component:
    """One row in the Permissions section — title + hint on the left,
    switch on the right."""
    return rx.hstack(
        rx.vstack(
            rx.text(label, weight="medium", size="2"),
            rx.text(hint, size="1", color_scheme="gray"),
            spacing="0",
            align="start",
            min_width="0",
            flex="1",
        ),
        rx.switch(checked=checked, on_change=on_change, size="2"),
        spacing="3",
        align="center",
        width="100%",
        class_name="manage-perm-row",
    )


def _manage_user_dialog() -> rx.Component:
    """Modern three-section dialog: Profile / Credentials / Permissions.
    Each section has its own Save button — change one without retyping
    the other two."""
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(
                rx.hstack(
                    rx.text("Edit", size="3", color_scheme="gray"),
                    rx.text(
                        SettingsState.managing_user_name,
                        weight="bold",
                        size="6",
                    ),
                    spacing="2",
                    align="baseline",
                ),
            ),
            rx.vstack(
                # ---- Profile section ----
                rx.box(
                    rx.vstack(
                        _manage_section_header(
                            "Profile",
                            "Display name shown across the app. Email is optional.",
                        ),
                        rx.input(
                            placeholder="Display name",
                            value=SettingsState.managing_name,
                            on_change=SettingsState.set_managing_name,
                            size="3",
                            width="100%",
                        ),
                        rx.input(
                            placeholder="Email (optional)",
                            value=SettingsState.managing_email,
                            on_change=SettingsState.set_managing_email,
                            size="3",
                            width="100%",
                        ),
                        _manage_perm_toggle(
                            "Admin",
                            "Can access Settings and manage users.",
                            SettingsState.managing_is_admin,
                            SettingsState.set_managing_is_admin,
                        ),
                        rx.button(
                            "Save profile",
                            on_click=SettingsState.save_profile,
                            size="2",
                        ),
                        spacing="3",
                        align="stretch",
                        width="100%",
                    ),
                    class_name="manage-section",
                ),

                # ---- Credentials section ----
                rx.box(
                    rx.vstack(
                        _manage_section_header(
                            "Sign-in credentials",
                            rx.cond(
                                SettingsState.managing_has_username,
                                "Username is set. Change it or rotate the "
                                "password below. Leave password blank to "
                                "keep the current one.",
                                "No credentials yet — set them so this user "
                                "can sign in.",
                            ),
                        ),
                        rx.input(
                            placeholder="Username (case-insensitive)",
                            value=SettingsState.managing_username,
                            on_change=SettingsState.set_managing_username,
                            size="3",
                            width="100%",
                        ),
                        rx.input(
                            placeholder="New password (leave blank to keep)",
                            type="password",
                            value=SettingsState.managing_password,
                            on_change=SettingsState.set_managing_password,
                            size="3",
                            width="100%",
                        ),
                        rx.input(
                            placeholder="Confirm new password",
                            type="password",
                            value=SettingsState.managing_password_confirm,
                            on_change=SettingsState.set_managing_password_confirm,
                            size="3",
                            width="100%",
                        ),
                        rx.button(
                            "Save credentials",
                            on_click=SettingsState.save_credentials,
                            size="2",
                        ),
                        spacing="3",
                        align="stretch",
                        width="100%",
                    ),
                    class_name="manage-section",
                ),

                # ---- Permissions section ----
                rx.box(
                    rx.vstack(
                        _manage_section_header(
                            "Permissions",
                            "Read controls page visibility; write controls "
                            "edits and deletes.",
                        ),
                        _manage_perm_toggle(
                            "Inventory · read",
                            "See inventory items, search, browse.",
                            SettingsState.managing_can_read_inventory,
                            SettingsState.set_managing_can_read_inventory,
                        ),
                        _manage_perm_toggle(
                            "Inventory · write",
                            "Capture, edit, delete, mark for sale.",
                            SettingsState.managing_can_write_inventory,
                            SettingsState.set_managing_can_write_inventory,
                        ),
                        _manage_perm_toggle(
                            "Chores · read",
                            "See the task list.",
                            SettingsState.managing_can_read_chores,
                            SettingsState.set_managing_can_read_chores,
                        ),
                        _manage_perm_toggle(
                            "Chores · write",
                            "Create, assign, complete, delete tasks.",
                            SettingsState.managing_can_write_chores,
                            SettingsState.set_managing_can_write_chores,
                        ),
                        rx.button(
                            "Save permissions",
                            on_click=SettingsState.save_permissions,
                            size="2",
                        ),
                        spacing="3",
                        align="stretch",
                        width="100%",
                    ),
                    class_name="manage-section",
                ),

                # ---- Feedback + close ----
                rx.cond(
                    SettingsState.manage_error,
                    rx.callout(
                        SettingsState.manage_error,
                        icon="triangle_alert",
                        color_scheme="red",
                    ),
                    rx.fragment(),
                ),
                rx.cond(
                    SettingsState.manage_success,
                    rx.callout(
                        SettingsState.manage_success,
                        icon="check",
                        color_scheme="green",
                    ),
                    rx.fragment(),
                ),
                rx.button(
                    "Done",
                    on_click=SettingsState.close_manage,
                    variant="soft",
                    color_scheme="gray",
                    size="3",
                    width="100%",
                ),
                spacing="4",
                align="stretch",
                width="100%",
            ),
            max_width="560px",
        ),
        open=SettingsState.managing_user_id != 0,
        on_open_change=SettingsState.handle_manage_open_change,
    )


def _settings_users_tab() -> rx.Component:
    return rx.vstack(
        # ---- Existing users list ----
        rx.hstack(
            rx.heading("Household members", size="5"),
            rx.spacer(),
            rx.badge(
                SettingsState.users.length(),
                color_scheme="gray",
                variant="soft",
                size="2",
            ),
            align="center",
            width="100%",
        ),
        rx.cond(
            SettingsState.users,
            rx.vstack(
                rx.foreach(SettingsState.users, _user_row),
                spacing="2",
                align="stretch",
                width="100%",
            ),
            _empty("No household members yet. Add one below."),
        ),

        rx.divider(margin_y="1.25em"),

        # ---- Add user ----
        rx.box(
            rx.vstack(
                rx.hstack(
                    rx.icon("user-plus", size=16),
                    rx.text(
                        "Add a household member",
                        weight="bold",
                        size="3",
                    ),
                    spacing="2",
                    align="center",
                ),
                rx.text(
                    "Just the name to start — you can set credentials and "
                    "permissions afterwards from their card.",
                    size="1",
                    color_scheme="gray",
                ),
                rx.input(
                    placeholder="Display name (e.g. Alex)",
                    value=SettingsState.new_user_name,
                    on_change=SettingsState.set_new_user_name,
                    size="3",
                    width="100%",
                ),
                rx.input(
                    placeholder="Email (optional)",
                    value=SettingsState.new_user_email,
                    on_change=SettingsState.set_new_user_email,
                    size="3",
                    width="100%",
                ),
                rx.hstack(
                    rx.switch(
                        checked=SettingsState.new_user_admin,
                        on_change=SettingsState.set_new_user_admin,
                        size="2",
                    ),
                    rx.text("Grant admin (can manage settings)", size="2"),
                    spacing="3",
                    align="center",
                ),
                rx.button(
                    rx.icon("circle-plus", size=14),
                    "Add user",
                    on_click=SettingsState.add_user,
                    size="3",
                ),
                rx.cond(
                    SettingsState.user_error,
                    rx.callout(
                        SettingsState.user_error,
                        icon="triangle_alert",
                        color_scheme="red",
                    ),
                    rx.fragment(),
                ),
                spacing="3",
                align="stretch",
            ),
            class_name="add-user-card",
        ),
        spacing="3",
        align="stretch",
        width="100%",
        max_width="640px",
    )


def _room_row(r) -> rx.Component:
    return rx.card(
        rx.hstack(
            rx.text(r["name"], weight="medium", size="3", flex="1"),
            rx.icon_button(
                rx.icon("arrow-up", size=16),
                on_click=SettingsState.move_room_up(r["id"]),
                variant="soft",
                size="1",
                aria_label='Move room up',
            ),
            rx.icon_button(
                rx.icon("arrow-down", size=16),
                on_click=SettingsState.move_room_down(r["id"]),
                variant="soft",
                size="1",
                aria_label='Move room down',
            ),
            rx.button(
                "Delete",
                on_click=SettingsState.delete_room(r["id"]),
                color_scheme="red",
                variant="soft",
                size="2",
            ),
            spacing="2",
            align="center",
            width="100%",
        ),
        size="2",
        width="100%",
    )


def _settings_rooms_tab() -> rx.Component:
    return rx.vstack(
        rx.text(
            "Rooms appear in the dropdowns on Capture and Browse. "
            "Reordering changes the dropdown order.",
            color_scheme="gray",
            size="2",
        ),
        rx.cond(
            SettingsState.rooms,
            rx.vstack(
                rx.foreach(SettingsState.rooms, _room_row),
                spacing="2",
                align="stretch",
                width="100%",
            ),
            _empty("No rooms yet. Add one below."),
        ),
        rx.divider(margin_y="1em"),
        rx.heading("Add room", size="4"),
        rx.input(
            placeholder="e.g. mudroom, workshop, kid's bedroom",
            value=SettingsState.new_room_name,
            on_change=SettingsState.set_new_room_name,
            size="3",
            width="100%",
        ),
        rx.button(
            "Add room",
            on_click=SettingsState.add_room,
            size="3",
            width="100%",
        ),
        rx.cond(
            SettingsState.room_error,
            rx.callout(
                SettingsState.room_error,
                icon="triangle_alert",
                color_scheme="red",
            ),
            rx.fragment(),
        ),
        spacing="3",
        align="stretch",
        width="100%",
        max_width="600px",
    )


def _settings_api_tab() -> rx.Component:
    """Pick LLM provider + manage API keys. Keys are write-only — once saved,
    only their 'configured' status is shown. The plaintext is never returned
    to the client."""
    return rx.vstack(
        rx.callout(
            "API keys are stored encrypted at rest. After saving, the key "
            "value is never displayed again — only its 'configured' status.",
            icon="lock",
            color_scheme="gray",
        ),
        rx.heading("Provider", size="4"),
        rx.select(
            SettingsState.api_provider_options,
            value=SettingsState.api_provider,
            on_change=SettingsState.set_api_provider,
            size="3",
        ),
        rx.divider(margin_y="0.5em"),
        rx.heading("Anthropic (Claude)", size="4"),
        rx.cond(
            SettingsState.anthropic_key_set,
            rx.hstack(
                rx.badge(
                    "Configured", color_scheme="green", variant="soft"
                ),
                rx.button(
                    "Clear key",
                    on_click=SettingsState.clear_anthropic_key,
                    variant="soft",
                    color_scheme="red",
                    size="2",
                ),
                spacing="3",
                align="center",
            ),
            rx.badge("Not configured", color_scheme="gray", variant="soft"),
        ),
        rx.input(
            placeholder="Enter new Anthropic API key (sk-ant-…)",
            type="password",
            value=SettingsState.anthropic_key_input,
            on_change=SettingsState.set_anthropic_key_input,
            size="3",
        ),
        rx.input(
            placeholder="Claude model (default: claude-opus-4-7)",
            value=SettingsState.claude_model,
            on_change=SettingsState.set_claude_model,
            size="3",
        ),
        rx.divider(margin_y="0.5em"),
        rx.heading("OpenAI", size="4"),
        rx.cond(
            SettingsState.openai_key_set,
            rx.hstack(
                rx.badge(
                    "Configured", color_scheme="green", variant="soft"
                ),
                rx.button(
                    "Clear key",
                    on_click=SettingsState.clear_openai_key,
                    variant="soft",
                    color_scheme="red",
                    size="2",
                ),
                spacing="3",
                align="center",
            ),
            rx.badge("Not configured", color_scheme="gray", variant="soft"),
        ),
        rx.input(
            placeholder="Enter new OpenAI API key (sk-…)",
            type="password",
            value=SettingsState.openai_key_input,
            on_change=SettingsState.set_openai_key_input,
            size="3",
        ),
        rx.input(
            placeholder="OpenAI model (default: gpt-4o)",
            value=SettingsState.openai_model,
            on_change=SettingsState.set_openai_model,
            size="3",
        ),
        rx.divider(margin_y="0.5em"),
        rx.heading("Object detector (OWL-ViT)", size="4"),
        rx.text(
            "When enabled, the local detector counts each item type after the "
            "LLM identifies them. First run downloads ~700 MB and can take a "
            "while on CPU — turn this off to use LLM-reported quantities only "
            "if capture stalls at 'Counting instances…'.",
            size="2",
            color_scheme="gray",
        ),
        rx.hstack(
            rx.switch(
                checked=SettingsState.enable_detector,
                on_change=SettingsState.set_enable_detector,
                size="2",
            ),
            rx.text(
                rx.cond(
                    SettingsState.enable_detector, "Enabled", "Disabled"
                ),
                size="2",
            ),
            spacing="3",
            align="center",
        ),
        rx.divider(margin_y="0.5em"),
        rx.button(
            "Save",
            on_click=SettingsState.save_api_settings,
            size="3",
            width="100%",
        ),
        rx.cond(
            SettingsState.api_message,
            rx.callout(
                SettingsState.api_message, icon="check", color_scheme="green"
            ),
            rx.fragment(),
        ),
        rx.cond(
            SettingsState.api_error,
            rx.callout(
                SettingsState.api_error,
                icon="triangle_alert",
                color_scheme="red",
            ),
            rx.fragment(),
        ),
        spacing="3",
        align="stretch",
        width="100%",
        max_width="600px",
    )


def _audit_row(a) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.text(a["created_at"], size="1", color_scheme="gray",
                    min_width="160px", class_name="audit-ts"),
            rx.badge(a["action"], color_scheme="indigo", variant="soft"),
            rx.text(a["actor_name"], size="2", weight="medium"),
            rx.cond(
                a["target"],
                rx.text("→ ", a["target"], size="2", color_scheme="gray"),
                rx.fragment(),
            ),
            rx.cond(
                a["ip"],
                rx.badge(a["ip"], color_scheme="gray", variant="surface"),
                rx.fragment(),
            ),
            rx.spacer(),
            rx.cond(
                a["detail"],
                rx.text(a["detail"], size="1", color_scheme="gray"),
                rx.fragment(),
            ),
            spacing="3",
            align="center",
            width="100%",
            wrap="wrap",
        ),
        class_name="audit-row",
    )


def _settings_audit_tab() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.heading("Audit log", size="5"),
            rx.spacer(),
            rx.badge(
                SettingsState.audit_rows.length(),
                color_scheme="gray", variant="soft", size="2",
            ),
            rx.icon_button(
                rx.icon("refresh-cw", size=15),
                on_click=SettingsState.refresh_audit,
                variant="soft", size="2",
                title="Refresh",
                aria_label='Refresh audit log',
            ),
            align="center",
            width="100%",
        ),
        rx.text(
            "Most recent 200 admin / security events. Read-only.",
            size="2",
            color_scheme="gray",
        ),
        rx.cond(
            SettingsState.audit_rows,
            rx.vstack(
                rx.foreach(SettingsState.audit_rows, _audit_row),
                spacing="1",
                align="stretch",
                width="100%",
            ),
            _empty("Nothing logged yet."),
        ),
        spacing="3",
        align="stretch",
        width="100%",
        max_width="900px",
    )


def _settings_push_section() -> rx.Component:
    """Push notification controls. The actual subscribe/unsubscribe work is
    100% client-side fetch calls into /push/* — we just render the buttons
    and let pwa-register.js do the talking."""
    on_enable = """
        const setStatus = (m) => {
            const s = document.getElementById('push-status');
            if (s) s.textContent = m;
        };
        try {
            await window.gystPush.subscribe();
            setStatus('Enabled on this device.');
        } catch (e) { setStatus('Could not enable push: ' + e.message); }
    """
    on_disable = """
        const setStatus = (m) => {
            const s = document.getElementById('push-status');
            if (s) s.textContent = m;
        };
        try {
            await window.gystPush.unsubscribe();
            setStatus('Disabled on this device.');
        } catch (e) { setStatus('Could not disable: ' + e.message); }
    """
    on_test = """
        const setStatus = (m) => {
            const s = document.getElementById('push-status');
            if (s) s.textContent = m;
        };
        try {
            const r = await window.gystPush.sendTest();
            setStatus('Test sent — delivered ' + r.sent + ', failed ' + r.failed);
        } catch (e) { setStatus('Could not send test: ' + e.message); }
    """
    return rx.vstack(
        rx.heading("Notifications", size="4"),
        rx.text(
            "Enable push notifications on this device. Each device "
            "(phone, browser) subscribes separately. You'll get a "
            "permission prompt the first time.",
            size="2",
            color_scheme="gray",
        ),
        rx.hstack(
            rx.el.button(
                "Enable on this device",
                on_click=rx.call_script(on_enable),
                class_name="rt-Button rt-r-size-2 rt-variant-soft",
            ),
            rx.el.button(
                "Disable",
                on_click=rx.call_script(on_disable),
                class_name="rt-Button rt-r-size-2 rt-variant-soft rt-r-color-gray",
            ),
            rx.el.button(
                "Send test",
                on_click=rx.call_script(on_test),
                class_name="rt-Button rt-r-size-2 rt-variant-soft rt-r-color-indigo",
            ),
            spacing="2",
            wrap="wrap",
        ),
        rx.text("", id="push-status", size="1", color_scheme="gray"),
        spacing="2",
        align="stretch",
    )


def _settings_ical_section() -> rx.Component:
    """Show + rotate the per-user iCal subscription URL. Phones subscribe to
    this URL in their native calendar app and GYST events appear alongside
    work / personal calendars without needing the app."""
    return rx.vstack(
        rx.heading("Calendar subscription (iCal)", size="4"),
        rx.text(
            "Add this URL to iPhone Calendar (Subscribed Calendars), "
            "Google Calendar (Add by URL), or Thunderbird to see your "
            "GYST tasks, meals, and appointments natively. The URL is "
            "tied to your account — don't share it.",
            size="2",
            color_scheme="gray",
        ),
        rx.hstack(
            rx.button(
                rx.icon("calendar", size=14),
                "Reveal URL",
                on_click=SettingsState.show_ical_url,
                size="2",
                variant="soft",
            ),
            rx.button(
                rx.icon("refresh-cw", size=14),
                "Rotate token",
                on_click=SettingsState.rotate_ical,
                size="2",
                variant="soft",
                color_scheme="amber",
            ),
            spacing="2",
            align="center",
        ),
        rx.cond(
            SettingsState.ical_url,
            rx.box(
                rx.code(SettingsState.ical_url),
                class_name="ical-url-box",
            ),
            rx.fragment(),
        ),
        spacing="2",
        align="stretch",
    )



def _settings_locale_section() -> rx.Component:
    """Currency + time-zone selects. Lives in the Appearance tab.
    Changes persist immediately to app_settings and take effect on
    the next render of any price or the home greeting."""
    return rx.box(
        rx.heading("Locale", size="3"),
        rx.text(
            "Pick how prices render across the app and what time zone "
            "the home greeting uses.",
            size="1", color_scheme="gray",
        ),
        rx.hstack(
            rx.vstack(
                rx.text("Currency", size="1", weight="bold"),
                rx.select(
                    [
                        "CAD", "USD", "EUR", "GBP", "AUD", "NZD",
                        "JPY", "CHF", "MXN", "BRL", "INR", "CNY",
                        "SEK", "NOK", "DKK", "ZAR",
                    ],
                    value=SettingsState.current_currency,
                    on_change=SettingsState.set_locale_currency,
                    size="2",
                ),
                spacing="1", align="start",
            ),
            rx.vstack(
                rx.text("Time zone", size="1", weight="bold"),
                rx.select(
                    [
                        "America/Halifax",
                        "America/St_Johns",
                        "America/Toronto",
                        "America/New_York",
                        "America/Chicago",
                        "America/Denver",
                        "America/Los_Angeles",
                        "America/Anchorage",
                        "America/Phoenix",
                        "America/Mexico_City",
                        "America/Sao_Paulo",
                        "Europe/London",
                        "Europe/Paris",
                        "Europe/Berlin",
                        "Europe/Athens",
                        "Africa/Johannesburg",
                        "Asia/Dubai",
                        "Asia/Kolkata",
                        "Asia/Singapore",
                        "Asia/Tokyo",
                        "Australia/Sydney",
                        "Pacific/Auckland",
                        "UTC",
                    ],
                    value=SettingsState.current_timezone,
                    on_change=SettingsState.set_locale_timezone,
                    size="2",
                ),
                spacing="1", align="start",
            ),
            spacing="3", wrap="wrap", align="start",
        ),
        rx.divider(margin_y="0.5em"),
        spacing="2", align="stretch", width="100%",
    )

def _settings_appearance_tab() -> rx.Component:
    return rx.vstack(
        _settings_locale_section(),
        rx.heading("Appearance", size="4"),
        rx.text(
            "Choose how the interface looks. 'System' follows your "
            "device's light/dark preference.",
            size="2",
            color_scheme="gray",
        ),
        rx.hstack(
            rx.button(
                rx.icon("sun", size=14),
                "Light",
                on_click=set_color_mode("light"),
                variant=rx.cond(
                    rx.color_mode == "light", "solid", "soft"
                ),
                size="3",
            ),
            rx.button(
                rx.icon("moon", size=14),
                "Dark",
                on_click=set_color_mode("dark"),
                variant=rx.cond(
                    rx.color_mode == "dark", "solid", "soft"
                ),
                size="3",
            ),
            rx.button(
                rx.icon("monitor", size=14),
                "System",
                on_click=set_color_mode("system"),
                variant=rx.cond(
                    rx.color_mode == "system", "solid", "soft"
                ),
                size="3",
            ),
            spacing="2",
            wrap="wrap",
        ),
        rx.text(
            rx.cond(
                rx.color_mode == "light",
                "Current: Light",
                rx.cond(
                    rx.color_mode == "dark",
                    "Current: Dark",
                    "Current: System",
                ),
            ),
            size="1",
            color_scheme="gray",
        ),
        spacing="3",
        align="stretch",
        width="100%",
        max_width="600px",
    )


def _settings_notifications_tab() -> rx.Component:
    return rx.vstack(
        _settings_push_section(),
        spacing="3",
        align="stretch",
        width="100%",
        max_width="600px",
    )


def _settings_sync_tab() -> rx.Component:
    return rx.vstack(
        _settings_ical_section(),
        spacing="3",
        align="stretch",
        width="100%",
        max_width="600px",
    )


def settings_page() -> rx.Component:
    return layout(
        rx.fragment(
            rx.tabs.root(
                rx.tabs.list(
                    rx.tabs.trigger("Users", value="users"),
                    rx.tabs.trigger("Rooms", value="rooms"),
                    rx.tabs.trigger("Announcements", value="announcements"),
                    rx.tabs.trigger("API", value="api"),
                    rx.tabs.trigger("Audit", value="audit"),
                    rx.tabs.trigger("Appearance", value="appearance"),
                    rx.tabs.trigger("Notifications", value="notifications"),
                    rx.tabs.trigger("Sync", value="sync"),
                    overflow_x="auto",
                    flex_wrap="nowrap",
                ),
                rx.tabs.content(
                    _settings_users_tab(), value="users", padding_top="1.5em"
                ),
                rx.tabs.content(
                    _settings_rooms_tab(), value="rooms", padding_top="1.5em"
                ),
                rx.tabs.content(
                    _settings_announcements_tab(),
                    value="announcements",
                    padding_top="1.5em",
                ),
                rx.tabs.content(
                    _settings_api_tab(), value="api", padding_top="1.5em"
                ),
                rx.tabs.content(
                    _settings_audit_tab(), value="audit",
                    padding_top="1.5em",
                ),
                rx.tabs.content(
                    _settings_appearance_tab(), value="appearance",
                    padding_top="1.5em",
                ),
                rx.tabs.content(
                    _settings_notifications_tab(), value="notifications",
                    padding_top="1.5em",
                ),
                rx.tabs.content(
                    _settings_sync_tab(), value="sync", padding_top="1.5em",
                ),
                default_value="users",
            ),
            _manage_user_dialog(),
        ),
        title="Settings",
    )


# ---- Login / first-run setup -------------------------------------------------
def _login_form() -> rx.Component:
    return rx.form(
        rx.vstack(
            rx.vstack(
                rx.heading("Welcome back", size="7", class_name="login-title"),
                rx.text(
                    "Sign in to keep your household together.",
                    color_scheme="gray",
                    size="3",
                ),
                spacing="1",
                align="start",
                width="100%",
            ),
            rx.input(
                placeholder="Username",
                name="username",
                size="3",
                width="100%",
                auto_focus=True,
                class_name="login-input",
            ),
            rx.input(
                placeholder="Password",
                type="password",
                name="password",
                size="3",
                width="100%",
                class_name="login-input",
            ),
            rx.hstack(
                rx.checkbox("Remember me for 30 days", name="remember"),
                rx.spacer(),
                align="center",
                width="100%",
            ),
            rx.button(
                "Sign in",
                rx.icon("arrow-right", size=16),
                type="submit",
                size="3",
                width="100%",
                class_name="login-button",
            ),
            rx.cond(
                AuthState.login_error,
                rx.callout(
                    AuthState.login_error,
                    icon="triangle_alert",
                    color_scheme="red",
                    custom_attrs={"role": "alert", "aria-live": "polite"},
                ),
                rx.fragment(),
            ),
            spacing="4",
            align="stretch",
            width="100%",
        ),
        on_submit=AuthState.attempt_login,
        reset_on_submit=False,
        width="100%",
    )


def _setup_form() -> rx.Component:
    return rx.form(
        rx.vstack(
            rx.heading("First-run setup", size="6"),
            rx.text(
                "No accounts exist yet. Create the first admin user — you'll be "
                "able to add more users from Settings after signing in.",
                color_scheme="gray",
                size="2",
            ),
            rx.vstack(
                rx.text("Display name", size="1", weight="bold"),
                rx.input(
                    placeholder="Display name (e.g. Alex)",
                    name="name",
                    size="3",
                    width="100%",
                    auto_focus=True,
                    aria_label="Display name",
                ),
                spacing="1", align="stretch", width="100%",
            ),
            rx.vstack(
                rx.text("Username", size="1", weight="bold"),
                rx.input(
                    placeholder="Username (for signing in)",
                    name="username",
                    size="3",
                    width="100%",
                    aria_label="Username",
                ),
                spacing="1", align="stretch", width="100%",
            ),
            rx.vstack(
                rx.text("Password", size="1", weight="bold"),
                rx.input(
                    placeholder="Password (8+ characters)",
                    type="password",
                    name="password",
                    size="3",
                    width="100%",
                    aria_label="Password",
                ),
                spacing="1", align="stretch", width="100%",
            ),
            rx.vstack(
                rx.text("Confirm password", size="1", weight="bold"),
                rx.input(
                    placeholder="Confirm password",
                    type="password",
                    name="password_confirm",
                    size="3",
                    width="100%",
                    aria_label="Confirm password",
                ),
                spacing="1", align="stretch", width="100%",
            ),
            rx.button(
                "Create admin and sign in",
                type="submit",
                size="3",
                width="100%",
            ),
            rx.cond(
                AuthState.setup_error,
                rx.callout(
                    AuthState.setup_error,
                    icon="triangle_alert",
                    color_scheme="red",
                ),
                rx.fragment(),
            ),
            spacing="3",
            align="stretch",
            width="100%",
        ),
        on_submit=AuthState.attempt_setup,
        reset_on_submit=False,
        width="100%",
    )


def _login_hero() -> rx.Component:
    """Left/top panel — the brand showcase. Mirrors the sidebar logomark
    but blown up and centered so the login page feels like a real splash."""
    return rx.box(
        # Animated mesh-gradient background lives in CSS via ::before/::after
        rx.box(
            rx.box(
                rx.el.span("GYST", class_name="hero-word"),
                rx.el.span(".", class_name="hero-dot"),
                class_name="hero-row",
            ),
            rx.text(
                "Get your stuff together.",
                class_name="hero-tagline",
            ),
            rx.box(
                rx.hstack(
                    rx.icon("package", size=16),
                    rx.text("Inventory", size="2"),
                    spacing="2", align="center",
                ),
                rx.hstack(
                    rx.icon("list-checks", size=16),
                    rx.text("Chores", size="2"),
                    spacing="2", align="center",
                ),
                rx.hstack(
                    rx.icon("shopping-cart", size=16),
                    rx.text("Groceries", size="2"),
                    spacing="2", align="center",
                ),
                rx.hstack(
                    rx.icon("utensils", size=16),
                    rx.text("Meals", size="2"),
                    spacing="2", align="center",
                ),
                rx.hstack(
                    rx.icon("calendar-clock", size=16),
                    rx.text("Appointments", size="2"),
                    spacing="2", align="center",
                ),
                rx.hstack(
                    rx.icon("sticky-note", size=16),
                    rx.text("Notes", size="2"),
                    spacing="2", align="center",
                ),
                class_name="hero-features",
            ),
            class_name="hero-stack",
        ),
        class_name="login-hero",
    )


def login_page() -> rx.Component:
    """Login + first-run setup splash. Two-pane: brand hero on the left
    (or top on mobile), form panel on the right (or below)."""
    return rx.box(
        _login_hero(),
        rx.box(
            rx.box(
                rx.cond(
                    AuthState.needs_setup, _setup_form(), _login_form()
                ),
                class_name="login-form-inner",
            ),
            class_name="login-form-pane",
        ),
        class_name="login-shell",
    )


# ---- Announcements -----------------------------------------------------------
def _announcement_view_card(a) -> rx.Component:
    """Read-only feed card — no action buttons. Used on /announcements."""
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.cond(
                    a["pinned_bool"],
                    rx.icon("pin", size=14, color=rx.color("amber", 10)),
                    rx.fragment(),
                ),
                rx.heading(a["title"], size="5"),
                spacing="2",
                align="center",
            ),
            rx.cond(
                a["body"],
                rx.text(a["body"], color_scheme="gray", size="2"),
                rx.fragment(),
            ),
            rx.hstack(
                rx.cond(
                    a["posted_by_name"],
                    _person_chip(a["posted_by_name"], a["posted_by_color"]),
                    rx.fragment(),
                ),
                rx.text(a["created_at"], color_scheme="gray", size="1"),
                spacing="3",
                align="center",
            ),
            spacing="2",
            align="stretch",
        ),
        size="2",
        width="100%",
    )


def _announcement_manage_card(a) -> rx.Component:
    """Admin-side card with pin + delete buttons. Used in Settings."""
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.cond(
                    a["pinned_bool"],
                    rx.icon("pin", size=14, color=rx.color("amber", 10)),
                    rx.fragment(),
                ),
                rx.heading(a["title"], size="5"),
                spacing="2",
                align="center",
            ),
            rx.cond(
                a["body"],
                rx.text(a["body"], color_scheme="gray", size="2"),
                rx.fragment(),
            ),
            rx.hstack(
                rx.cond(
                    a["posted_by_name"],
                    _person_chip(a["posted_by_name"], a["posted_by_color"]),
                    rx.fragment(),
                ),
                rx.text(a["created_at"], color_scheme="gray", size="1"),
                rx.spacer(),
                rx.button(
                    rx.icon("pin", size=14),
                    on_click=AnnouncementsState.toggle_pinned(a["id"]),
                    variant="soft",
                    size="1",
                ),
                rx.button(
                    rx.icon("trash-2", size=14),
                    on_click=AnnouncementsState.delete(a["id"]),
                    color_scheme="red",
                    variant="soft",
                    size="1",
                    aria_label='Delete announcement',
                ),
                spacing="3",
                align="center",
                width="100%",
            ),
            spacing="2",
            align="stretch",
        ),
        size="2",
        width="100%",
    )


def _chat_turn(entry) -> rx.Component:
    """Render one transcript entry. Three shapes: user bubble, assistant
    bubble, and a compact tool-call chip showing what JARVIS just did."""
    return rx.match(
        entry["kind"],
        (
            "user",
            rx.box(
                rx.text(entry["text"], class_name="chat-bubble-text"),
                class_name="chat-bubble chat-bubble-user",
            ),
        ),
        (
            "assistant",
            rx.box(
                rx.text(entry["text"], class_name="chat-bubble-text"),
                class_name="chat-bubble chat-bubble-assistant",
            ),
        ),
        (
            "tool_call",
            rx.hstack(
                rx.icon("wrench", size=12),
                rx.text(entry["name"], size="1", weight="medium"),
                rx.cond(
                    entry["args_json"],
                    rx.text(
                        entry["args_json"],
                        size="1",
                        color_scheme="gray",
                        class_name="chat-tool-args",
                    ),
                    rx.fragment(),
                ),
                spacing="2",
                align="center",
                class_name="chat-tool-chip",
            ),
        ),
        rx.fragment(),
    )


def chat_page() -> rx.Component:
    return layout(
        rx.box(
            rx.vstack(
                rx.hstack(
                    rx.icon("brain-circuit", size=20, color="var(--accent-9)"),
                    rx.heading("JARVIS", size="5", weight="bold"),
                    rx.spacer(),
                    rx.button(
                        rx.icon("trash-2", size=12),
                        "Clear",
                        on_click=AssistantState.clear_chat,
                        variant="soft",
                        color_scheme="gray",
                        size="1",
                    ),
                    spacing="2",
                    align="center",
                    width="100%",
                ),
                rx.box(
                    rx.foreach(AssistantState.transcript, _chat_turn),
                    rx.cond(
                        AssistantState.sending,
                        rx.hstack(
                            rx.spinner(size="1"),
                            rx.text(
                                "Thinking…", size="1", color_scheme="gray",
                            ),
                            spacing="2",
                            align="center",
                            class_name="chat-thinking",
                        ),
                        rx.fragment(),
                    ),
                    class_name="chat-scroll",
                ),
                # Input lives in the global JARVIS omnibox (top of page on
                # desktop, above the bottom-nav on mobile). When the user
                # submits from there while on /chat, OmniboxState routes
                # the message through AssistantState.send so it lands in
                # the transcript above — no duplicate input row here.
                spacing="3",
                align="stretch",
                width="100%",
                height="100%",
            ),
            class_name="chat-shell",
        ),
        title="Assistant",
    )


def announcements_page() -> rx.Component:
    """Read-only feed — anyone signed in can see announcements here.
    Posting/pinning/deleting happens in Settings → Announcements."""
    return layout(
        rx.vstack(
            rx.cond(
                AnnouncementsState.items,
                rx.vstack(
                    rx.foreach(
                        AnnouncementsState.items, _announcement_view_card
                    ),
                    spacing="3",
                    align="stretch",
                    width="100%",
                ),
                _empty(
                    "No announcements yet. Admins can post one from "
                    "Settings → Announcements."
                ),
            ),
            spacing="4",
            align="stretch",
            width="100%",
        ),
        title="Announcements",
    )


def _settings_announcements_tab() -> rx.Component:
    """Admin form to post + manage announcements. Mounted in Settings."""
    return rx.vstack(
        rx.card(
            rx.vstack(
                rx.heading("Post a new announcement", size="4"),
                rx.input(
                    placeholder="Title",
                    value=AnnouncementsState.new_title,
                    on_change=AnnouncementsState.set_new_title,
                    size="3",
                ),
                rx.text_area(
                    placeholder="Details (optional)",
                    value=AnnouncementsState.new_body,
                    on_change=AnnouncementsState.set_new_body,
                    size="3",
                ),
                rx.checkbox(
                    "Pin to top",
                    checked=AnnouncementsState.new_pinned,
                    on_change=AnnouncementsState.set_new_pinned,
                ),
                rx.button("Post", on_click=AnnouncementsState.add, size="3"),
                rx.cond(
                    AnnouncementsState.error,
                    rx.callout(
                        AnnouncementsState.error,
                        icon="triangle_alert",
                        color_scheme="red",
                    ),
                    rx.fragment(),
                ),
                spacing="3",
                align="stretch",
            ),
            size="2",
        ),
        rx.heading("Existing announcements", size="4"),
        rx.cond(
            AnnouncementsState.items,
            rx.vstack(
                rx.foreach(
                    AnnouncementsState.items, _announcement_manage_card
                ),
                spacing="3",
                align="stretch",
                width="100%",
            ),
            _empty("Nothing posted yet."),
        ),
        spacing="4",
        align="stretch",
        width="100%",
        max_width="700px",
    )


# ---- Notes -------------------------------------------------------------------
def _note_card(n) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.cond(
                    n["pinned_bool"],
                    rx.icon("pin", size=14, color="var(--amber-9)"),
                    rx.fragment(),
                ),
                rx.heading(n["title"], size="4"),
                rx.spacer(),
                rx.icon_button(
                    rx.icon("pin", size=14),
                    on_click=NotesState.toggle_pinned(n["id"]),
                    variant=rx.cond(n["pinned_bool"], "solid", "soft"),
                    color_scheme="amber",
                    size="2",
                    aria_label='Toggle pinned',
                ),
                rx.icon_button(
                    rx.icon("pencil", size=14),
                    on_click=NotesState.open_edit(n["id"]),
                    variant="soft",
                    size="2",
                    aria_label='Edit note',
                ),
                rx.icon_button(
                    rx.icon("trash-2", size=14),
                    on_click=NotesState.delete(n["id"]),
                    variant="soft",
                    color_scheme="red",
                    size="2",
                    aria_label='Delete note',
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            rx.cond(
                n["body"],
                rx.text(
                    n["body"],
                    size="2",
                    white_space="pre-wrap",
                ),
                rx.fragment(),
            ),
            rx.text(
                "Updated " + n["updated_at"],
                size="1",
                color_scheme="gray",
            ),
            spacing="2",
            align="stretch",
            width="100%",
        ),
        size="2",
    )


def _note_edit_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Edit note"),
            rx.vstack(
                rx.input(
                    placeholder="Title",
                    value=NotesState.edit_title,
                    on_change=NotesState.set_edit_title,
                    size="3",
                ),
                rx.box(
                    rx.text_area(
                        placeholder="Body",
                        value=NotesState.edit_body,
                        on_change=NotesState.set_edit_body,
                        size="3",
                        rows="10",
                        id="note-edit-body",
                        class_name="note-body-textarea",
                    ),
                    rx.el.button(
                        rx.icon("mic", size=14),
                        on_click=rx.call_script(
                            "window.gystSpeakInto('#note-edit-body', '#note-edit-body');"
                        ),
                        type="button",
                        id="note-edit-body-mic",
                        class_name="note-mic-btn",
                        title="Dictate into this note",
                        custom_attrs={"aria-label": "Dictate into this note"},
                    ),
                    rx.el.div("", id="note-edit-body-status",
                              class_name="note-mic-status"),
                    class_name="note-body-wrap",
                ),
                rx.hstack(
                    rx.button(
                        rx.icon("sparkles", size=14),
                        rx.cond(
                            NotesState.polishing,
                            "Polishing…",
                            "Polish with AI",
                        ),
                        on_click=NotesState.polish_edit_body,
                        variant="soft",
                        size="2",
                        disabled=NotesState.polishing,
                    ),
                    spacing="2",
                    align="center",
                ),
                rx.hstack(
                    rx.button(
                        "Cancel",
                        on_click=NotesState.close_edit,
                        variant="soft",
                        color_scheme="gray",
                    ),
                    rx.button("Save", on_click=NotesState.save_edit),
                    spacing="2",
                    justify="end",
                    width="100%",
                ),
                spacing="3",
                align="stretch",
                width="100%",
            ),
            max_width="600px",
        ),
        open=NotesState.editing_id > 0,
        on_open_change=NotesState.close_edit,
    )


def notes_page() -> rx.Component:
    return layout(
        rx.fragment(
            _note_edit_dialog(),
            rx.vstack(
                rx.card(
                    rx.vstack(
                        # Compact entry: title input is the primary
                        # affordance, body is collapsed to 3 rows by
                        # default. Enter in the title submits when
                        # body is blank — fastest possible quick note.
                        rx.input(
                            placeholder="Quick note title…",
                            value=NotesState.new_title,
                            on_change=NotesState.set_new_title,
                            on_key_down=NotesState.maybe_submit_on_enter,
                            size="3",
                            auto_focus=True,
                        ),
                        rx.box(
                            rx.text_area(
                                placeholder="Body (optional)",
                                value=NotesState.new_body,
                                on_change=NotesState.set_new_body,
                                size="3",
                                rows="3",
                                id="note-new-body",
                                class_name="note-body-textarea",
                            ),
                            rx.el.button(
                                rx.icon("mic", size=14),
                                on_click=rx.call_script(
                                    "window.gystSpeakInto('#note-new-body', '#note-new-body');"
                                ),
                                type="button",
                                id="note-new-body-mic",
                                class_name="note-mic-btn",
                                title="Dictate into this note",
                                custom_attrs={"aria-label": "Dictate into this note"},
                            ),
                            rx.el.div("", id="note-new-body-status",
                                      class_name="note-mic-status"),
                            class_name="note-body-wrap",
                        ),
                        rx.hstack(
                            rx.button(
                                rx.icon("sparkles", size=14),
                                rx.cond(
                                    NotesState.polishing,
                                    "Polishing…",
                                    "Polish with AI",
                                ),
                                on_click=NotesState.polish_new_body,
                                variant="soft",
                                size="2",
                                disabled=NotesState.polishing,
                            ),
                            spacing="2",
                            align="center",
                        ),
                        rx.hstack(
                            rx.checkbox(
                                "Pin to top",
                                checked=NotesState.new_pinned,
                                on_change=NotesState.set_new_pinned,
                            ),
                            rx.spacer(),
                            rx.button(
                                rx.icon("circle-plus", size=14),
                                "Add note",
                                on_click=NotesState.add,
                                size="3",
                            ),
                            spacing="3",
                            align="center",
                            width="100%",
                        ),
                        rx.cond(
                            NotesState.error,
                            rx.callout(
                                NotesState.error,
                                icon="triangle_alert",
                                color_scheme="red",
                            ),
                            rx.fragment(),
                        ),
                        spacing="3",
                        align="stretch",
                    ),
                    size="2",
                ),
                rx.cond(
                    NotesState.items,
                    rx.vstack(
                        rx.foreach(NotesState.items, _note_card),
                        spacing="3",
                        align="stretch",
                        width="100%",
                    ),
                    rx.box(
                        rx.icon("sticky-note", size=28, color_scheme="gray"),
                        rx.text(
                            "No notes yet — type one above.",
                            size="2",
                            color_scheme="gray",
                            margin_top="0.5em",
                        ),
                        text_align="center",
                        padding_y="2em",
                    ),
                ),
                spacing="4",
                align="stretch",
                width="100%",
            ),
        ),
        title="Notes",
    )


# ---- Groceries ---------------------------------------------------------------
def _grocery_row(g) -> rx.Component:
    return rx.hstack(
        rx.checkbox(
            checked=g["purchased_bool"],
            on_change=GroceriesState.toggle_purchased(g["id"]),
            size="3",
        ),
        rx.vstack(
            rx.text(g["name"], weight="medium", size="3"),
            rx.cond(
                g["quantity"],
                rx.text(g["quantity"], color_scheme="gray", size="1"),
                rx.fragment(),
            ),
            spacing="0",
            align="start",
            flex="1",
        ),
        rx.button(
            rx.icon("trash-2", size=14),
            on_click=GroceriesState.delete(g["id"]),
            color_scheme="red",
            variant="soft",
            size="1",
            aria_label='Delete grocery item',
        ),
        spacing="3",
        align="center",
        width="100%",
        padding_y="0.5em",
        border_bottom=f"1px solid {rx.color('gray', 4)}",
    )


def groceries_page() -> rx.Component:
    """List-only view of the shopping list."""
    return layout(
        rx.vstack(
            rx.hstack(
                rx.text(
                    "Tap a checkbox to mark an item as purchased.",
                    color_scheme="gray",
                    size="2",
                    flex="1",
                ),
                rx.button(
                    rx.icon("trash-2", size=14),
                    "Clear purchased",
                    on_click=GroceriesState.clear_purchased,
                    variant="soft",
                    color_scheme="gray",
                    size="2",
                ),
                align="center",
                width="100%",
            ),
            rx.cond(
                GroceriesState.items,
                rx.vstack(
                    rx.foreach(GroceriesState.items, _grocery_row),
                    spacing="0",
                    align="stretch",
                    width="100%",
                ),
                _empty_cta("shopping-cart", "Shopping list's clear. Tap + to add.", "Add item", "/groceries/add"),
            ),
            spacing="4",
            align="stretch",
            width="100%",
        ),
        title="Shopping list",
    )


def groceries_add_page() -> rx.Component:
    return layout(
        rx.vstack(
            rx.card(
                rx.vstack(
                    rx.vstack(
                        rx.text("Item", size="1", weight="bold"),
                        rx.input(
                            placeholder="Item (e.g. milk)",
                            value=GroceriesState.new_name,
                            on_change=GroceriesState.set_new_name,
                            size="3",
                            aria_label="Item name",
                        ),
                        spacing="1", align="stretch", width="100%",
                    ),
                    rx.vstack(
                        rx.text("Quantity", size="1", weight="bold"),
                        rx.input(
                            placeholder="Quantity (optional, e.g. 2 gallons)",
                            value=GroceriesState.new_quantity,
                            on_change=GroceriesState.set_new_quantity,
                            size="3",
                            aria_label="Quantity",
                        ),
                        spacing="1", align="stretch", width="100%",
                    ),
                    rx.button("Add", on_click=GroceriesState.add, size="3"),
                    rx.cond(
                        GroceriesState.error,
                        rx.callout(
                            GroceriesState.error,
                            icon="triangle_alert",
                            color_scheme="red",
                        ),
                        rx.fragment(),
                    ),
                    spacing="3",
                    align="stretch",
                ),
                size="2",
            ),
            spacing="4",
            align="stretch",
            width="100%",
            max_width="500px",
        ),
        title="Add to shopping list",
    )


# ---- Meals -------------------------------------------------------------------
def _meal_card(m) -> rx.Component:
    return rx.card(
        rx.hstack(
            rx.vstack(
                rx.hstack(
                    rx.heading(m["name"], size="4"),
                    rx.cond(
                        m["meal_type"],
                        rx.badge(m["meal_type"], color_scheme="indigo", variant="soft"),
                        rx.fragment(),
                    ),
                    spacing="2",
                    align="center",
                ),
                rx.cond(
                    m["meal_date"],
                    rx.hstack(
                        rx.icon("calendar", size=14),
                        rx.text(m["meal_date"], size="2", color_scheme="gray"),
                        spacing="1",
                        align="center",
                    ),
                    rx.fragment(),
                ),
                rx.cond(
                    m["ingredients_text"],
                    rx.hstack(
                        rx.icon("utensils", size=14),
                        rx.text(
                            m["ingredients_text"],
                            size="1",
                            color_scheme="gray",
                        ),
                        spacing="1",
                        align="start",
                    ),
                    rx.fragment(),
                ),
                rx.cond(
                    m["notes"],
                    rx.text(m["notes"], color_scheme="gray", size="2"),
                    rx.fragment(),
                ),
                spacing="2",
                align="start",
                flex="1",
            ),
            rx.button(
                rx.icon("trash-2", size=14),
                on_click=MealsState.delete(m["id"]),
                color_scheme="red",
                variant="soft",
                size="1",
                aria_label='Delete meal',
            ),
            spacing="3",
            align="start",
            width="100%",
        ),
        size="2",
        width="100%",
    )


def _cookable_card(r) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.cond(
                    r["fully_stocked"],
                    rx.badge(
                        rx.icon("circle-check", size=12),
                        "All ingredients on hand",
                        color_scheme="green", variant="soft",
                    ),
                    rx.badge(
                        rx.icon("triangle-alert", size=12),
                        "Missing ", r["missing"].to(str),
                        color_scheme="amber", variant="soft",
                    ),
                ),
                rx.spacer(),
                rx.text(
                    r["have"].to(str), "/", r["have"].to(str) +
                    r["missing"].to(str),
                    size="1", color_scheme="gray",
                ),
                width="100%",
                align="center",
            ),
            rx.heading(r["name"], size="4"),
            rx.text(r["ingredients_text"], size="1", color_scheme="gray"),
            rx.cond(
                r["missing"] > 0,
                rx.vstack(
                    rx.text(
                        "Missing: " + r["missing_names"],
                        size="1", color_scheme="amber",
                    ),
                    # One-tap flow from a stocked-status callout into
                    # the shopping list. The recipe links back via
                    # from_meal_id so we can show its origin later.
                    rx.button(
                        rx.icon("shopping-cart", size=14),
                        "Add missing to shopping list",
                        on_click=MealsState.add_missing_to_groceries(r["id"]),
                        size="2",
                        variant="soft",
                    ),
                    spacing="2", align="start",
                ),
                rx.fragment(),
            ),
            spacing="2",
            align="stretch",
            width="100%",
        ),
        size="2",
    )


def meals_page() -> rx.Component:
    return layout(
        rx.vstack(
            rx.cond(
                MealsState.cookable,
                rx.vstack(
                    rx.heading("What you can cook tonight", size="5"),
                    rx.text(
                        "Saved recipes scored against your current "
                        "inventory. Fully-stocked first.",
                        size="2", color_scheme="gray",
                    ),
                    rx.vstack(
                        rx.foreach(MealsState.cookable, _cookable_card),
                        spacing="2",
                        align="stretch",
                        width="100%",
                    ),
                    rx.divider(margin_y="0.75em"),
                    spacing="2",
                    align="stretch",
                    width="100%",
                ),
                rx.fragment(),
            ),
            rx.heading("Planned meals", size="5"),
            rx.cond(
                MealsState.items,
                rx.vstack(
                    rx.foreach(MealsState.items, _meal_card),
                    spacing="3",
                    align="stretch",
                    width="100%",
                ),
                _empty("No meals planned. Use 'Add meal' to plan one."),
            ),
            spacing="4",
            align="stretch",
            width="100%",
        ),
        title="Meal plan",
    )


def meals_add_page() -> rx.Component:
    return layout(
        rx.vstack(
            rx.card(
                rx.vstack(
                    # --- Quick-pick from saved recipes ---
                    rx.vstack(
                        rx.text(
                            "Start from a saved recipe (optional)",
                            size="1",
                            weight="bold",
                            color_scheme="gray",
                        ),
                        rx.select(
                            MealsState.template_options,
                            value=MealsState.new_template,
                            on_change=MealsState.set_template,
                            size="3",
                            width="100%",
                        ),
                        spacing="1",
                        align="stretch",
                        width="100%",
                    ),
                    rx.divider(margin_y="0.25em"),

                    # --- Shared: name + ingredients ---
                    rx.input(
                        placeholder="Meal / recipe name (e.g. chicken stir-fry)",
                        value=MealsState.new_name,
                        on_change=MealsState.set_new_name,
                        size="3",
                    ),
                    rx.vstack(
                        rx.text(
                            "Ingredients (one per line)",
                            size="2",
                            weight="bold",
                        ),
                        rx.text_area(
                            placeholder=(
                                "spaghetti\nground beef\ntomato sauce\n…"
                            ),
                            value=MealsState.new_ingredients_text,
                            on_change=MealsState.set_new_ingredients_text,
                            size="3",
                            rows="6",
                        ),
                        spacing="1",
                        align="stretch",
                    ),

                    # --- Planning-only fields (used by Add to plan) ---
                    rx.divider(margin_y="0.25em"),
                    rx.text(
                        "Planning details (only used when adding to plan)",
                        size="1",
                        weight="bold",
                        color_scheme="gray",
                    ),
                    rx.hstack(
                        rx.input(
                            type="date",
                            value=MealsState.new_date,
                            on_change=MealsState.set_new_date,
                            size="3",
                        ),
                        rx.select(
                            MealsState.meal_type_options,
                            value=MealsState.new_type,
                            on_change=MealsState.set_new_type,
                            size="3",
                        ),
                        spacing="3",
                    ),
                    rx.text_area(
                        placeholder="Notes (prep details, links…)",
                        value=MealsState.new_notes,
                        on_change=MealsState.set_new_notes,
                        size="3",
                    ),
                    rx.text(
                        "When adding to the plan, anything not already in "
                        "your inventory is auto-added to the shopping list.",
                        size="1",
                        color_scheme="gray",
                    ),

                    # --- Action row ---
                    rx.divider(margin_y="0.25em"),
                    rx.hstack(
                        rx.button(
                            rx.icon("bookmark", size=14),
                            "Save as recipe",
                            on_click=MealsState.save_as_recipe,
                            variant="soft",
                            size="3",
                        ),
                        rx.button(
                            rx.icon("calendar-plus", size=14),
                            "Add to plan",
                            on_click=MealsState.add,
                            variant="soft",
                            size="3",
                        ),
                        rx.button(
                            rx.icon("check", size=14),
                            "Save & add to plan",
                            on_click=MealsState.save_recipe_and_add,
                            size="3",
                        ),
                        spacing="2",
                        wrap="wrap",
                        width="100%",
                    ),

                    # --- Validation errors only (success surfaces as toast) ---
                    rx.cond(
                        MealsState.error,
                        rx.callout(
                            MealsState.error,
                            icon="triangle_alert",
                            color_scheme="red",
                        ),
                        rx.fragment(),
                    ),
                    rx.cond(
                        MealsState.recipe_error,
                        rx.callout(
                            MealsState.recipe_error,
                            icon="triangle_alert",
                            color_scheme="amber",
                        ),
                        rx.fragment(),
                    ),
                    spacing="3",
                    align="stretch",
                ),
                size="2",
            ),
            _meals_recipes_list_card(),
            spacing="4",
            align="stretch",
            width="100%",
            max_width="640px",
        ),
        title="Plan a meal",
    )


def _recipe_row(r) -> rx.Component:
    return rx.card(
        rx.hstack(
            rx.vstack(
                rx.text(r["name"], weight="bold", size="3"),
                rx.cond(
                    r["ingredients_text"],
                    rx.text(
                        r["ingredients_text"], size="1", color_scheme="gray"
                    ),
                    rx.fragment(),
                ),
                spacing="1",
                align="start",
            ),
            rx.spacer(),
            rx.icon_button(
                rx.icon("trash-2", size=16),
                on_click=MealsState.delete_recipe(r["id"]),
                variant="soft",
                color_scheme="red",
                size="2",
                aria_label='Delete recipe',
            ),
            spacing="3",
            align="center",
            width="100%",
        ),
        size="1",
    )


def _meals_recipes_list_card() -> rx.Component:
    """List of saved recipes with delete actions. The "save" action lives in
    the unified form above; this card is read-only browsing."""
    return rx.card(
        rx.vstack(
            rx.heading("Saved recipes", size="4"),
            rx.text(
                "Recipes appear in the 'Start from a saved recipe' dropdown "
                "above. Use the form above to add new ones.",
                size="1",
                color_scheme="gray",
            ),
            rx.cond(
                MealsState.recipes,
                rx.vstack(
                    rx.foreach(MealsState.recipes, _recipe_row),
                    spacing="2",
                    align="stretch",
                    width="100%",
                ),
                rx.text(
                    "No recipes saved yet.", size="2", color_scheme="gray"
                ),
            ),
            spacing="3",
            align="stretch",
        ),
        size="2",
    )


# ---- Appointments ------------------------------------------------------------
def _appointment_card(a) -> rx.Component:
    return rx.card(
        rx.hstack(
            rx.vstack(
                rx.heading(a["title"], size="4"),
                rx.hstack(
                    rx.icon("calendar", size=14),
                    rx.text(a["appointment_at"], size="2"),
                    spacing="1",
                    align="center",
                ),
                rx.cond(
                    a["location"],
                    rx.hstack(
                        rx.icon("map-pin", size=14),
                        rx.text(a["location"], size="2", color_scheme="gray"),
                        spacing="1",
                        align="center",
                    ),
                    rx.fragment(),
                ),
                rx.cond(
                    a["for_person_name"],
                    _person_chip(a["for_person_name"], a["for_person_color"]),
                    rx.fragment(),
                ),
                rx.cond(
                    a["notes"],
                    rx.text(a["notes"], color_scheme="gray", size="2"),
                    rx.fragment(),
                ),
                spacing="2",
                align="start",
                flex="1",
            ),
            rx.button(
                rx.icon("trash-2", size=14),
                on_click=AppointmentsState.delete(a["id"]),
                color_scheme="red",
                variant="soft",
                size="1",
                aria_label='Delete appointment',
            ),
            spacing="3",
            align="start",
            width="100%",
        ),
        size="2",
        width="100%",
    )


def appointments_page() -> rx.Component:
    return layout(
        rx.vstack(
            rx.cond(
                AppointmentsState.items,
                rx.vstack(
                    rx.foreach(AppointmentsState.items, _appointment_card),
                    spacing="3",
                    align="stretch",
                    width="100%",
                ),
                _empty_cta("calendar", "Nothing on the calendar.", "Add appointment", "/appointments/add"),
            ),
            spacing="4",
            align="stretch",
            width="100%",
        ),
        title="Schedule",
    )


def appointments_add_page() -> rx.Component:
    return layout(
        rx.vstack(
            rx.card(
                rx.vstack(
                    rx.vstack(
                        rx.text("Title", size="1", weight="bold"),
                        rx.input(
                            placeholder="Title (e.g. dentist)",
                            value=AppointmentsState.new_title,
                            on_change=AppointmentsState.set_new_title,
                            size="3",
                            aria_label="Appointment title",
                        ),
                        spacing="1", align="stretch", width="100%",
                    ),
                    rx.hstack(
                        rx.vstack(
                            rx.text("Date", size="1", weight="bold"),
                            rx.input(
                                type="date",
                                value=AppointmentsState.new_date,
                                on_change=AppointmentsState.set_new_date,
                                size="3",
                                aria_label="Appointment date",
                            ),
                            spacing="1", align="start",
                        ),
                        rx.vstack(
                            rx.text("Time", size="1", weight="bold"),
                            rx.input(
                                type="time",
                                value=AppointmentsState.new_time,
                                on_change=AppointmentsState.set_new_time,
                                size="3",
                                aria_label="Appointment time",
                            ),
                            spacing="1", align="start",
                        ),
                        spacing="3",
                    ),
                    rx.vstack(
                        rx.text("Location", size="1", weight="bold"),
                        rx.input(
                            placeholder="Location (optional)",
                            value=AppointmentsState.new_location,
                            on_change=AppointmentsState.set_new_location,
                            size="3",
                            aria_label="Location",
                        ),
                        spacing="1", align="stretch", width="100%",
                    ),
                    rx.hstack(
                        rx.text("For:", weight="medium"),
                        rx.select(
                            AppointmentsState.for_options,
                            value=AppointmentsState.new_for_name,
                            on_change=AppointmentsState.set_new_for,
                            size="3",
                        ),
                        spacing="3",
                        align="center",
                    ),
                    rx.text_area(
                        placeholder="Notes (optional)",
                        value=AppointmentsState.new_notes,
                        on_change=AppointmentsState.set_new_notes,
                        size="3",
                    ),
                    rx.hstack(
                        rx.icon("repeat", size=14),
                        rx.text("Repeats:", weight="medium"),
                        rx.select(
                            AppointmentsState.recurrence_options,
                            value=AppointmentsState.recurrence_label,
                            on_change=AppointmentsState.set_recurrence_label,
                            size="3",
                        ),
                        spacing="2",
                        align="center",
                    ),
                    rx.button("Add", on_click=AppointmentsState.add, size="3"),
                    rx.cond(
                        AppointmentsState.error,
                        rx.callout(
                            AppointmentsState.error,
                            icon="triangle_alert",
                            color_scheme="red",
                        ),
                        rx.fragment(),
                    ),
                    spacing="3",
                    align="stretch",
                ),
                size="2",
            ),
            spacing="4",
            align="stretch",
            width="100%",
            max_width="600px",
        ),
        title="New appointment",
    )


# ---- Inventory item detail ---------------------------------------------------
def _detail_field(label: str, value) -> rx.Component:
    return rx.hstack(
        rx.text(
            label,
            size="1",
            weight="bold",
            color_scheme="gray",
            text_transform="uppercase",
            letter_spacing="0.06em",
            width="120px",
        ),
        rx.text(value, size="3"),
        spacing="2",
        align="start",
    )


def _detail_expiry_card(item) -> rx.Component:
    """Set/clear an expiration date on an item. Reminder dispatcher pushes
    a notification 3 days before."""
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.icon("calendar-clock", size=14),
                rx.text("Expires", weight="medium", size="2"),
                rx.spacer(),
                rx.cond(
                    item["expires_at"],
                    rx.badge(
                        item["expires_at"],
                        color_scheme="amber", variant="soft",
                    ),
                    rx.badge(
                        "Not set", color_scheme="gray", variant="soft",
                    ),
                ),
                align="center",
                width="100%",
            ),
            rx.hstack(
                rx.input(
                    type="date",
                    value=ItemDetailState.expiry_input,
                    on_change=ItemDetailState.set_expiry_input,
                    size="2",
                ),
                rx.button(
                    "Save",
                    on_click=ItemDetailState.save_expiry,
                    size="2",
                    variant="soft",
                ),
                spacing="2",
                align="center",
            ),
            spacing="2",
            align="stretch",
            width="100%",
        ),
        class_name="detail-card",
    )


def _detail_loan_card(item) -> rx.Component:
    """Track who borrowed this item. Toggle between Loan-out form and
    'Lent to X' panel with a Return button."""
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.icon("hand-helping", size=14),
                rx.text("Loan", weight="medium", size="2"),
                rx.spacer(),
                rx.cond(
                    item["is_loaned"],
                    rx.badge(
                        "Lent to " + item["loaned_to_name"],
                        color_scheme="orange", variant="soft",
                    ),
                    rx.badge(
                        "On hand", color_scheme="green", variant="soft",
                    ),
                ),
                align="center",
                width="100%",
            ),
            rx.cond(
                item["is_loaned"],
                rx.vstack(
                    rx.cond(
                        item["loaned_at"],
                        rx.text(
                            "Since " + item["loaned_at"], size="1",
                            color_scheme="gray",
                        ),
                        rx.fragment(),
                    ),
                    rx.cond(
                        item["loan_notes"],
                        rx.text(item["loan_notes"], size="2"),
                        rx.fragment(),
                    ),
                    rx.button(
                        rx.icon("rotate-ccw", size=14),
                        "Mark returned",
                        on_click=ItemDetailState.loan_return,
                        size="2",
                        variant="soft",
                        color_scheme="green",
                    ),
                    spacing="2",
                    align="stretch",
                    width="100%",
                ),
                rx.vstack(
                    rx.input(
                        placeholder="Who has it?",
                        value=ItemDetailState.loan_to_name,
                        on_change=ItemDetailState.set_loan_to_name,
                        size="2",
                    ),
                    rx.input(
                        placeholder="Notes (optional)",
                        value=ItemDetailState.loan_notes,
                        on_change=ItemDetailState.set_loan_notes,
                        size="2",
                    ),
                    rx.button(
                        "Loan out",
                        on_click=ItemDetailState.loan_out,
                        size="2",
                        variant="soft",
                    ),
                    spacing="2",
                    align="stretch",
                    width="100%",
                ),
            ),
            spacing="2",
            align="stretch",
            width="100%",
        ),
        class_name="detail-card",
    )


def _item_detail_body() -> rx.Component:
    item = ItemDetailState.item
    return rx.vstack(
        rx.link(
            rx.hstack(
                rx.icon("arrow-left", size=16),
                rx.text("Back to inventory"),
                spacing="1",
                align="center",
            ),
            href="/inventory/browse",
            underline="none",
            color_scheme="gray",
        ),
        rx.grid(
            rx.box(
                rx.image(
                    src=item["crop_url"],
                    width="100%",
                    object_fit="contain",
                    border_radius="0.75em",
                    key=item["id"].to(str),
                    loading="eager",
                ),
                width="100%",
            ),
            rx.vstack(
                rx.heading(item["name"], size="8", line_height="1.1"),
                rx.hstack(
                    rx.badge(
                        item["category"], color_scheme="indigo", variant="soft"
                    ),
                    rx.cond(
                        item["for_sale_bool"],
                        rx.badge(
                            "For sale", color_scheme="green", variant="solid"
                        ),
                        rx.fragment(),
                    ),
                    spacing="2",
                    wrap="wrap",
                ),
                rx.divider(margin_y="0.5em"),
                _detail_field("Room", item["room"]),
                _detail_field("Quantity", item["quantity"].to(str)),
                rx.cond(
                    item["value_display"],
                    _detail_field("Estimated value", item["value_display"]),
                    rx.fragment(),
                ),
                _detail_field("Added", item["created_at"]),
                rx.divider(margin_y="0.5em"),
                _detail_expiry_card(item),
                _detail_loan_card(item),
                rx.divider(margin_y="0.5em"),
                rx.hstack(
                    rx.button(
                        rx.icon("pencil", size=14),
                        "Edit",
                        on_click=InventoryEditState.open_edit(item["id"]),
                        size="3",
                    ),
                    rx.button(
                        rx.icon("trash-2", size=14),
                        "Delete",
                        on_click=ItemDetailState.delete_item,
                        color_scheme="red",
                        variant="soft",
                        size="3",
                    ),
                    spacing="2",
                ),
                spacing="3",
                align="start",
                width="100%",
            ),
            columns=rx.breakpoints(initial="1", md="2"),
            spacing="5",
            width="100%",
        ),
        spacing="4",
        align="stretch",
        width="100%",
    )


def item_detail_page() -> rx.Component:
    return layout(
        rx.fragment(
            _inventory_edit_dialog(),
            rx.cond(
                ItemDetailState.not_found,
                rx.vstack(
                    _empty(
                        "Item not found. It may have been deleted."
                    ),
                    rx.link(
                        rx.button("← Back to inventory"),
                        href="/inventory/browse",
                    ),
                    spacing="3",
                    align="start",
                ),
                _item_detail_body(),
            ),
        ),
        title="Item details",
    )


# ---- Calendar ----------------------------------------------------------------
def _calendar_event_row(ev) -> rx.Component:
    return rx.hstack(
        rx.icon(ev["icon"], size=14),
        rx.cond(
            ev["time"],
            rx.text(ev["time"], size="1", weight="bold", color_scheme="gray"),
            rx.fragment(),
        ),
        rx.text(
            ev["title"],
            size="2",
            weight="medium",
            text_decoration=rx.cond(
                ev["completed"], "line-through", "none"
            ),
        ),
        rx.cond(
            ev["detail"],
            rx.text(ev["detail"], size="1", color_scheme="gray"),
            rx.fragment(),
        ),
        rx.spacer(),
        rx.badge(ev["kind"], color_scheme=ev["color"], variant="soft"),
        spacing="2",
        align="center",
        width="100%",
    )


def _calendar_event_chip(ev) -> rx.Component:
    """Compact one-line event chip for desktop grid cells."""
    return rx.hstack(
        rx.icon(ev["icon"], size=11),
        rx.text(
            ev["title"],
            size="1",
            weight="medium",
            text_decoration=rx.cond(ev["completed"], "line-through", "none"),
            class_name="cal-chip-text",
        ),
        spacing="1",
        align="center",
        width="100%",
        class_name=f"cal-chip cal-chip-{ev['color']}",
    )


def _calendar_grid_cell(cell) -> rx.Component:
    """One day cell in the desktop month grid."""
    return rx.box(
        rx.hstack(
            rx.text(
                cell["day_num"].to(str),
                size="2",
                weight=rx.cond(cell["is_today"], "bold", "medium"),
                class_name=rx.cond(
                    cell["is_today"],
                    "cal-day-num today",
                    "cal-day-num",
                ),
            ),
            rx.spacer(),
            rx.cond(
                cell["event_count"] > 0,
                rx.text(
                    cell["event_count"].to(str),
                    size="1",
                    color_scheme="gray",
                ),
                rx.fragment(),
            ),
            spacing="1",
            align="center",
            width="100%",
        ),
        rx.vstack(
            rx.foreach(cell["events"], _calendar_event_chip),
            spacing="1",
            align="stretch",
            width="100%",
            class_name="cal-chip-stack",
        ),
        class_name=rx.cond(
            cell["is_current_month"],
            rx.cond(
                cell["is_today"],
                "cal-cell current today",
                rx.cond(
                    cell["is_weekend"],
                    "cal-cell current weekend",
                    "cal-cell current",
                ),
            ),
            "cal-cell other-month",
        ),
    )


def _calendar_mobile_day(cell) -> rx.Component:
    """Vertical card for one day on mobile."""
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.heading(cell["weekday_label"], size="3"),
                rx.cond(
                    cell["is_today"],
                    rx.badge("Today", color_scheme="indigo", variant="solid"),
                    rx.fragment(),
                ),
                spacing="2",
                align="center",
            ),
            rx.cond(
                cell["event_count"] > 0,
                rx.vstack(
                    rx.foreach(cell["events"], _calendar_event_row),
                    spacing="1",
                    align="stretch",
                    width="100%",
                ),
                rx.text(
                    "Nothing scheduled.", color_scheme="gray", size="1"
                ),
            ),
            spacing="2",
            align="stretch",
            width="100%",
        ),
        size="2",
        width="100%",
        class_name=rx.cond(cell["is_weekend"], "cal-mobile-day weekend", "cal-mobile-day"),
    )


def _calendar_weekday_header(label: str) -> rx.Component:
    return rx.box(
        rx.text(label, size="1", weight="bold", color_scheme="gray"),
        class_name="cal-weekday-header",
    )


def calendar_page() -> rx.Component:
    header = rx.hstack(
        rx.heading(CalendarState.month_label, size="5"),
        rx.spacer(),
        rx.hstack(
            rx.icon_button(
                rx.icon("chevron-left", size=18),
                on_click=CalendarState.prev_month,
                variant="soft",
                size="2",
                aria_label='Previous month',
            ),
            rx.button(
                "Today",
                on_click=CalendarState.go_to_today,
                variant="soft",
                size="2",
            ),
            rx.icon_button(
                rx.icon("chevron-right", size=18),
                on_click=CalendarState.next_month,
                variant="soft",
                size="2",
                aria_label='Next month',
            ),
            spacing="2",
            align="center",
        ),
        spacing="3",
        align="center",
        width="100%",
    )

    desktop_grid = rx.box(
        rx.grid(
            rx.foreach(CalendarState.weekday_labels, _calendar_weekday_header),
            columns="7",
            spacing="0",
            width="100%",
            class_name="cal-header-row",
        ),
        rx.grid(
            rx.foreach(CalendarState.grid_cells, _calendar_grid_cell),
            columns="7",
            spacing="0",
            width="100%",
            class_name="cal-grid",
        ),
        class_name="cal-desktop",
        width="100%",
    )

    mobile_list = rx.vstack(
        rx.foreach(CalendarState.mobile_days, _calendar_mobile_day),
        spacing="2",
        align="stretch",
        width="100%",
        class_name="cal-mobile",
    )

    return layout(
        rx.vstack(
            header,
            desktop_grid,
            mobile_list,
            spacing="3",
            align="stretch",
            width="100%",
        ),
        title="Calendar",
    )


# ---- Inventory For-Sale ------------------------------------------------------
def _for_sale_list_card(item) -> rx.Component:
    return _browse_card(item)  # same shape; deletes through Browse state path


def _for_sale_grid_card(item) -> rx.Component:
    return _grid_card(item, InventoryForSaleState.delete_item(item["id"]))


def _for_sale_compact_card(item) -> rx.Component:
    return _compact_card(item, InventoryForSaleState.delete_item(item["id"]))


def _for_sale_full_card(item) -> rx.Component:
    """Same as the browse list card but wired to the For-Sale state's delete."""
    return rx.card(
        rx.hstack(
            _item_link(
                item["id"],
                rx.box(
                    rx.image(
                        src=item["crop_url"],
                        width="200px",
                        height="200px",
                        object_fit="cover",
                        key=item["id"].to(str),
                        loading="eager",
                    ),
                    _qty_overlay(item["quantity"]),
                    class_name="inv-photo-wrap",
                ),
            ),
            rx.vstack(
                _item_link(
                    item["id"],
                    rx.heading(item["name"], size="6", line_height="1.2"),
                ),
                rx.hstack(
                    rx.badge(
                        item["category"], color_scheme="indigo", variant="soft"
                    ),
                    rx.cond(
                        item["value_display"],
                        rx.badge(
                            item["value_display"],
                            color_scheme="gray",
                            variant="soft",
                        ),
                        rx.fragment(),
                    ),
                    rx.badge("For sale", color_scheme="green", variant="solid"),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                _meta_line("map-pin", item["room"]),
                _meta_line("clock", item["created_at"]),
                rx.spacer(),
                _item_actions(
                    item["id"], InventoryForSaleState.delete_item(item["id"])
                ),
                spacing="3",
                align="start",
                flex="1",
                height="100%",
                padding_y="0.25em",
            ),
            spacing="4",
            align="stretch",
            width="100%",
        ),
        class_name="inv-card",
        size="3",
        width="100%",
    )


def inventory_for_sale_page() -> rx.Component:
    return layout(
        rx.fragment(
            _inventory_edit_dialog(),
            rx.vstack(
                # Stat strip
                rx.hstack(
                    rx.box(
                        rx.text("Listed", class_name="inv-stat-label"),
                        rx.text(
                            InventoryForSaleState.total_count,
                            class_name="inv-stat-value",
                        ),
                        class_name="inv-stat-card",
                    ),
                    rx.box(
                        rx.text("Total value", class_name="inv-stat-label"),
                        rx.text(
                            InventoryForSaleState.total_value_display,
                            class_name="inv-stat-value",
                        ),
                        class_name="inv-stat-card",
                    ),
                    rx.spacer(),
                    _view_mode_switcher(InventoryForSaleState),
                    spacing="3",
                    align="stretch",
                    wrap="wrap",
                    width="100%",
                ),
                rx.hstack(
                    rx.icon("arrow-up-down", size=16),
                    rx.select(
                        InventoryForSaleState.sort_options,
                        value=InventoryForSaleState.sort_by,
                        on_change=InventoryForSaleState.set_sort,
                        size="3",
                    ),
                    spacing="2",
                    align="center",
                ),
                rx.cond(
                    InventoryForSaleState.items,
                    rx.match(
                        InventoryForSaleState.view_mode,
                        (
                            "grid",
                            rx.grid(
                                rx.foreach(
                                    InventoryForSaleState.items,
                                    _for_sale_grid_card,
                                ),
                                columns=rx.breakpoints(
                                    initial="2", sm="3", md="4"
                                ),
                                spacing="3",
                                width="100%",
                            ),
                        ),
                        (
                            "compact",
                            rx.vstack(
                                rx.foreach(
                                    InventoryForSaleState.items,
                                    _for_sale_compact_card,
                                ),
                                spacing="2",
                                align="stretch",
                                width="100%",
                            ),
                        ),
                        rx.vstack(
                            rx.foreach(
                                InventoryForSaleState.items,
                                _for_sale_full_card,
                            ),
                            spacing="3",
                            align="stretch",
                            width="100%",
                        ),
                    ),
                    _empty(
                        "Nothing's marked for sale right now. Open an "
                        "item and tick 'For sale' to list it here."
                    ),
                ),
                spacing="4",
                align="stretch",
                width="100%",
            ),
        ),
        title="For sale",
    )


# ---- Inventory Food ----------------------------------------------------------
def _food_grid_card(item) -> rx.Component:
    return _grid_card(item, InventoryFoodState.delete_item(item["id"]))


def _food_compact_card(item) -> rx.Component:
    return _compact_card(item, InventoryFoodState.delete_item(item["id"]))


def _food_full_card(item) -> rx.Component:
    """Same shape as browse list card, wired to the Food state's delete."""
    return _browse_card(item)


def inventory_food_page() -> rx.Component:
    return layout(
        rx.fragment(
            _inventory_edit_dialog(),
            rx.vstack(
                rx.hstack(
                    rx.box(
                        rx.text("Food items", class_name="inv-stat-label"),
                        rx.text(
                            InventoryFoodState.total_count,
                            class_name="inv-stat-value",
                        ),
                        class_name="inv-stat-card",
                    ),
                    rx.spacer(),
                    _view_mode_switcher(InventoryFoodState),
                    spacing="3",
                    align="stretch",
                    wrap="wrap",
                    width="100%",
                ),
                rx.hstack(
                    rx.icon("arrow-up-down", size=16),
                    rx.select(
                        InventoryFoodState.sort_options,
                        value=InventoryFoodState.sort_by,
                        on_change=InventoryFoodState.set_sort,
                        size="3",
                    ),
                    spacing="2",
                    align="center",
                ),
                rx.cond(
                    InventoryFoodState.items,
                    rx.match(
                        InventoryFoodState.view_mode,
                        (
                            "grid",
                            rx.grid(
                                rx.foreach(
                                    InventoryFoodState.items,
                                    _food_grid_card,
                                ),
                                columns=rx.breakpoints(
                                    initial="2", sm="3", md="4"
                                ),
                                spacing="3",
                                width="100%",
                            ),
                        ),
                        (
                            "compact",
                            rx.vstack(
                                rx.foreach(
                                    InventoryFoodState.items,
                                    _food_compact_card,
                                ),
                                spacing="2",
                                align="stretch",
                                width="100%",
                            ),
                        ),
                        rx.vstack(
                            rx.foreach(
                                InventoryFoodState.items,
                                _food_full_card,
                            ),
                            spacing="3",
                            align="stretch",
                            width="100%",
                        ),
                    ),
                    _empty(
                        "No food items tracked yet. Capture pantry / spice "
                        "photos to see them here."
                    ),
                ),
                spacing="4",
                align="stretch",
                width="100%",
            ),
        ),
        title="Food inventory",
    )


# ---- Help page ---------------------------------------------------------------
def help_page() -> rx.Component:
    """Two-tab Help page: end-user guides + application documentation.
    Content is rendered as markdown for readable section formatting.
    Lives at /help (added to app.add_page in house_demo.py)."""
    user_md = """
## Getting started

Sign in at **/login** with the username + password your admin set up. First-time admin: see the `app_settings` notes from your operator. Sessions are cookie-backed and last 30 days unless you sign out.

GYST works in any modern browser and installs as a PWA on Android/iOS: open the menu in Chrome and pick "Install app" (Android) or "Add to Home Screen" (iOS).

---

## Adding items to inventory

Three ways to add an item:

**Take a photo (in-page camera)** — On the Add items page, tap **Take photo**. Point at the items, tap the snapshot button. The captured frame is sent to the recognizer; identified items appear in a summary list under the photo, with quantity +/- and trash icons for editing. Save when done.

**Pick from gallery** — Tap **Pick from gallery**. A file picker opens; the photo appears immediately, identification runs in the background, items populate as they're recognized. No page reload.

**Scan a barcode** — Tap **Scan barcode**. Aim at a UPC, EAN, or ISBN. GYST checks Open Food Facts → UPCitemdb → Open Library in order. On a hit, the item name, image, and estimated value (converted to your locale currency) auto-fill. Tap **Add**. No-match scans can still be added — they get saved with the raw code as the name so you can edit it later.

Choose a room from the dropdown above the buttons before adding. New rooms can be created from Settings → Rooms.

---

## Browsing, searching, deleting

- **Search** (`/inventory/search`) — full-text across name, category, notes.
- **Browse** (`/inventory/browse`) — filter by room, category, for-sale status, and sort. Per-room chips at the top double as quick counts.
- **Food** (`/inventory/food`) — items in the pantry/fridge/spice categories only.
- **For sale** (`/inventory/for-sale`) — items flagged as for sale, with estimated value totals.
- **Trash** (`/inventory/trash`) — soft-deleted items. Restore or permanently delete from here.

Tap an item to open detail/edit. Tap the trash icon on any list to soft-delete (the item moves to Trash, recoverable for 30 days). Deletes are optimistic — the row disappears immediately and an Undo toast appears for a few seconds.

---

## Chores and tasks

`/chores/tasks` — list of open and completed tasks. Tap to mark complete, optionally attach a proof photo. Add new tasks at `/chores/add` with a person to assign, a due date, and an optional recurrence (daily/weekly/monthly).

People (assignees) are managed in Settings → Rooms (originally a "users" but reused as the people list).

---

## Groceries, meals, food (one section)

The sidebar's **Food** section ties three things together:

- **Pantry** — your current food inventory.
- **Shopping list** — what you still need to buy. Tick items to mark them purchased; they auto-archive.
- **Meal plan** — scheduled meals + a saved-recipe library.

The integration: on the Meal plan page, each cookable-recipe card shows how many of its ingredients you have vs. don't. Tap **Add missing to shopping list** and the missing ones flow straight into the shopping list, tagged with the recipe they came from.

Add meals at `/meals/add`, add a grocery at `/groceries/add` or via Jarvis voice.

---

## Notes

Quick: type a title in the box at the top of `/notes`, press Enter. Done.

Longer notes: type a body too. Use the **mic icon** in the body field to dictate (Android Chrome / Chrome / Safari; not Firefox). The **Polish with AI** button rewrites the body for clarity using your configured LLM provider.

Pin a note to keep it at the top of the list.

---

## Appointments

`/appointments` — upcoming events. Add at `/appointments/add` with title, date/time, location, attendees, and optional notes. The home greeting page surfaces appointments within the next 24 hours.

---

## Talking to JARVIS

Three ways:

**Omnibox (top of every page)** — type a question or command. Try:
- "What's expiring in the fridge?"
- "Add take out the trash tomorrow to my tasks"
- "Move all items from default to office"
- "What do I have in the kitchen?"

**Voice on the omnibox** — tap the mic, speak, release. The first time, Android pops a permission prompt. If you tap the **🔊 speaker** toggle next to the mic, Jarvis speaks its replies aloud — and after each spoken reply the mic auto-reopens, closing the loop into a back-and-forth conversation.

**Full chat at /chat** — same engine, conversation history visible, "Continue in chat" works from any omnibox reply.

Jarvis has 40+ tools — read, write, update, delete across inventory, tasks, groceries, meals, notes, appointments, announcements. It also has `remember(key, value)` for facts about the household it should keep in mind across sessions.

---

## Voice tips

- **It's blocked** — if the mic toggle says "Microphone permission denied," go to your phone's app settings (long-press the GYST icon → App info → Permissions → Microphone → Allow). On a regular Chrome tab you can use the padlock instead.
- **It's not hearing me** — check that you're on HTTPS (`https://gyst.local/...`); Web Speech doesn't work on plain HTTP. Verify with the status banner: it should say "Listening…" while you talk.
- **No final transcript** — some Android Chrome PWA shells stream interim text but never fire a final result. Tap the mic again to force-end and submit what was heard.

---

## Settings

`/settings` (admins only):

- **Users** — create accounts, assign roles, scope permissions.
- **Rooms** — manage rooms; rename, delete, set sort order.
- **Announcements** — broadcast household messages with a pinned-state.
- **API** — pick LLM provider (Anthropic or OpenAI), enter API keys, choose model defaults, toggle the OWL-ViT detector.
- **Audit** — log of who did what.
- **Appearance** — currency (16 supported) and time zone for the greeting + price formatting.

---

## Installing as a PWA

Android Chrome will prompt to install after a few visits, or you can pick "Install app" from the menu. iOS Safari: share sheet → "Add to Home Screen."

Once installed:
- Receives push notifications (subscribe in Settings → API → Push test).
- Share photos to GYST from any other app's share sheet — GYST captures them as inventory items.
- Open from the home screen runs in standalone mode (no browser chrome).

---

## Backups and recovery

Soft-deleted items live in `/inventory/trash` for 30 days; restore is one tap.

For full-database recovery, your operator has access to `/var/backups/gyst-prod/code-YYYYMMDD-HHMMSS.tgz` snapshots taken at each prod deploy.
"""
    app_md = """
## Architecture

GYST is a **Reflex 0.9** single-page Python application. Reflex compiles Python state and components into a React frontend + an asyncio backend over WebSockets. The backend is served by **Granian** (Rust-based ASGI server). All traffic is fronted by **Caddy** with `tls internal` self-signed certificates.

### Process layout

- `gyst-prod.service` — production Reflex/Granian backend on `127.0.0.1:3002`
- `gyst-dev.service` — sandbox copy of prod on `127.0.0.1:3003`
- `caddy.service` — reverse proxy on `:443` (prod), `:8443` (dev), `:80` → HTTPS redirect

Code lives at `/opt/house-inventory` (dev) and `/opt/gyst-prod` (prod). The dev → prod promotion script `deploy/sync-to-prod.sh` rsyncs code, snapshots prod into `/var/backups/gyst-prod/`, then restarts the prod service.

---

## Reverse proxy + headers

Caddyfile at `/etc/caddy/Caddyfile`. A shared `(reverseproxy)` snippet handles:

- TLS termination with `tls internal`
- zstd/gzip compression
- Per-bucket cache-control:
  - `/assets/*` (fingerprinted JS/CSS) → `max-age=31536000, immutable`
  - `/icons/*`, `/manifest.webmanifest`, `/favicon.ico` → `max-age=86400, must-revalidate`
  - `/sw.js`, `/pwa-register.js` → `no-cache, no-store, must-revalidate`
  - Everything else (HTML, API) → `no-store, no-cache, must-revalidate, private`
- Security headers:
  - `Content-Security-Policy` (no scheme wildcards, `connect-src 'self' wss://gyst.local ws://gyst.local`)
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains`
  - `Permissions-Policy: camera=(self), microphone=(self), geolocation=(), ...`
  - `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`

---

## Data stores

All SQLite, one DB per concern:

| Module | DB file | Tables |
|---|---|---|
| `inventory` | items.db | items, photos, history, rooms |
| `notes` | notes.db | notes, memories (Jarvis remember()) |
| `chores` | chores.db | tasks, completions, people |
| `groceries` | groceries.db | groceries (with `from_meal_id` link) |
| `meals` | meals.db | meals, recipes |
| `appointments` | appointments.db | appointments |
| `announcements` | announcements.db | announcements |
| `auth` | auth.db | users, sessions, permissions |
| `app_settings` | settings.db | locale, API keys, provider choice |
| `audit` | audit.db | actor + action + timestamp log |
| `push` | push.db | VAPID subscriptions |

Inventory items are **soft-deleted** (timestamped `deleted_at`); the recently-deleted view is `/inventory/trash`.

---

## LLM integration

`assistant/chat.py` + `assistant/tools.py` define the agent loop. Two providers supported, chosen from Settings → API:

- **Anthropic** (Claude). Default model: `claude-haiku-4-5`. Sonnet/Opus selectable.
- **OpenAI**. Default: `gpt-4o-mini`.

The tool surface (40+ tools) covers list/create/update/delete on every entity, plus `now()`, `bulk_move_room`, `move_item_to_room`, `remember`, and `push_notify`. The system prompt is in `assistant/chat.py:_jarvis_system_prompt`.

Recognition (photo → items) uses the same provider in vision mode. Optional OWL-ViT detector toggle for object counting (off by default since LLM vision counts are usually close enough and OWL adds 2-5s per call).

Currency conversion via the Frankfurter FX API (`api.frankfurter.dev`), 24h cached per-currency.

---

## Barcode pipeline

Browser-side (`assets/barcode.js`):
1. Try **native `BarcodeDetector`** if the browser supports it (Chrome/Edge/Safari iOS 17+).
2. Fall back to **ZXing** loaded locally from `/zxing.min.js` (no public-CDN dependency).
3. On hit, capture a still frame and pause the video stream.

Lookup chain (server-side, via `/api/scan-product`):
1. **Open Food Facts** (`world.openfoodfacts.org/api/v3/`) for food/grocery items.
2. **UPCitemdb** for general consumer goods.
3. **Open Library** for ISBNs/books.

Returns `{name, image_url, est_price_usd, category, source}`. Server fetches the product image via an SSRF-guarded host allow-list (`images.openfoodfacts.org`, `images.upcitemdb.com`, etc.) and converts USD → user currency.

---

## Authentication & authorization

- **PBKDF2-SHA256, 600,000 iterations** for password hashing (`auth/db.py:hash_password`).
- 30-day session cookies, HttpOnly + Secure + SameSite=Lax.
- Role-based scoping: admin / read-inventory / write-inventory / read-chores / write-chores / etc. (`auth/scopes.py`).
- Every page's `on_load` calls `_require_auth(self, read="<scope>")` — denied requests redirect to `/login` with the requested-path query so login can return them.

Permissions get scrubbed cross-module on the home dashboard: a user with no inventory read scope sees the home page with inventory cards stripped, not a partial broken layout.

---

## PWA layer

- `assets/manifest.webmanifest` declares app identity, icons, theme color, share_target.
- `assets/sw.js` is the service worker. Currently runs in `NETWORK_ONLY = true` mode — transparent pass-through to the network. This avoids stale-bundle incidents on phones (fingerprinted /assets/* already have `immutable` cache so an SW cache layer adds no value).
- `assets/pwa-register.js` registers the SW, drives subscribe/unsubscribe/test for VAPID push (Settings → API → Push), and auto-self-heals on build mismatch via the build-version banner.
- **Share target**: receiving photos and text from other apps' share sheets is handled by `/share-target` (writes a temp file + cookie pointer) → `/share-handoff` (lets user route to inventory / note / grocery / task).

Push uses VAPID. Subscriptions stored in `push.db`. `notify_users(kind, title, body)` checks per-(user, kind) cooldowns before sending.

---

## Security model

The security suite at `tests/test_security_review.py` enforces 34 invariants (F1-F8). Runs from `/opt/house-inventory` via `.venv/bin/python tests/test_security_review.py`. Stdlib-only — no pytest dependency.

- **F1**: Path traversal protection on `gyst_shared_photo` cookie. Cookie values that resolve outside `<PHOTOS_DIR>/shared/` are rejected via `_is_safe_shared_photo_path`.
- **F2**: Upload size cap (default 10 MB). Enforced both pre-read (Content-Length) and post-read.
- **F3**: Origin / Referer check on POST endpoints to thwart CSRF.
- **F4**: `X-Content-Type-Options: nosniff` on all photo responses.
- **F5**: LLM rate limit — per-user buckets, prevents abuse.
- **F6**: Orphan shared-photo cleanup — deletes shared-target temp files past 1h max age.
- **F7**: Cross-module permission scrubbing on the home dashboard.
- **F8**: ZAP-remediation regression-locks (HSTS present, no CSP scheme wildcards, HTML `no-store`, /assets/* cacheable).

Other guards:
- SSRF allow-list for outbound image fetches (`_PRODUCT_IMAGE_HOSTS`).
- `_save_oriented_jpeg` strips EXIF + re-encodes to limit pixel-bomb attacks.
- LLM rate limit at 30/min per user with sliding window.
- Capture upload endpoint checks Origin + size before reading.

---

## Build + deploy workflow

1. Edit code in `/opt/house-inventory`.
2. Bump `BUILD_VERSION` in `layout.py`, `pwa-register.js`, `sw.js` (same value across all three — the banner self-heal uses this to detect mismatch).
3. `sudo systemctl restart gyst-dev` (sandbox on `:8443`).
4. Run security suite: `cd /opt/house-inventory && PYTHONPATH=. .venv/bin/python tests/test_security_review.py`. Must be 34/34.
5. `sudo /opt/house-inventory/deploy/sync-to-prod.sh` — rsyncs to `/opt/gyst-prod`, snapshots into `/var/backups/gyst-prod/code-YYYYMMDD-HHMMSS.tgz`, restarts `gyst-prod`.
6. Re-run security suite on `/opt/gyst-prod` against prod port — must still be 34/34.

Rollback: `sudo tar -xzf /var/backups/gyst-prod/code-<timestamp>.tgz -C /opt && sudo systemctl restart gyst-prod`.

---

## File layout (root)

```
/opt/house-inventory/                   # dev tree
├── house_demo/                         # Reflex app
│   ├── house_demo/
│   │   ├── house_demo.py               # entry: routes, app.add_page
│   │   ├── layout.py                   # sidebar, omnibox, layout()
│   │   ├── pages.py                    # every page() function
│   │   ├── states.py                   # every rx.State subclass
│   │   └── config.py                   # categories, meal types, rooms, paths
│   └── assets/                         # static: JS, CSS, manifest, icons
├── inventory/, notes/, chores/,        # one module per concern; each has db.py
├── groceries/, meals/, appointments/,
├── announcements/, auth/, app_settings/, audit/, push/
├── assistant/                          # JARVIS: chat.py + tools.py
├── tests/test_security_review.py       # 34 invariant suite
├── deploy/sync-to-prod.sh
└── .venv/                              # uv-managed virtualenv
```

---

## Operational tips

- **Watch live logs**: `sudo journalctl -u gyst-prod -f`
- **Check ports**: `ss -tlnp | grep -E ':(80|443|3002|3003|8443)'`
- **Force SW refresh on a stuck phone**: bump the build version + visit `/?nocache=<rand>`; the auto-self-heal in `pwa-register.js` clears the SW cache when build mismatches.
- **Manual test of security headers**: `curl -kis --resolve gyst.local:443:127.0.0.1 https://gyst.local/ | grep -iE "csp|hsts|cache-control"`
- **Reset a user password**: edit `auth/db.py` with `set_password(user_id, new_password)` from a `python -m` shell.

---

## Known limitations

- Web Speech API requires HTTPS (which we have) and an internet connection (Chrome's recognizer round-trips through Google's cloud). Offline voice would need a local Whisper model — not currently wired.
- Android PWA share-target receives photos but iOS does not (PWA share-target is Chrome/Android only).
- The OWL-ViT detector ships in the Python venv but loads ~600MB of weights on first use. Default off.
- Web Push is supported on Android Chrome / desktop Chrome/Edge/Firefox. Not yet supported on iOS PWA pre-iOS 16.4; on 16.4+ requires the PWA to be installed (not just bookmarked).
"""
    return layout(
        rx.box(
            rx.vstack(
                rx.heading("Help & Documentation", size="6"),
                rx.text(
                    "Everything you need to use, run, or extend GYST.",
                    size="2", color_scheme="gray",
                ),
                rx.tabs.root(
                    rx.tabs.list(
                        rx.tabs.trigger("Using GYST", value="user"),
                        rx.tabs.trigger("Application Documentation", value="app"),
                    ),
                    rx.tabs.content(
                        rx.box(
                            rx.markdown(user_md),
                            class_name="help-body",
                        ),
                        value="user",
                    ),
                    rx.tabs.content(
                        rx.box(
                            rx.markdown(app_md),
                            class_name="help-body",
                        ),
                        value="app",
                    ),
                    default_value="user",
                    width="100%",
                ),
                spacing="3",
                align="stretch",
                width="100%",
                max_width="60em",
                margin="0 auto",
            ),
            padding="0.5em",
            width="100%",
        ),
        title="Help",
    )

