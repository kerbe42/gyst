"""Tool schema + implementations for the JARVIS-style chat assistant.

Each tool is a thin wrapper around an existing per-module DB function.
The LLM picks tools based on the user's question; the chat loop executes
the chosen tool and returns the result back to the model for the next
turn.

To add a tool:
  1. Write a Python function that returns JSON-serializable data
  2. Register it in `TOOLS` with a name, description, and JSON schema
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable

import config


# ---- Tool implementations ----------------------------------------------------
# Each tool returns a dict / list / scalar that JSON-serializes cleanly.
# Errors should be caught and returned as {"error": "..."} so the model can
# react gracefully rather than crashing the whole turn.

def _safe(fn: Callable, *args, **kwargs) -> Any:
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _search_inventory(query: str, limit: int = 20) -> Any:
    from inventory import db as inv_db
    rows = inv_db.search_items(query, limit=limit)
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "category": r.get("category"),
            "quantity": r.get("quantity"),
            "room": r.get("room"),
            "for_sale": bool(r.get("for_sale")),
            "estimated_value": r.get("estimated_value"),
            "expires_at": r.get("expires_at"),
            "loaned_to": r.get("loaned_to_name"),
        }
        for r in rows
    ]


def _inventory_in_room(room: str) -> Any:
    from inventory import db as inv_db
    return [
        {"id": r["id"], "name": r["name"], "quantity": r.get("quantity")}
        for r in inv_db.items_in_room(room)
    ]


def _inventory_expiring(days: int = 7) -> Any:
    from inventory import db as inv_db
    return inv_db.items_expiring_within(int(days))


def _inventory_stats() -> Any:
    from inventory import db as inv_db
    return inv_db.inventory_stats()


def recipes_using_expiring_items(days: int = 7) -> list[dict]:
    """Plain helper: rank user recipes by how many of their ingredients are
    in the inventory's about-to-expire pile. Used by both the JARVIS tool
    and the morning briefing.
    Returns list of {recipe_name, expiring_ingredients_matched,
    total_ingredients} sorted desc by match count, then name.
    """
    from inventory import db as inv_db
    from meals import db as meals_db
    try:
        expiring = inv_db.items_expiring_within(int(days)) or []
    except Exception:
        expiring = []
    try:
        recipes = meals_db.list_recipes() or []
    except Exception:
        recipes = []
    expiring_names = [
        (e.get("name") or "").strip().lower() for e in expiring
    ]
    expiring_names = [n for n in expiring_names if n]
    out: list[dict] = []
    for r in recipes:
        ings = [str(i).strip() for i in (r.get("ingredients") or []) if i]
        matched: list[str] = []
        for ing in ings:
            ing_l = ing.lower()
            for en in expiring_names:
                if en in ing_l or ing_l in en:
                    matched.append(ing)
                    break
        out.append({
            "recipe_name": r.get("name"),
            "expiring_ingredients_matched": matched,
            "total_ingredients": len(ings),
        })
    out.sort(
        key=lambda x: (
            -len(x["expiring_ingredients_matched"]),
            (x["recipe_name"] or "").lower(),
        ),
    )
    return out


def _recipes_using_expiring_items(days: int = 7) -> Any:
    return recipes_using_expiring_items(int(days))


def _list_tasks(only_open: bool = True, assignee_name: str | None = None) -> Any:
    from chores import db as chores_db
    aid = None
    if assignee_name:
        person = next(
            (
                p for p in chores_db.list_people()
                if p["name"].lower() == assignee_name.strip().lower()
            ),
            None,
        )
        if person:
            aid = int(person["id"])
        else:
            return {"error": f"No person named {assignee_name!r}."}
    rows = chores_db.list_tasks(
        assigned_to=aid, include_completed=not only_open,
    )
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "description": r.get("description"),
            "assignee": r.get("assignee_name"),
            "due_date": r.get("due_date"),
            "completed": bool(r.get("completed")),
            "recurrence": r.get("recurrence"),
        }
        for r in rows
    ]


def _complete_task(task_id: int) -> Any:
    from chores import db as chores_db
    chores_db.mark_complete_and_advance(int(task_id))
    return {"ok": True, "completed": int(task_id)}


def _create_task(
    title: str,
    assignee_name: str | None = None,
    due_date: str | None = None,
    recurrence: str | None = None,
    description: str | None = None,
) -> Any:
    from chores import db as chores_db
    aid = None
    if assignee_name:
        person = next(
            (
                p for p in chores_db.list_people()
                if p["name"].lower() == assignee_name.strip().lower()
            ),
            None,
        )
        if person:
            aid = int(person["id"])
    new_id = chores_db.add_task(
        title=title,
        description=description,
        assigned_to=aid,
        due_date=due_date,
        recurrence=recurrence,
    )
    return {"ok": True, "id": new_id}


def _list_appointments(window_hours: int = 168) -> Any:
    """All appointments within the next `window_hours` (default 1 week)."""
    from datetime import timedelta
    from appointments import db as appt_db
    end = datetime.now() + timedelta(hours=int(window_hours))
    rows = appt_db.list_appointments(upcoming_only=True)
    out = []
    for a in rows:
        try:
            when = datetime.strptime(a["appointment_at"], "%Y-%m-%d %H:%M:%S")
        except (KeyError, ValueError):
            continue
        if when > end:
            continue
        out.append({
            "id": a["id"],
            "title": a["title"],
            "when": a["appointment_at"],
            "location": a.get("location"),
            "notes": a.get("notes"),
            "for_person": a.get("for_person"),
            "recurrence": a.get("recurrence"),
        })
    return out


def _create_appointment(
    title: str,
    when: str,
    location: str | None = None,
    notes: str | None = None,
    recurrence: str | None = None,
) -> Any:
    from appointments import db as appt_db
    if "T" in when:
        when = when.replace("T", " ")
    if len(when) == 16:  # YYYY-MM-DD HH:MM -> add seconds
        when = when + ":00"
    new_id = appt_db.add_appointment(
        title=title,
        appointment_at=when,
        location=location,
        notes=notes,
        recurrence=recurrence,
    )
    return {"ok": True, "id": new_id}


def _list_groceries(only_open: bool = True) -> Any:
    from groceries import db as groc_db
    rows = groc_db.list_groceries(include_purchased=not only_open)
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "quantity": r.get("quantity"),
            "purchased": bool(r.get("purchased")),
            "notes": r.get("notes"),
        }
        for r in rows
    ]


def _create_grocery(
    name: str, quantity: str | None = None, notes: str | None = None,
) -> Any:
    from groceries import db as groc_db
    new_id = groc_db.add_grocery(name=name, quantity=quantity, notes=notes)
    return {"ok": True, "id": new_id}


def _toggle_grocery(grocery_id: int, purchased: bool = True) -> Any:
    from groceries import db as groc_db
    groc_db.set_purchased(int(grocery_id), bool(purchased))
    return {"ok": True}


def _list_meals(upcoming_only: bool = True) -> Any:
    from meals import db as meals_db
    rows = meals_db.list_meals(upcoming_only=bool(upcoming_only))
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "date": r.get("meal_date"),
            "type": r.get("meal_type"),
            "ingredients": r.get("ingredients") or [],
        }
        for r in rows
    ]


def _create_meal(
    name: str,
    meal_date: str | None = None,
    meal_type: str | None = None,
    ingredients: list[str] | None = None,
) -> Any:
    from meals import db as meals_db
    new_id = meals_db.add_meal(
        name=name,
        meal_date=meal_date,
        meal_type=meal_type or "dinner",
        ingredients=ingredients or [],
    )
    return {"ok": True, "id": new_id}


def _list_notes(limit: int = 20) -> Any:
    from notes import db as notes_db
    rows = notes_db.list_notes()[:limit]
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "body": r.get("body"),
            "pinned": bool(r.get("pinned")),
        }
        for r in rows
    ]


def _create_note(
    title: str, body: str | None = None, pinned: bool = False,
) -> Any:
    from notes import db as notes_db
    new_id = notes_db.add_note(
        title=title, body=body, pinned=bool(pinned),
    )
    return {"ok": True, "id": new_id}


def _memory_remember(key: str, value: str) -> Any:
    """Persist a free-form fact / preference for future conversations."""
    from notes import db as notes_db
    notes_db.memory_set(key, value)
    return {"ok": True, "key": key}


def _memory_recall(key: str) -> Any:
    from notes import db as notes_db
    v = notes_db.memory_get(key)
    return {"key": key, "value": v} if v is not None else {"key": key, "value": None}


def _memory_list() -> Any:
    from notes import db as notes_db
    return notes_db.memory_list(limit=200)


def _memory_forget(key: str) -> Any:
    from notes import db as notes_db
    notes_db.memory_delete(key)
    return {"ok": True}


def _push_to_user(
    user_name: str,
    title: str,
    body: str,
    url: str = "/",
    kind: str = "assistant",
    cooldown_hours: float = 0.0,
) -> Any:
    """Send a push notification to a household member. Respects an optional
    throttle keyed on `kind` so repeat pushes don't spam.
    `kind`: short string like 'reminder', 'briefing', 'expiring'. Used for
    rate limiting; same kind to the same user can't fire more than once
    per `cooldown_hours`."""
    from chores import db as chores_db
    from notes import db as notes_db
    from notifications import db as push_db

    person = next(
        (
            p for p in chores_db.list_people()
            if p["name"].lower() == user_name.strip().lower()
        ),
        None,
    )
    if not person:
        return {"error": f"No person named {user_name!r}"}
    uid = int(person["id"])
    if cooldown_hours > 0 and not notes_db.push_throttle_check(
        kind, uid, cooldown_hours,
    ):
        return {"skipped": True, "reason": "cooldown"}
    result = push_db.send_to_user(
        user_id=uid, title=title, body=body, url=url,
    )
    if result.get("sent", 0) > 0:
        notes_db.push_throttle_record(kind, uid)
    return result


def _list_announcements() -> Any:
    from announcements import db as ann_db
    rows = ann_db.list_announcements(include_expired=False)
    return [
        {"id": r["id"], "title": r["title"], "body": r.get("body"),
         "pinned": bool(r.get("pinned"))}
        for r in rows
    ]


def _list_people() -> Any:
    from chores import db as chores_db
    rows = chores_db.list_people()
    return [{"id": p["id"], "name": p["name"]} for p in rows]


def _now() -> Any:
    """Authoritative server-side time, ISO-8601. The model often needs this
    to resolve relative time references like 'tomorrow' or 'next Tuesday'."""
    return {"now": datetime.now().isoformat(timespec="seconds")}


# ---- Tool registry: name -> (callable, json schema) -------------------------
# Schemas follow the JSON-Schema dialect that both Anthropic and OpenAI
# tool-use accept. Keep them minimal — the LLM is good at filling in.


# ---- Update / delete tools (added: full CRUD parity for JARVIS) ------------
def _update_item(item_id, name=None, quantity=None, category=None,
                 for_sale=None, estimated_value=None):
    from inventory import db as inv_db
    cur = inv_db.get_item(int(item_id))
    if not cur:
        return {"ok": False, "error": "Item not found"}
    inv_db.update_item(
        int(item_id),
        name if name is not None else cur.get("name", ""),
        int(quantity) if quantity is not None else int(cur.get("quantity", 1)),
        category if category is not None else cur.get("category", "other"),
        for_sale=for_sale if for_sale is not None else bool(cur.get("for_sale")),
        estimated_value=estimated_value if estimated_value is not None else cur.get("estimated_value"),
        actor_name="JARVIS",
    )
    return {"ok": True, "id": int(item_id)}


def _delete_item(item_id):
    from inventory import db as inv_db
    inv_db.delete_item(int(item_id), actor_name="JARVIS")
    return {"ok": True, "id": int(item_id)}


def _update_task(task_id, title=None, description=None, assigned_to=None, due_date=None):
    from chores import db as chores_db
    cur = next((t for t in chores_db.list_tasks(include_completed=True)
                if int(t["id"]) == int(task_id)), None)
    if not cur:
        return {"ok": False, "error": "Task not found"}
    chores_db.update_task(
        int(task_id),
        title if title is not None else cur.get("title", ""),
        description if description is not None else cur.get("description"),
        int(assigned_to) if assigned_to is not None else cur.get("assigned_to"),
        due_date if due_date is not None else cur.get("due_date"),
    )
    return {"ok": True, "id": int(task_id)}


def _delete_task(task_id):
    from chores import db as chores_db
    chores_db.delete_task(int(task_id))
    return {"ok": True, "id": int(task_id)}


def _delete_appointment(appointment_id):
    from appointments import db as appt_db
    appt_db.delete_appointment(int(appointment_id))
    return {"ok": True, "id": int(appointment_id)}


def _delete_grocery(grocery_id):
    from groceries import db as groc_db
    groc_db.delete_grocery(int(grocery_id))
    return {"ok": True, "id": int(grocery_id)}


def _update_note(note_id, title=None, body=None):
    from notes import db as notes_db
    notes_db.update_note(int(note_id), title=title, body=body)
    return {"ok": True, "id": int(note_id)}


def _delete_note(note_id):
    from notes import db as notes_db
    notes_db.delete_note(int(note_id))
    return {"ok": True, "id": int(note_id)}


def _list_recipes():
    from meals import db as _meals_db
    return [{"id": r["id"], "name": r["name"]} for r in _meals_db.list_recipes()]


def _delete_recipe(recipe_id):
    from meals import db as _meals_db
    _meals_db.delete_recipe(int(recipe_id))
    return {"ok": True, "id": int(recipe_id)}


def _delete_meal(meal_id):
    from meals import db as _meals_db
    _meals_db.delete_meal(int(meal_id))
    return {"ok": True, "id": int(meal_id)}


def _create_announcement(title, body=None, pinned=False):
    from announcements import db as _ann_db
    new_id = _ann_db.add_announcement(title=title, body=body, pinned=bool(pinned))
    return {"ok": True, "id": int(new_id)}


def _bulk_move_room(from_room, to_room):
    from inventory import db as inv_db
    """Move EVERYTHING currently in `from_room` to `to_room`. Returns
    a JSON-serialisable count + the rooms involved."""
    n = inv_db.bulk_move_room(str(from_room), str(to_room))
    return {"ok": True, "moved": int(n), "from": str(from_room), "to": str(to_room)}


def _move_item_to_room(item_id, target_room):
    from inventory import db as inv_db
    inv_db.move_item_to_room(int(item_id), str(target_room))
    return {"ok": True, "id": int(item_id), "to": str(target_room)}



def _delete_announcement(announcement_id):
    from announcements import db as _ann_db
    _ann_db.delete_announcement(int(announcement_id))
    return {"ok": True, "id": int(announcement_id)}


TOOLS: dict[str, dict] = {
    "now": {
        "fn": _now,
        "description": (
            "Get the current server-side date and time. ALWAYS call this "
            "first when the user mentions relative times like 'today', "
            "'tomorrow', 'next week', 'in 2 hours'."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    "list_people": {
        "fn": _list_people,
        "description": "List all household members (name + id).",
        "input_schema": {"type": "object", "properties": {}},
    },
    "search_inventory": {
        "fn": _search_inventory,
        "description": (
            "Find inventory items by partial name match. Use this for "
            "'do we have X?', 'where is my Y?', 'what's in the kitchen?' "
            "style questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
    },
    "inventory_in_room": {
        "fn": _inventory_in_room,
        "description": "List every active inventory item in a given room.",
        "input_schema": {
            "type": "object",
            "properties": {"room": {"type": "string"}},
            "required": ["room"],
        },
    },
    "inventory_expiring": {
        "fn": _inventory_expiring,
        "description": (
            "List inventory items expiring within N days (default 7)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "default": 7}},
        },
    },
    "recipes_using_expiring_items": {
        "fn": _recipes_using_expiring_items,
        "description": (
            "Suggest user-saved recipes that use food items expiring "
            "within N days (default 7). Returns recipes ranked by the "
            "number of expiring ingredients they consume. Use when the "
            "user asks 'what should I cook?' or to proactively reduce "
            "food waste."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "default": 7}},
        },
    },
    "inventory_stats": {
        "fn": _inventory_stats,
        "description": (
            "Top-level inventory stats: total items, total value, etc."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    "list_tasks": {
        "fn": _list_tasks,
        "description": (
            "List chores/tasks. Use only_open=false to include completed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "only_open": {"type": "boolean", "default": True},
                "assignee_name": {"type": "string"},
            },
        },
    },
    "complete_task": {
        "fn": _complete_task,
        "description": (
            "Mark a task done by id. If it's recurring, the next instance "
            "is auto-created. Confirm before calling on important items."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
    "create_task": {
        "fn": _create_task,
        "description": (
            "Create a new chore. Recurrence codes: 'daily', 'weekly', "
            "'weekly:MON,WED,FRI', 'weekly:SAT,SUN', 'monthly', 'monthly:15',"
            " 'yearly'. Leave empty for one-shot. due_date as YYYY-MM-DD."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "assignee_name": {"type": "string"},
                "due_date": {"type": "string"},
                "recurrence": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["title"],
        },
    },
    "list_appointments": {
        "fn": _list_appointments,
        "description": "Upcoming appointments within N hours (default 168 = 1 week).",
        "input_schema": {
            "type": "object",
            "properties": {
                "window_hours": {"type": "integer", "default": 168},
            },
        },
    },
    "create_appointment": {
        "fn": _create_appointment,
        "description": (
            "Schedule an appointment. when: 'YYYY-MM-DD HH:MM' format. "
            "Resolve relative times via `now` first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "when": {"type": "string"},
                "location": {"type": "string"},
                "notes": {"type": "string"},
                "recurrence": {"type": "string"},
            },
            "required": ["title", "when"],
        },
    },
    "list_groceries": {
        "fn": _list_groceries,
        "description": "Current shopping list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "only_open": {"type": "boolean", "default": True},
            },
        },
    },
    "create_grocery": {
        "fn": _create_grocery,
        "description": "Add an item to the shopping list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "quantity": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["name"],
        },
    },
    "toggle_grocery_purchased": {
        "fn": _toggle_grocery,
        "description": "Mark a grocery line as purchased (or not).",
        "input_schema": {
            "type": "object",
            "properties": {
                "grocery_id": {"type": "integer"},
                "purchased": {"type": "boolean", "default": True},
            },
            "required": ["grocery_id"],
        },
    },
    "list_meals": {
        "fn": _list_meals,
        "description": "Planned meals. Defaults to upcoming-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "upcoming_only": {"type": "boolean", "default": True},
            },
        },
    },
    "create_meal": {
        "fn": _create_meal,
        "description": "Plan a meal for a date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "meal_date": {"type": "string"},
                "meal_type": {"type": "string"},
                "ingredients": {
                    "type": "array", "items": {"type": "string"},
                },
            },
            "required": ["name"],
        },
    },
    "list_notes": {
        "fn": _list_notes,
        "description": "List notes (pinned first, most recently updated next).",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    "create_note": {
        "fn": _create_note,
        "description": "Save a note.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
                "pinned": {"type": "boolean", "default": False},
            },
            "required": ["title"],
        },
    },
    "list_announcements": {
        "fn": _list_announcements,
        "description": "Active household announcements (admin-posted).",
        "input_schema": {"type": "object", "properties": {}},
    },
    "remember": {
        "fn": _memory_remember,
        "description": (
            "Save a fact, preference, or pattern you've learned about "
            "the household. Use a short snake_case key. Examples: "
            "trash_day, justin_coffee_preference, kid_bedtime_routine. "
            "Recall later via the `recall` tool. Persists across "
            "conversations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["key", "value"],
        },
    },
    "recall": {
        "fn": _memory_recall,
        "description": "Recall a previously remembered fact by key.",
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
    "list_memories": {
        "fn": _memory_list,
        "description": (
            "Dump all stored memories. Useful for review or to find a "
            "key you don't quite remember."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    "forget": {
        "fn": _memory_forget,
        "description": "Delete a memory by key.",
        "input_schema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
    "push_to_user": {
        "fn": _push_to_user,
        "description": (
            "Send a push notification to a household member's "
            "subscribed devices. Use sparingly — for genuinely "
            "actionable things. `kind` is a short identifier used for "
            "rate limiting; pass `cooldown_hours` > 0 to avoid spam."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_name": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "url": {"type": "string", "default": "/"},
                "kind": {"type": "string", "default": "assistant"},
                "cooldown_hours": {"type": "number", "default": 0},
            },
            "required": ["user_name", "title", "body"],
        },
    },
    "update_item": {
        "fn": _update_item,
        "description": "Update an inventory item. Pass only fields to change.",
        "input_schema": {"type": "object", "properties": {
            "item_id": {"type": "integer"}, "name": {"type": "string"},
            "quantity": {"type": "integer"}, "category": {"type": "string"},
            "for_sale": {"type": "boolean"}, "estimated_value": {"type": "number"}
        }, "required": ["item_id"]},
    },
    "delete_item": {
        "fn": _delete_item,
        "description": "Soft-delete (trash) an inventory item by id.",
        "input_schema": {"type": "object", "properties": {"item_id": {"type": "integer"}}, "required": ["item_id"]},
    },
    "update_task": {
        "fn": _update_task,
        "description": "Update a task. Pass only fields to change.",
        "input_schema": {"type": "object", "properties": {
            "task_id": {"type": "integer"}, "title": {"type": "string"},
            "description": {"type": "string"}, "assigned_to": {"type": "integer"},
            "due_date": {"type": "string"}
        }, "required": ["task_id"]},
    },
    "delete_task": {
        "fn": _delete_task,
        "description": "Delete a task by id.",
        "input_schema": {"type": "object", "properties": {"task_id": {"type": "integer"}}, "required": ["task_id"]},
    },
    "delete_appointment": {
        "fn": _delete_appointment,
        "description": "Delete an appointment by id.",
        "input_schema": {"type": "object", "properties": {"appointment_id": {"type": "integer"}}, "required": ["appointment_id"]},
    },
    "delete_grocery": {
        "fn": _delete_grocery,
        "description": "Delete a grocery row.",
        "input_schema": {"type": "object", "properties": {"grocery_id": {"type": "integer"}}, "required": ["grocery_id"]},
    },
    "update_note": {
        "fn": _update_note,
        "description": "Update a note title and/or body.",
        "input_schema": {"type": "object", "properties": {
            "note_id": {"type": "integer"}, "title": {"type": "string"}, "body": {"type": "string"}
        }, "required": ["note_id"]},
    },
    "delete_note": {
        "fn": _delete_note,
        "description": "Delete a note by id.",
        "input_schema": {"type": "object", "properties": {"note_id": {"type": "integer"}}, "required": ["note_id"]},
    },
    "list_recipes": {
        "fn": _list_recipes,
        "description": "List saved recipe names + ids.",
        "input_schema": {"type": "object", "properties": {}},
    },
    "delete_recipe": {
        "fn": _delete_recipe,
        "description": "Delete a saved recipe by id.",
        "input_schema": {"type": "object", "properties": {"recipe_id": {"type": "integer"}}, "required": ["recipe_id"]},
    },
    "delete_meal": {
        "fn": _delete_meal,
        "description": "Delete a planned meal by id.",
        "input_schema": {"type": "object", "properties": {"meal_id": {"type": "integer"}}, "required": ["meal_id"]},
    },
    "create_announcement": {
        "fn": _create_announcement,
        "description": "Post a household announcement.",
        "input_schema": {"type": "object", "properties": {
            "title": {"type": "string"}, "body": {"type": "string"}, "pinned": {"type": "boolean"}
        }, "required": ["title"]},
    },
    "delete_announcement": {
        "fn": _delete_announcement,
        "description": "Delete an announcement by id.",
        "input_schema": {"type": "object", "properties": {"announcement_id": {"type": "integer"}}, "required": ["announcement_id"]},
    },
    "bulk_move_room": {
        "fn": _bulk_move_room,
        "description": "Move EVERY active item currently in `from_room` into `to_room`. Returns count moved. Use for requests like 'move everything in the default room to the office'. Creates `to_room` if it doesn't exist.",
        "input_schema": {"type": "object", "properties": {
            "from_room": {"type": "string"}, "to_room": {"type": "string"}
        }, "required": ["from_room", "to_room"]},
    },
    "move_item_to_room": {
        "fn": _move_item_to_room,
        "description": "Move ONE inventory item to a different room. Use when the user names a specific item rather than a whole-room move.",
        "input_schema": {"type": "object", "properties": {
            "item_id": {"type": "integer"}, "target_room": {"type": "string"}
        }, "required": ["item_id", "target_room"]},
    },
}


def call_tool(name: str, arguments: dict | None) -> Any:
    """Look up and invoke a tool. Always returns a JSON-serializable result."""
    if name not in TOOLS:
        return {"error": f"Unknown tool: {name}"}
    fn = TOOLS[name]["fn"]
    args = arguments or {}
    try:
        return fn(**args)
    except TypeError as exc:
        return {"error": f"Invalid arguments for {name}: {exc}"}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def claude_tool_definitions() -> list[dict]:
    """Anthropic Messages API tool-use schema."""
    return [
        {
            "name": name,
            "description": meta["description"],
            "input_schema": meta["input_schema"],
        }
        for name, meta in TOOLS.items()
    ]


def openai_tool_definitions() -> list[dict]:
    """OpenAI chat completions tool-use schema (slightly different wrapper)."""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": meta["description"],
                "parameters": meta["input_schema"],
            },
        }
        for name, meta in TOOLS.items()
    ]
