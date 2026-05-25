"""House App — entry point.

Multi-tool home app. Each tool lives in its own subpackage:
  - inventory/   photo-based item cataloging
  - chores/      tasks assigned to household members

Run: `streamlit run app.py`
"""

from __future__ import annotations

import streamlit as st

import config
from chores import ui as chores_ui
from inventory import ui as inventory_ui


def page_home() -> None:
    st.title("🏠 House App")
    st.caption("Pick a tool from the sidebar, or jump in below.")

    st.divider()
    cols = st.columns(2)

    with cols[0]:
        st.subheader("📦 Inventory")
        st.write(
            "Photograph rooms and bins; the app identifies items, counts them, "
            "and stores them by location so you can find things later."
        )
        if st.button("Go to Capture →", use_container_width=True):
            st.session_state["_jump"] = "Capture"
            st.rerun()

    with cols[1]:
        st.subheader("✅ Chores")
        st.write(
            "Track household tasks and assign them to people. Due dates, "
            "completion status, per-person filters."
        )
        if st.button("Go to Tasks →", use_container_width=True):
            st.session_state["_jump"] = "Tasks"
            st.rerun()


def main() -> None:
    st.set_page_config(page_title="House App", layout="wide")

    home = st.Page(page_home, title="Home", icon="🏠", default=True, url_path="home")

    inv_capture = st.Page(
        inventory_ui.page_capture, title="Capture", icon="📸", url_path="inv_capture"
    )
    inv_search = st.Page(
        inventory_ui.page_search, title="Search", icon="🔍", url_path="inv_search"
    )
    inv_browse = st.Page(
        inventory_ui.page_browse, title="Browse", icon="📋", url_path="inv_browse"
    )

    chr_tasks = st.Page(
        chores_ui.page_tasks, title="Tasks", icon="✅", url_path="chores_tasks"
    )
    chr_add = st.Page(
        chores_ui.page_add_task,
        title="Add task",
        icon="➕",
        url_path="chores_add",
    )
    chr_people = st.Page(
        chores_ui.page_people, title="People", icon="👥", url_path="chores_people"
    )

    nav = st.navigation(
        {
            "Home": [home],
            "📦 Inventory": [inv_capture, inv_search, inv_browse],
            "✅ Chores": [chr_tasks, chr_add, chr_people],
        }
    )

    st.sidebar.divider()
    st.sidebar.caption("House App · MVP")
    nav.run()


if __name__ == "__main__":
    main()
