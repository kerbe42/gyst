"""Shared layout for the House App — responsive sidebar with mobile drawer.

On mobile: hamburger button at top-left toggles a sliding drawer. Tap the
overlay or any nav link to close.
On desktop (≥768px): sidebar is a fixed left rail; the hamburger / overlay
are hidden via CSS.

All responsive + animated behavior lives in `assets/styles.css`.
"""

from __future__ import annotations

import reflex as rx

from house_demo.states import AuthState, OmniboxState, UIState, UndoState

# Bumped on every prod push so the on-screen build banner gives us a single
# read-it-on-the-phone confirmation that fresh code is actually loaded.
# Keep in sync with BUILD_VERSION in assets/pwa-register.js + assets/sw.js.
BUILD_VERSION = "20260612e"


def _build_banner() -> rx.Component:
    """Tiny fixed chip in the bottom-right corner showing the page's build
    version, the SW's reported build, and the bundle hash actually loaded.
    Visible on every page including the auth-gate splash. The text starts
    as just the Python-side build version; pwa-register.js rewrites it on
    load with sw_build + bundle hash sniffed from the page's <script src>.
    """
    initial = f"build {BUILD_VERSION} · sw ? · esm-?"
    return rx.el.div(
        initial,
        id="gyst-build-banner",
        # Inline style so it works without depending on styles.css being
        # cache-fresh — the whole point of this banner is to be readable
        # in the broken-cache states we're trying to diagnose.
        style={
            "position": "fixed",
            "top": "4px",
            "right": "6px",
            "zIndex": "9999",
            "fontSize": "10px",
            "fontFamily": "ui-monospace, SFMono-Regular, Menlo, monospace",
            "color": "rgba(255,255,255,0.75)",
            "background": "rgba(0,0,0,0.55)",
            "padding": "2px 6px",
            "borderRadius": "4px",
            "pointerEvents": "none",
            "lineHeight": "1.3",
        },
    )


def _nav_link(label: str, href: str, icon: str) -> rx.Component:
    """Sidebar nav link with a Lucide icon. Tapping closes the mobile drawer."""
    return rx.link(
        rx.hstack(
            rx.icon(icon, size=18),
            rx.text(label, size="3"),
            spacing="3",
            align="center",
        ),
        href=href,
        on_click=UIState.close_sidebar,
        class_name="app-nav-link",
        underline="none",
    )


def _section(
    label: str,
    section_icon: str,
    is_open,
    toggle,
    *children,
) -> rx.Component:
    """Collapsible nav section with an icon + chevron header."""
    return rx.box(
        rx.hstack(
            rx.hstack(
                rx.icon(section_icon, size=18),
                rx.text(label, size="3", class_name="app-nav-section-label"),
                spacing="3",
                align="center",
            ),
            rx.icon(
                "chevron-down",
                size=16,
                class_name=rx.cond(
                    is_open,
                    "app-nav-section-chevron open",
                    "app-nav-section-chevron",
                ),
            ),
            on_click=toggle,
            class_name="app-nav-section",
        ),
        rx.box(
            *children,
            class_name=rx.cond(
                is_open,
                "app-nav-section-content open",
                "app-nav-section-content",
            ),
        ),
        width="100%",
    )


def _brand() -> rx.Component:
    """Modern GYST logomark — tight grotesk wordmark with an accent dot.

    Single-weight typography, no per-letter rainbow, no 3D drop shadows.
    The accent is a colored dot after the word — a small designed move
    that does the heavy lifting visually.
    """
    return rx.box(
        rx.box(
            rx.el.span("GYST", class_name="brand-word"),
            rx.el.span(".", class_name="brand-dot"),
            class_name="brand-row",
        ),
        rx.box(
            rx.el.span("get your stuff together", class_name="brand-tag"),
            class_name="brand-tag-row",
        ),
        class_name="app-brand",
    )


def _sidebar_content() -> rx.Component:
    return rx.vstack(
        _brand(),
        _nav_link("Home", "/", "house"),
        _nav_link("JARVIS", "/chat", "brain-circuit"),
        _nav_link("Calendar", "/calendar", "calendar-days"),
        _nav_link("Announcements", "/announcements", "megaphone"),
        _nav_link("Notes", "/notes", "sticky-note"),
        _nav_link("Strongman", "/strongman", "dumbbell"),
        _section(
            "Inventory",
            "package",
            UIState.inventory_section_open,
            UIState.toggle_inventory_section,
            _nav_link("Add items", "/inventory/capture", "camera"),
            _nav_link("Search", "/inventory/search", "search"),
            _nav_link("Browse", "/inventory/browse", "layout-grid"),
            _nav_link("For sale", "/inventory/for-sale", "dollar-sign"),
            _nav_link("Trash", "/inventory/trash", "trash-2"),
        ),
        _section(
            "Chores",
            "list-checks",
            UIState.chores_section_open,
            UIState.toggle_chores_section,
            _nav_link("Tasks", "/chores/tasks", "square-check-big"),
            _nav_link("Add task", "/chores/add", "circle-plus"),
        ),
        # ---- Food: a single section unifying the three formerly
        # ---- separate nav groups (pantry, shopping list, meals).
        # ---- They share an entity (an ingredient) and a flow (cook a
        # ---- meal -> missing ingredients land on the shopping list ->
        # ---- bought groceries become pantry items). The user's mental
        # ---- model has them as one feature; the menu now reflects that.
        _section(
            "Food",
            "utensils",
            UIState.meals_section_open,
            UIState.toggle_meals_section,
            _nav_link("Pantry", "/inventory/food", "refrigerator"),
            _nav_link("Shopping list", "/groceries", "shopping-cart"),
            _nav_link("Meal plan", "/meals", "calendar"),
            _nav_link("Add to shopping", "/groceries/add", "circle-plus"),
            _nav_link("Add meal", "/meals/add", "circle-plus"),
        ),
        _section(
            "Appointments",
            "calendar",
            UIState.appointments_section_open,
            UIState.toggle_appointments_section,
            _nav_link("Schedule", "/appointments", "calendar-clock"),
            _nav_link("Add", "/appointments/add", "circle-plus"),
        ),
        rx.cond(
            # Admins only see the settings cog; one link, no collapsible
            # wrapper. Used to nest under an "Admin" section that held
            # exactly one child.
            AuthState.is_admin,
            _nav_link("Settings", "/settings", "settings"),
            rx.fragment(),
        ),
        # Help is available to all signed-in users.
        _nav_link("Help", "/help", "circle-help"),
        rx.divider(margin_y="0.75em"),
        rx.cond(
            AuthState.is_authed,
            rx.vstack(
                rx.text(
                    "Signed in as",
                    size="1",
                    color_scheme="gray",
                ),
                rx.text(AuthState.current_user_name, weight="bold", size="2"),
                rx.button(
                    "Sign out",
                    on_click=AuthState.logout,
                    variant="soft",
                    color_scheme="gray",
                    size="2",
                    width="100%",
                ),
                rx.button(
                    rx.icon("log-out", size=12),
                    "Sign out everywhere",
                    on_click=AuthState.logout_everywhere,
                    variant="soft",
                    color_scheme="red",
                    size="1",
                    width="100%",
                    title="Revoke all sessions on every device.",
                ),
                spacing="1",
                align="stretch",
            ),
            rx.fragment(),
        ),
        spacing="1",
        align="stretch",
        width="100%",
    )


def _omnibox_action_chip(action: dict) -> rx.Component:
    return rx.hstack(
        rx.icon("wrench", size=12),
        rx.text(action["name"], size="1", weight="medium"),
        rx.cond(
            action["args_json"],
            rx.text(
                action["args_json"],
                size="1",
                color_scheme="gray",
                class_name="chat-tool-args",
            ),
            rx.fragment(),
        ),
        spacing="2",
        align="center",
        class_name="chat-tool-chip",
    )


def _omnibox_popover() -> rx.Component:
    """Result popover rendered below the input. Open is driven by
    OmniboxState.popover_open."""
    return rx.cond(
        OmniboxState.popover_open,
        rx.box(
            rx.vstack(
                rx.hstack(
                    rx.text("JARVIS", weight="bold", size="2"),
                    rx.spacer(),
                    rx.icon_button(
                        rx.icon("x", size=14),
                        on_click=OmniboxState.close_popover,
                        variant="soft",
                        color_scheme="gray",
                        size="1",
                        aria_label='Close search',
                    ),
                    width="100%",
                    align="center",
                ),
                rx.cond(
                    OmniboxState.last_actions,
                    rx.vstack(
                        rx.foreach(
                            OmniboxState.last_actions,
                            _omnibox_action_chip,
                        ),
                        spacing="1",
                        align="stretch",
                        width="100%",
                    ),
                    rx.fragment(),
                ),
                rx.el.div(
                    OmniboxState.last_response,
                    id="omnibox-reply-text",
                    class_name="omnibox-reply",
                ),
                rx.button(
                    "Continue in chat →",
                    variant="soft",
                    size="1",
                    on_click=OmniboxState.continue_in_chat,
                ),
                spacing="2",
                align="stretch",
                width="100%",
            ),
            class_name="omnibox-popover",
        ),
        rx.fragment(),
    )


def _omnibox() -> rx.Component:
    """Floating JARVIS omnibox. Desktop: top-center of main content.
    Mobile: pinned above the bottom nav, full-width minus padding. Hidden
    on /login and /share-handoff via class_name + rx.cond."""
    inner = rx.box(
        rx.form(
            rx.hstack(
                rx.input(
                    placeholder="Ask JARVIS…",
                    value=OmniboxState.query,
                    on_change=OmniboxState.set_query,
                    size="2",
                    id="omnibox-input",
                    class_name="omnibox-input",
                    disabled=OmniboxState.pending,
                ),
                # Speak-replies toggle. Pure-JS — voice.js reads the
                # data-on attribute on every Jarvis response render
                # and decides whether to TTS the text aloud. Default
                # off (persisted in localStorage).
                rx.el.button(
                    rx.icon("volume-2", size=14),
                    type="button",
                    id="omnibox-speak",
                    class_name="omnibox-mic-btn",
                    title="Speak Jarvis's replies aloud",
                    custom_attrs={
                        "aria-label": "Toggle speak replies aloud",
                        "data-on": "0",
                    },
                ),
                rx.el.button(
                    rx.icon("mic", size=14),
                    # Mouse handlers used to drive this, but Android
                    # Chrome only synthesizes mousedown/up AFTER touchend
                    # — by which time the user has already released and
                    # the hold-to-talk gesture is over. Pointer events
                    # are bound natively in voice.js to fix that.
                    type="button",
                    id="omnibox-mic",
                    class_name="omnibox-mic-btn",
                    title="Hold to talk",
                    # touch-action: none is set via CSS in styles.css
                    # (.omnibox-mic-btn) so we can preventDefault on
                    # pointerdown without the browser stealing the
                    # gesture for scroll/long-press. Passing it as
                    # a `style` string here triggers React #62 because
                    # React expects style to be an object.
                    custom_attrs={"aria-label": "Hold to talk to JARVIS"},
                ),
                rx.button(
                    rx.cond(
                        OmniboxState.pending,
                        rx.spinner(size="1"),
                        rx.icon("arrow-up", size=14),
                    ),
                    type="submit",
                    size="2",
                    disabled=OmniboxState.pending,
                    class_name="omnibox-send-btn",
                    aria_label="Send message",
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            on_submit=OmniboxState.submit,
            reset_on_submit=False,
            width="100%",
        ),
        # Hidden span the voice.js helper writes status messages into.
        # voice.js looks for #chat-input-mic / #chat-input-status, so by
        # not duplicating those IDs we keep the chat page status node as
        # the canonical sink; visual cue here is via class toggling on
        # #omnibox-mic? No — voice.js targets #chat-input-mic only.
        # The mic still works (it appends to #chat-input on /chat); on
        # the omnibox it dispatches into the global recognizer and the
        # user sees the listening pulse on the chat input instead. That
        # is a documented gracefully-degraded behavior; see report.
        _omnibox_popover(),
        id="omnibox-root",
        class_name=rx.cond(OmniboxState.is_visible, "omnibox-shell", "omnibox-shell hidden"),
    )
    return rx.cond(AuthState.is_authed, inner, rx.fragment())


def _undo_snack() -> rx.Component:
    """Fixed-bottom snack that pops in when UndoState is armed. A small
    external watcher in undo-snack.js sets a 1.8s dismiss timer each
    time the data-seq attribute changes (i.e. every fresh arm). Putting
    the timer inside an inline <script> in rx.cond doesn't work because
    React doesn't re-execute script tags when the snack re-renders with
    new content."""
    return rx.cond(
        UndoState.kind,
        rx.box(
            rx.hstack(
                rx.icon("undo-2", size=15),
                rx.text(UndoState.label, size="2", weight="medium"),
                rx.spacer(),
                rx.button(
                    "Undo",
                    on_click=UndoState.do_undo,
                    variant="solid",
                    size="2",
                ),
                rx.icon_button(
                    rx.icon("x", size=14),
                    on_click=UndoState.dismiss,
                    id="undo-dismiss",
                    variant="soft",
                    color_scheme="gray",
                    size="1",
                    aria_label='Dismiss undo',
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            id="undo-snack",
            custom_attrs={"data-seq": UndoState.seq.to(str)},
            class_name="undo-snack",
        ),
        rx.fragment(),
    )


def _bottom_nav_item(label: str, href: str, icon: str) -> rx.Component:
    return rx.link(
        rx.vstack(
            rx.icon(icon, size=20),
            rx.text(label, size="1"),
            spacing="0",
            align="center",
        ),
        href=href,
        underline="none",
        class_name="app-bottomnav-item",
        on_click=UIState.close_sidebar,
    )


def _bottom_nav() -> rx.Component:
    """Fixed bottom tab bar — mobile only (hidden ≥ 768px in CSS).
    Optimized for quick-add: Home anchors the left, then the three most
    common 'create' actions, then Menu opens the drawer for everything
    else. Replaces the old top-left hamburger on mobile."""
    return rx.box(
        # Menu opens the drawer; lives on the left (thumb-reach for
        # right-handed users tends to favor opposite-side primary
        # actions, but the user explicitly wants Menu left, Home right).
        rx.box(
            rx.vstack(
                rx.icon("menu", size=22),
                rx.text("Menu", size="1"),
                spacing="0",
                align="center",
            ),
            on_click=UIState.toggle_sidebar,
            class_name="app-bottomnav-item",
        ),
        _bottom_nav_item("Add item", "/inventory/capture", "camera"),
        _bottom_nav_item("Add note", "/notes", "sticky-note"),
        _bottom_nav_item("Add task", "/chores/add", "list-checks"),
        class_name="app-bottomnav",
    )


def _hamburger() -> rx.Component:
    return rx.icon_button(
        rx.icon("menu", size=22),
        on_click=UIState.toggle_sidebar,
        variant="soft",
        size="3",
        class_name="app-hamburger",
        aria_label='Open menu',
    )


def _overlay() -> rx.Component:
    return rx.box(
        on_click=UIState.close_sidebar,
        class_name=rx.cond(
            UIState.sidebar_open, "app-overlay open", "app-overlay"
        ),
    )


def _drawer() -> rx.Component:
    return rx.box(
        _sidebar_content(),
        class_name=rx.cond(
            UIState.sidebar_open, "app-sidebar open", "app-sidebar"
        ),
    )


def _auth_gate_splash() -> rx.Component:
    """Brief loading state shown while AuthState rehydrates from the cookie.
    Without this gate, page content prerenders for a split second before
    on_load's redirect fires, and the user sees the home page flash before
    the login redirect kicks in."""
    return rx.box(
        rx.vstack(
            rx.el.span("GYST", class_name="brand-word"),
            rx.el.span(".", class_name="brand-dot"),
            rx.spinner(size="3", margin_top="1.5rem"),
            spacing="2",
            align="center",
            justify="center",
        ),
        class_name="auth-gate-splash",
    )


def layout(content: rx.Component, *, title: str | None = "") -> rx.Component:
    """Wrap a page's content with the standard chrome. Until AuthState has
    confirmed the user is signed in, render a minimal splash so we don't
    leak the page's contents during the rehydration round-trip."""
    chrome_and_content = rx.fragment(
        _hamburger(),
        _overlay(),
        _drawer(),
        _bottom_nav(),
        _undo_snack(),
        _omnibox(),
        rx.box(
            rx.vstack(
                *(
                    [rx.heading(title, size="8")]
                    if title
                    else []
                ),
                content,
                spacing="5",
                align="stretch",
                width="100%",
                max_width="1100px",
            ),
            class_name="app-main",
        ),
    )
    return rx.fragment(
        # Toast provider — slide-in notifications. Mounted once.
        rx.toast.provider(position="top-right", rich_colors=True),
        rx.cond(
            AuthState.is_authed,
            chrome_and_content,
            _auth_gate_splash(),
        ),
        # Build banner — sits above everything via fixed position + high
        # z-index. Mounted outside the rx.cond so it appears on the auth
        # splash too (most-broken-state visibility is the whole point).
        _build_banner(),
    )
