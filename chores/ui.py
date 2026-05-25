"""Streamlit pages for the Chores tool.

Three public page functions wired up by the top-level app.py:
- page_tasks    — list/filter/complete tasks
- page_add_task — form to create a task
- page_people   — manage household members
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import streamlit as st

import config
from chores import db


def _assignee_chip(name: Optional[str], color: Optional[str]) -> str:
    """Inline-HTML chip showing an assignee's name with a colored dot."""
    if not name:
        return (
            "<span style='color:#888;font-style:italic'>Unassigned</span>"
        )
    swatch = (
        f"<span style='display:inline-block;width:10px;height:10px;"
        f"background:{color or '#888'};border-radius:50%;margin-right:6px;"
        f"vertical-align:middle'></span>"
    )
    return f"{swatch}<span style='vertical-align:middle'>{name}</span>"


def _due_chip(due_date: Optional[str], completed: bool) -> str:
    if not due_date or completed:
        return ""
    try:
        due = datetime.strptime(due_date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return f"<span style='color:#888'>due {due_date}</span>"
    today = date.today()
    if due < today:
        return (
            f"<span style='color:#FF4136;font-weight:600'>"
            f"⚠ overdue ({due_date})</span>"
        )
    if due == today:
        return f"<span style='color:#FF851B;font-weight:600'>due today</span>"
    delta = (due - today).days
    return f"<span style='color:#0074D9'>due in {delta} day(s)</span>"


# ---- Pages -------------------------------------------------------------------
def page_tasks() -> None:
    db.init_db()
    st.header("Tasks")

    summary = db.task_summary_by_person()
    if summary:
        cols = st.columns(min(len(summary), 6) or 1)
        for i, row in enumerate(summary):
            with cols[i % len(cols)]:
                st.markdown(
                    _assignee_chip(row["name"], row["color"]),
                    unsafe_allow_html=True,
                )
                st.caption(
                    f"{int(row['open_count'] or 0)} open · "
                    f"{int(row['done_count'] or 0)} done"
                )
        st.divider()

    people = db.list_people()
    filter_options: list[tuple[str, Optional[int]]] = [
        ("All open", None),
        ("Unassigned", 0),
    ]
    for p in people:
        filter_options.append((p["name"], int(p["id"])))
    filter_options.append(("Completed", -1))  # special sentinel

    labels = [label for label, _ in filter_options]
    chosen = st.radio("Filter", labels, horizontal=True, label_visibility="collapsed")
    chosen_val = next(v for label, v in filter_options if label == chosen)

    if chosen_val == -1:
        tasks = db.list_tasks(only_completed=True)
    else:
        tasks = db.list_tasks(assigned_to=chosen_val, include_completed=False)

    if not tasks:
        st.info("Nothing here. Add a task on the **Add task** page.")
        return

    for t in tasks:
        st.divider()
        cols = st.columns([0.5, 4, 2])
        new_state = cols[0].checkbox(
            "done",
            value=bool(t["completed"]),
            key=f"done_{t['id']}",
            label_visibility="collapsed",
        )
        if new_state != bool(t["completed"]):
            db.mark_complete(int(t["id"]), completed=new_state)
            st.rerun()

        title = t["title"]
        title_md = (
            f"~~{title}~~" if t["completed"] else f"### {title}"
        )
        cols[1].markdown(title_md)
        if t.get("description"):
            cols[1].caption(t["description"])

        chip = _assignee_chip(t.get("assignee_name"), t.get("assignee_color"))
        due = _due_chip(t.get("due_date"), bool(t["completed"]))
        meta = chip + ("&nbsp;&nbsp;·&nbsp;&nbsp;" + due if due else "")
        cols[1].markdown(meta, unsafe_allow_html=True)

        btn_row = cols[2].columns([1, 1])
        _render_edit_task(btn_row[0], t, people)
        _render_delete_task(btn_row[1], t)


def page_add_task() -> None:
    db.init_db()
    st.header("Add task")
    people = db.list_people()

    with st.form("add_task_form", clear_on_submit=True):
        title = st.text_input("Title", placeholder="e.g. take out the trash")
        description = st.text_area(
            "Notes (optional)", placeholder="Details, links, anything useful."
        )

        assignee_options: list[tuple[str, Optional[int]]] = [("Unassigned", None)]
        for p in people:
            assignee_options.append((p["name"], int(p["id"])))
        labels = [label for label, _ in assignee_options]
        chosen_label = st.selectbox("Assign to", labels)
        chosen_id = next(v for label, v in assignee_options if label == chosen_label)

        use_due = st.checkbox("Has a due date")
        due_date = st.date_input("Due date", value=date.today()) if use_due else None

        submitted = st.form_submit_button("Add task", type="primary")
        if submitted:
            if not title.strip():
                st.warning("Title can't be empty.")
            else:
                db.add_task(
                    title=title,
                    description=description or None,
                    assigned_to=chosen_id,
                    due_date=due_date.strftime("%Y-%m-%d") if due_date else None,
                )
                st.toast(f"Added: {title.strip()}")
                if not people:
                    st.info(
                        "No people yet. Add some on the **People** page so you "
                        "can assign tasks."
                    )


def page_people() -> None:
    db.init_db()
    st.header("Household members")

    people = db.list_people()
    if people:
        for p in people:
            st.divider()
            cols = st.columns([3, 2])
            cols[0].markdown(
                f"<span style='display:inline-block;width:14px;height:14px;"
                f"background:{p['color']};border-radius:50%;"
                f"margin-right:8px;vertical-align:middle'></span>"
                f"<span style='font-size:1.2em;vertical-align:middle'>{p['name']}</span>",
                unsafe_allow_html=True,
            )
            cols[0].caption(
                f"Added {p['created_at']} · "
                f"{db.person_task_count(int(p['id']))} task(s) assigned"
            )
            btn_row = cols[1].columns([1, 1])
            _render_edit_person(btn_row[0], p)
            _render_delete_person(btn_row[1], p)
    else:
        st.info("No household members yet. Add one below.")

    st.divider()
    st.subheader("Add a person")
    with st.form("add_person_form", clear_on_submit=True):
        name = st.text_input("Name")
        color = st.selectbox(
            "Color",
            config.PERSON_COLORS,
            format_func=lambda c: c,
        )
        submitted = st.form_submit_button("Add", type="primary")
        if submitted:
            cleaned = name.strip()
            if not cleaned:
                st.warning("Name can't be empty.")
            else:
                try:
                    db.add_person(cleaned, color)
                    st.toast(f"Added: {cleaned}")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not add: {exc}")


# ---- Edit / Delete helpers ---------------------------------------------------
def _render_edit_task(container, task: dict, people: list[dict]) -> None:
    task_id = int(task["id"])
    with container.popover("✏️ Edit", use_container_width=False):
        new_title = st.text_input(
            "Title", value=task["title"], key=f"et_title_{task_id}"
        )
        new_desc = st.text_area(
            "Notes",
            value=task.get("description") or "",
            key=f"et_desc_{task_id}",
        )
        options: list[tuple[str, Optional[int]]] = [("Unassigned", None)]
        for p in people:
            options.append((p["name"], int(p["id"])))
        labels = [label for label, _ in options]
        current_id = task.get("assigned_to")
        try:
            current_idx = next(
                i for i, (_, v) in enumerate(options) if v == current_id
            )
        except StopIteration:
            current_idx = 0
        chosen_label = st.selectbox(
            "Assign to",
            labels,
            index=current_idx,
            key=f"et_assignee_{task_id}",
        )
        chosen_id = next(v for label, v in options if label == chosen_label)

        existing_due: Optional[date]
        try:
            existing_due = (
                datetime.strptime(task["due_date"], "%Y-%m-%d").date()
                if task.get("due_date")
                else None
            )
        except (TypeError, ValueError):
            existing_due = None
        use_due = st.checkbox(
            "Has a due date",
            value=existing_due is not None,
            key=f"et_use_due_{task_id}",
        )
        new_due = (
            st.date_input(
                "Due date",
                value=existing_due or date.today(),
                key=f"et_due_{task_id}",
            )
            if use_due
            else None
        )

        if st.button("Save", key=f"et_save_{task_id}", type="primary"):
            cleaned = new_title.strip()
            if not cleaned:
                st.warning("Title can't be empty.")
            else:
                db.update_task(
                    task_id,
                    cleaned,
                    new_desc or None,
                    chosen_id,
                    new_due.strftime("%Y-%m-%d") if new_due else None,
                )
                st.toast(f"Updated: {cleaned}")
                st.rerun()


def _render_delete_task(container, task: dict) -> None:
    task_id = int(task["id"])
    with container.popover("🗑️ Delete", use_container_width=False):
        st.write(f"Delete task **{task['title']}**?")
        if st.button(
            "Yes, delete", key=f"dt_confirm_{task_id}", type="primary"
        ):
            db.delete_task(task_id)
            st.toast(f"Deleted: {task['title']}")
            st.rerun()


def _render_edit_person(container, person: dict) -> None:
    person_id = int(person["id"])
    with container.popover("✏️ Edit", use_container_width=False):
        new_name = st.text_input(
            "Name", value=person["name"], key=f"ep_name_{person_id}"
        )
        try:
            color_idx = config.PERSON_COLORS.index(person["color"])
        except ValueError:
            color_idx = 0
        new_color = st.selectbox(
            "Color",
            config.PERSON_COLORS,
            index=color_idx,
            key=f"ep_color_{person_id}",
        )
        if st.button(
            "Save", key=f"ep_save_{person_id}", type="primary"
        ):
            cleaned = new_name.strip()
            if not cleaned:
                st.warning("Name can't be empty.")
            else:
                db.update_person(person_id, cleaned, new_color)
                st.toast(f"Updated: {cleaned}")
                st.rerun()


def _render_delete_person(container, person: dict) -> None:
    person_id = int(person["id"])
    count = db.person_task_count(person_id)
    with container.popover("🗑️ Delete", use_container_width=False):
        st.write(f"Delete **{person['name']}**?")
        if count:
            st.caption(
                f"{count} task(s) assigned to them will become **Unassigned**."
            )
        if st.button(
            "Yes, delete", key=f"dp_confirm_{person_id}", type="primary"
        ):
            db.delete_person(person_id)
            st.toast(f"Deleted: {person['name']}")
            st.rerun()
