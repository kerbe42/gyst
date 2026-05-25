"""Streamlit pages for the Inventory tool.

Three public page functions wired up by the top-level app.py:
- page_capture
- page_search
- page_browse
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import streamlit as st

import config
from inventory import db, recognize


# Cycling palette for per-item bounding-box colors. PIL accepts these names.
_BOX_PALETTE: list[str] = [
    "#FF4136",  # red
    "#2ECC40",  # green
    "#0074D9",  # blue
    "#FF851B",  # orange
    "#B10DC9",  # violet
    "#39CCCC",  # teal
    "#FFDC00",  # yellow
    "#F012BE",  # magenta
    "#01FF70",  # lime
    "#85144B",  # maroon
    "#7FDBFF",  # light blue
    "#AAAAAA",  # gray
]


def _color_for(idx: int) -> str:
    return _BOX_PALETTE[idx % len(_BOX_PALETTE)]


def _open_oriented(photo_path: Path):
    """Open a photo and apply EXIF orientation. Phones store portrait photos
    as landscape pixels + a 'rotate me' EXIF tag; PIL doesn't auto-apply it.
    """
    from PIL import Image, ImageOps

    img = Image.open(photo_path).convert("RGB")
    return ImageOps.exif_transpose(img)


def _crop_to_item(photo_path: Path, item: dict, padding_pct: float = 0.2):
    """Return a PIL image cropped to the union of this item's boxes + padding."""
    img = _open_oriented(photo_path)
    boxes = item.get("boxes") or []
    valid = [b for b in boxes if isinstance(b, (list, tuple)) and len(b) >= 4]
    if not valid:
        return img  # no boxes (legacy item) — fall back to full photo
    min_x = min(b[0] for b in valid)
    min_y = min(b[1] for b in valid)
    max_x = max(b[2] for b in valid)
    max_y = max(b[3] for b in valid)
    w = max(1.0, max_x - min_x)
    h = max(1.0, max_y - min_y)
    pad_x = w * padding_pct
    pad_y = h * padding_pct
    crop = (
        max(0, int(min_x - pad_x)),
        max(0, int(min_y - pad_y)),
        min(img.width, int(max_x + pad_x)),
        min(img.height, int(max_y + pad_y)),
    )
    return img.crop(crop)


def _annotate_photo(
    photo_path: Path, items: Iterable[dict], highlight_idx: Optional[int] = None
):
    """Open `photo_path`, draw colored bounding boxes per item, return a PIL image."""
    from PIL import ImageDraw

    img = _open_oriented(photo_path)
    draw = ImageDraw.Draw(img, "RGBA")
    width = max(3, min(img.width, img.height) // 250)

    for idx, item in enumerate(items):
        if highlight_idx is not None and idx != highlight_idx:
            continue
        boxes = item.get("boxes") or []
        if not boxes:
            continue
        color = _color_for(idx)
        for box in boxes:
            if len(box) < 4:
                continue
            x1, y1, x2, y2 = box[:4]
            draw.rectangle([(x1, y1), (x2, y2)], outline=color, width=width)
    return img


def _legend_markdown(items: list[dict]) -> str:
    parts: list[str] = []
    for idx, item in enumerate(items):
        color = _color_for(idx)
        qty = item.get("quantity", 1)
        qty_str = f" ×{qty}" if qty and qty != 1 else ""
        parts.append(
            f"<span style='display:inline-block;width:12px;height:12px;"
            f"background:{color};border-radius:2px;margin-right:6px;"
            f"vertical-align:middle'></span>"
            f"<span style='vertical-align:middle'>{item['name']}{qty_str}</span>"
        )
    return "&nbsp;&nbsp;&nbsp;".join(parts)


def _render_edit_button(container, item: dict) -> None:
    item_id = item.get("id")
    if item_id is None:
        return
    with container.popover("✏️ Edit", use_container_width=False):
        new_name = st.text_input(
            "Name", value=item["name"], key=f"edit_name_{item_id}"
        )
        new_qty = st.number_input(
            "Quantity",
            value=int(item.get("quantity", 1)),
            min_value=0,
            step=1,
            key=f"edit_qty_{item_id}",
        )
        try:
            cat_idx = config.CATEGORIES.index(item.get("category", "other"))
        except ValueError:
            cat_idx = config.CATEGORIES.index("other")
        new_cat = st.selectbox(
            "Category",
            config.CATEGORIES,
            index=cat_idx,
            key=f"edit_cat_{item_id}",
        )
        if st.button("Save changes", key=f"save_edit_{item_id}", type="primary"):
            cleaned = new_name.strip()
            if not cleaned:
                st.warning("Name can't be empty.")
            else:
                db.update_item(int(item_id), cleaned, int(new_qty), new_cat)
                st.toast(f"Updated: {cleaned}")
                st.rerun()


def _render_delete_button(container, item: dict) -> None:
    item_id = item.get("id")
    if item_id is None:
        return
    with container.popover("🗑️ Delete", use_container_width=False):
        st.write(f"Delete **{item['name']}** from inventory?")
        st.caption("Only this sighting is removed. The photo file stays on disk.")
        if st.button("Yes, delete", key=f"confirm_del_{item_id}", type="primary"):
            db.delete_item(int(item_id))
            st.toast(f"Deleted: {item['name']}")
            st.rerun()


# ---- Pages -------------------------------------------------------------------
def page_capture() -> None:
    db.init_db()
    config.PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

    st.header("Add to inventory")
    room = st.selectbox("Room", config.ROOMS)
    photo = st.file_uploader(
        "Photo (take with camera or choose from library)",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=False,
        help="On mobile, your OS picker will offer 'Take Photo or Video' as one of the options.",
    )

    if photo is None:
        for k in ("recognized", "recognized_hash", "photo_path", "photo_room"):
            st.session_state.pop(k, None)
        return

    photo_hash = hashlib.md5(photo.getvalue()).hexdigest()

    if st.session_state.get("saved_hash") == photo_hash:
        st.success(
            f"Saved {st.session_state.get('saved_count', 0)} items "
            f"to {st.session_state.get('saved_room', '?')}. "
            "Take another photo to continue."
        )
        return

    if st.session_state.get("recognized_hash") != photo_hash:
        import io

        from PIL import Image, ImageOps

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_room = room.replace(" ", "_")
        photo_path = config.PHOTOS_DIR / f"{ts}_{safe_room}.jpg"
        oriented = ImageOps.exif_transpose(
            Image.open(io.BytesIO(photo.getvalue()))
        ).convert("RGB")
        oriented.save(photo_path, "JPEG", quality=92)

        st.session_state.photo_path = str(photo_path)
        st.session_state.photo_room = room

        try:
            with st.spinner("Identifying and counting items..."):
                items = recognize.recognize_items(photo_path)
        except Exception as exc:
            st.error(f"Recognition failed: {type(exc).__name__}: {exc}")
            return

        st.session_state.recognized = [
            {
                "name": it.name,
                "category": it.category,
                "quantity": (
                    it.detector_count if it.detector_count > 0 else it.llm_quantity
                ),
                "detector_count": it.detector_count,
                "boxes": it.boxes,
            }
            for it in items
        ]
        st.session_state.recognized_hash = photo_hash

    items = st.session_state.get("recognized", [])
    if not items:
        st.info("No items detected in this photo.")
        return

    photo_path_obj = Path(st.session_state.photo_path)
    if photo_path_obj.exists():
        try:
            annotated = _annotate_photo(photo_path_obj, items)
            st.image(annotated, use_container_width=True)
            st.markdown(_legend_markdown(items), unsafe_allow_html=True)
        except Exception as exc:
            st.warning(f"Could not render annotated preview: {exc}")
            st.image(str(photo_path_obj), use_container_width=True)

    st.subheader(f"Detected items ({len(items)})")
    st.caption(
        "Edit names and counts before saving. Uncheck **keep** to drop bogus entries. "
        "Detector counts are approximate — review them."
    )

    hdr = st.columns([3, 1, 2, 1])
    hdr[0].caption("Name")
    hdr[1].caption("Qty")
    hdr[2].caption("Category")
    hdr[3].caption("Keep")

    edited: list[dict] = []
    for i, item in enumerate(items):
        cols = st.columns([3, 1, 2, 1])
        name = cols[0].text_input(
            "name", value=item["name"], key=f"name_{i}", label_visibility="collapsed"
        )
        quantity = cols[1].number_input(
            "qty",
            value=int(item["quantity"]),
            min_value=0,
            step=1,
            key=f"qty_{i}",
            label_visibility="collapsed",
        )
        try:
            cat_idx = config.CATEGORIES.index(item["category"])
        except ValueError:
            cat_idx = config.CATEGORIES.index("other")
        category = cols[2].selectbox(
            "cat",
            config.CATEGORIES,
            index=cat_idx,
            key=f"cat_{i}",
            label_visibility="collapsed",
        )
        keep = cols[3].checkbox(
            "keep", value=True, key=f"keep_{i}", label_visibility="collapsed"
        )
        edited.append(
            {
                "name": name.strip(),
                "quantity": int(quantity),
                "category": category,
                "detector_count": item["detector_count"],
                "boxes": item.get("boxes") or [],
                "keep": keep,
            }
        )

    st.divider()
    if st.button("Save to inventory", type="primary"):
        kept = [e for e in edited if e["keep"] and e["name"]]
        if not kept:
            st.warning("Nothing to save — all rows unchecked or empty.")
            return
        photo_id = db.save_photo(
            st.session_state.photo_path, st.session_state.photo_room
        )
        db.save_items(
            photo_id,
            [
                {
                    "name": e["name"],
                    "category": e["category"],
                    "quantity": e["quantity"],
                    "detector_count": e["detector_count"],
                    "boxes": e["boxes"],
                }
                for e in kept
            ],
        )
        st.session_state.saved_hash = photo_hash
        st.session_state.saved_count = len(kept)
        st.session_state.saved_room = st.session_state.photo_room
        for k in ("recognized", "recognized_hash", "photo_path", "photo_room"):
            st.session_state.pop(k, None)
        st.rerun()


def page_search() -> None:
    db.init_db()
    st.header("Where is my…")
    query = st.text_input("Search", placeholder="e.g. drill, scissors, charger")
    if not query.strip():
        return
    results = db.search_items(query)
    if not results:
        st.info(f"Nothing found matching “{query}”.")
        return
    st.caption(f"Found {len(results)} sighting(s) — most recent first.")
    for r in results:
        cols = st.columns([1, 3])
        photo_path = Path(r["photo_path"])
        if photo_path.exists():
            try:
                cols[0].image(_crop_to_item(photo_path, r), width=240)
            except Exception:
                cols[0].image(str(photo_path), width=240)
        else:
            cols[0].caption("(photo missing)")
        qty = r["quantity"]
        qty_str = f" ×{qty}" if qty and qty != 1 else ""
        cols[1].markdown(
            f"### {r['name']}{qty_str}\n"
            f"**Room:** {r['room']}  \n"
            f"**Seen:** {r['created_at']}  \n"
            f"_Category: {r['category']}_"
        )
        btn_row = cols[1].columns([1, 1, 3])
        _render_edit_button(btn_row[0], r)
        _render_delete_button(btn_row[1], r)
        st.divider()


def page_browse() -> None:
    db.init_db()
    st.header("Browse inventory")

    rooms = db.all_rooms_with_counts()
    if not rooms:
        st.info("No items saved yet. Go to **Capture** to add some.")
        return

    st.caption("Per-room totals:")
    st.dataframe(
        {"Room": [r for r, _ in rooms], "Items": [n for _, n in rooms]},
        hide_index=True,
        use_container_width=False,
    )

    st.divider()
    room = st.selectbox("Show items in", config.ROOMS, index=0)
    sort_by = st.radio(
        "Sort",
        ["Most recent first", "A → Z"],
        horizontal=True,
        label_visibility="collapsed",
    )

    items = db.items_in_room(room)
    if not items:
        st.info(f"No items recorded in **{room}** yet.")
        return

    if sort_by == "A → Z":
        items = sorted(items, key=lambda it: it["name"].lower())

    st.caption(f"{len(items)} item(s) in **{room}**.")
    for item in items:
        st.divider()
        cols = st.columns([1, 3])
        path = Path(item["photo_path"])
        if path.exists():
            try:
                cols[0].image(_crop_to_item(path, item), width=240)
            except Exception:
                cols[0].image(str(path), width=240)
        else:
            cols[0].caption("(photo missing)")
        qty = item["quantity"]
        qty_str = f" ×{qty}" if qty and qty != 1 else ""
        cols[1].markdown(
            f"### {item['name']}{qty_str}\n"
            f"_Category: {item['category']}_  \n"
            f"**Seen:** {item['photo_taken_at']}"
        )
        btn_row = cols[1].columns([1, 1, 3])
        _render_edit_button(btn_row[0], item)
        _render_delete_button(btn_row[1], item)
