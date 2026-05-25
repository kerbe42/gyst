"""Wrap each destructive delete handler with UndoState.arm() so the
bottom-fixed snack appears with an Undo button. Pattern-matches each
unique delete site by signature; bails noisily on any miss."""

from pathlib import Path

p = Path("/opt/house-inventory/house_demo/house_demo/states.py")
src = p.read_text()


def replace_once(old: str, new: str, label: str) -> None:
    global src
    if old not in src:
        print(f"MISS: {label}")
        return
    src = src.replace(old, new, 1)
    print(f"ok:   {label}")


# ---- Inventory: 4 list-view delete_item handlers all look the same ----
INV_OLD = (
    "    @rx.event\n"
    "    def delete_item(self, item_id: int):\n"
    "        inv_db.delete_item(int(item_id))\n"
    "        self._refresh()\n"
)
INV_NEW = (
    "    @rx.event\n"
    "    async def delete_item(self, item_id: int):\n"
    "        item = inv_db.get_item(int(item_id))\n"
    "        inv_db.delete_item(int(item_id))\n"
    "        self._refresh()\n"
    "        if item:\n"
    "            undo = await self.get_state(UndoState)\n"
    "            undo.arm(\n"
    "                \"inventory\", {\"id\": int(item_id)},\n"
    "                f\"Deleted {item.get('name') or 'item'}.\",\n"
    "            )\n"
)
# Replace all instances (it's the same in multiple classes).
n = src.count(INV_OLD)
src = src.replace(INV_OLD, INV_NEW)
print(f"ok:   {n}x inventory list-view delete_item")

# ---- Inventory Browse/For-sale/Food use the async _require_write form ----
INV_RW_OLD = (
    "    @rx.event\n"
    "    async def delete_item(self, item_id: int):\n"
    "        if not await _require_write(self, \"inventory\"):\n"
    "            return\n"
    "        inv_db.delete_item(int(item_id))\n"
    "        self._refresh()\n"
)
INV_RW_NEW = (
    "    @rx.event\n"
    "    async def delete_item(self, item_id: int):\n"
    "        if not await _require_write(self, \"inventory\"):\n"
    "            return\n"
    "        item = inv_db.get_item(int(item_id))\n"
    "        inv_db.delete_item(int(item_id))\n"
    "        self._refresh()\n"
    "        if item:\n"
    "            undo = await self.get_state(UndoState)\n"
    "            undo.arm(\n"
    "                \"inventory\", {\"id\": int(item_id)},\n"
    "                f\"Deleted {item.get('name') or 'item'}.\",\n"
    "            )\n"
)
n = src.count(INV_RW_OLD)
src = src.replace(INV_RW_OLD, INV_RW_NEW)
print(f"ok:   {n}x inventory write-protected delete_item")

# ---- Capture summary delete_saved_item — already async; just arm undo ----
CAP_OLD = "        if item_id:\n            try:\n                inv_db.delete_item(item_id)\n            except Exception:\n                pass\n        self.items = [it for j, it in enumerate(self.items) if j != idx]"
CAP_NEW = (
    "        snapshot_name = item.get(\"name\") or \"\"\n"
    "        if item_id:\n"
    "            try:\n"
    "                inv_db.delete_item(item_id)\n"
    "            except Exception:\n"
    "                pass\n"
    "        self.items = [it for j, it in enumerate(self.items) if j != idx]\n"
    "        if item_id:\n"
    "            undo = await self.get_state(UndoState)\n"
    "            undo.arm(\n"
    "                \"inventory\", {\"id\": int(item_id)},\n"
    "                f\"Removed {snapshot_name or 'item'}.\",\n"
    "            )"
)
replace_once(CAP_OLD, CAP_NEW, "capture summary delete_saved_item")

# ---- Chores task delete ----
CHO_OLD = (
    "    @rx.event\n"
    "    async def delete_task(self, task_id: int):\n"
    "        if not await _require_write(self, \"chores\"):\n"
    "            return\n"
    "        chores_db.delete_task(int(task_id))\n"
    "        self._refresh()\n"
)
CHO_NEW = (
    "    @rx.event\n"
    "    async def delete_task(self, task_id: int):\n"
    "        if not await _require_write(self, \"chores\"):\n"
    "            return\n"
    "        task = chores_db.get_task(int(task_id))\n"
    "        chores_db.delete_task(int(task_id))\n"
    "        self._refresh()\n"
    "        if task:\n"
    "            undo = await self.get_state(UndoState)\n"
    "            undo.arm(\n"
    "                \"task\",\n"
    "                {\n"
    "                    \"title\": task.get(\"title\") or \"\",\n"
    "                    \"description\": task.get(\"description\"),\n"
    "                    \"assigned_to\": task.get(\"assigned_to\"),\n"
    "                    \"due_date\": task.get(\"due_date\"),\n"
    "                    \"recurrence\": task.get(\"recurrence\"),\n"
    "                    \"parent_task_id\": task.get(\"parent_task_id\"),\n"
    "                },\n"
    "                f\"Deleted {task.get('title') or 'task'}.\",\n"
    "            )\n"
)
replace_once(CHO_OLD, CHO_NEW, "ChoresTasksState.delete_task")

# ---- Announcements ----
ANN_OLD = (
    "    @rx.event\n"
    "    def delete(self, ann_id: int):\n"
    "        ann_db.delete_announcement(int(ann_id))\n"
    "        self._refresh()\n"
)
ANN_NEW = (
    "    @rx.event\n"
    "    async def delete(self, ann_id: int):\n"
    "        row = next(\n"
    "            (a for a in ann_db.list_announcements(include_expired=True)\n"
    "             if int(a['id']) == int(ann_id)),\n"
    "            None,\n"
    "        )\n"
    "        ann_db.delete_announcement(int(ann_id))\n"
    "        self._refresh()\n"
    "        if row:\n"
    "            undo = await self.get_state(UndoState)\n"
    "            undo.arm(\n"
    "                \"announcement\",\n"
    "                {\n"
    "                    \"title\": row.get(\"title\") or \"\",\n"
    "                    \"body\": row.get(\"body\"),\n"
    "                    \"posted_by\": row.get(\"posted_by\"),\n"
    "                    \"pinned\": bool(row.get(\"pinned\")),\n"
    "                },\n"
    "                f\"Deleted announcement: {row.get('title') or ''}.\",\n"
    "            )\n"
)
replace_once(ANN_OLD, ANN_NEW, "AnnouncementsState.delete")

# ---- Notes ----
NOTE_OLD = (
    "    @rx.event\n"
    "    def delete(self, nid: int):\n"
    "        notes_db.delete_note(int(nid))\n"
    "        self._refresh()\n"
)
NOTE_NEW = (
    "    @rx.event\n"
    "    async def delete(self, nid: int):\n"
    "        row = notes_db.get_note(int(nid))\n"
    "        notes_db.delete_note(int(nid))\n"
    "        self._refresh()\n"
    "        if row:\n"
    "            undo = await self.get_state(UndoState)\n"
    "            undo.arm(\n"
    "                \"note\",\n"
    "                {\n"
    "                    \"title\": row.get(\"title\") or \"\",\n"
    "                    \"body\": row.get(\"body\"),\n"
    "                    \"author_id\": row.get(\"author_id\"),\n"
    "                    \"pinned\": bool(row.get(\"pinned\")),\n"
    "                },\n"
    "                f\"Deleted note: {row.get('title') or ''}.\",\n"
    "            )\n"
)
replace_once(NOTE_OLD, NOTE_NEW, "NotesState.delete")

# ---- Groceries ----
GROC_OLD = (
    "    @rx.event\n"
    "    def delete(self, gid: int):\n"
    "        groc_db.delete_grocery(int(gid))\n"
    "        self._refresh()\n"
)
GROC_NEW = (
    "    @rx.event\n"
    "    async def delete(self, gid: int):\n"
    "        row = next(\n"
    "            (g for g in groc_db.list_groceries(include_purchased=True)\n"
    "             if int(g['id']) == int(gid)),\n"
    "            None,\n"
    "        )\n"
    "        groc_db.delete_grocery(int(gid))\n"
    "        self._refresh()\n"
    "        if row:\n"
    "            undo = await self.get_state(UndoState)\n"
    "            undo.arm(\n"
    "                \"grocery\",\n"
    "                {\n"
    "                    \"name\": row.get(\"name\") or \"\",\n"
    "                    \"quantity\": row.get(\"quantity\"),\n"
    "                    \"notes\": row.get(\"notes\"),\n"
    "                    \"from_meal_id\": row.get(\"from_meal_id\"),\n"
    "                },\n"
    "                f\"Removed {row.get('name') or 'item'}.\",\n"
    "            )\n"
)
replace_once(GROC_OLD, GROC_NEW, "GroceriesState.delete")

# ---- Meals recipes ----
RCP_OLD = (
    "    @rx.event\n"
    "    def delete_recipe(self, rid: int):\n"
    "        meals_db.delete_recipe(int(rid))\n"
    "        self._refresh_recipes()\n"
)
RCP_NEW = (
    "    @rx.event\n"
    "    async def delete_recipe(self, rid: int):\n"
    "        row = next(\n"
    "            (r for r in meals_db.list_recipes()\n"
    "             if int(r['id']) == int(rid)),\n"
    "            None,\n"
    "        )\n"
    "        meals_db.delete_recipe(int(rid))\n"
    "        self._refresh_recipes()\n"
    "        if row:\n"
    "            undo = await self.get_state(UndoState)\n"
    "            undo.arm(\n"
    "                \"recipe\",\n"
    "                {\n"
    "                    \"name\": row.get(\"name\") or \"\",\n"
    "                    \"ingredients\": row.get(\"ingredients\") or [],\n"
    "                },\n"
    "                f\"Deleted recipe: {row.get('name') or ''}.\",\n"
    "            )\n"
)
replace_once(RCP_OLD, RCP_NEW, "MealsState.delete_recipe")

# ---- Meals planned ----
MEAL_OLD = (
    "    @rx.event\n"
    "    def delete(self, mid: int):\n"
    "        meals_db.delete_meal(int(mid))\n"
    "        self._refresh()\n"
)
MEAL_NEW = (
    "    @rx.event\n"
    "    async def delete(self, mid: int):\n"
    "        row = next(\n"
    "            (m for m in meals_db.list_meals(upcoming_only=False)\n"
    "             if int(m['id']) == int(mid)),\n"
    "            None,\n"
    "        )\n"
    "        meals_db.delete_meal(int(mid))\n"
    "        self._refresh()\n"
    "        if row:\n"
    "            undo = await self.get_state(UndoState)\n"
    "            undo.arm(\n"
    "                \"meal\",\n"
    "                {\n"
    "                    \"name\": row.get(\"name\") or \"\",\n"
    "                    \"meal_date\": row.get(\"meal_date\"),\n"
    "                    \"meal_type\": row.get(\"meal_type\"),\n"
    "                    \"notes\": row.get(\"notes\"),\n"
    "                    \"ingredients\": row.get(\"ingredients\") or [],\n"
    "                },\n"
    "                f\"Removed meal: {row.get('name') or ''}.\",\n"
    "            )\n"
)
replace_once(MEAL_OLD, MEAL_NEW, "MealsState.delete")

# ---- Appointments ----
APPT_OLD = (
    "    @rx.event\n"
    "    def delete(self, aid: int):\n"
    "        appt_db.delete_appointment(int(aid))\n"
    "        self._refresh()\n"
)
APPT_NEW = (
    "    @rx.event\n"
    "    async def delete(self, aid: int):\n"
    "        row = appt_db.get_appointment(int(aid))\n"
    "        appt_db.delete_appointment(int(aid))\n"
    "        self._refresh()\n"
    "        if row:\n"
    "            undo = await self.get_state(UndoState)\n"
    "            undo.arm(\n"
    "                \"appointment\",\n"
    "                {\n"
    "                    \"title\": row.get(\"title\") or \"\",\n"
    "                    \"appointment_at\": row.get(\"appointment_at\") or \"\",\n"
    "                    \"location\": row.get(\"location\"),\n"
    "                    \"notes\": row.get(\"notes\"),\n"
    "                    \"for_person\": row.get(\"for_person\"),\n"
    "                    \"recurrence\": row.get(\"recurrence\"),\n"
    "                },\n"
    "                f\"Removed: {row.get('title') or 'appointment'}.\",\n"
    "            )\n"
)
replace_once(APPT_OLD, APPT_NEW, "AppointmentsState.delete")

p.write_text(src)
print("done")
