"""Vision pipeline: Claude identifies item types, OWL-ViT v2 counts instances.

Exposes one main entry point: `recognize_items(image_path)`.

OWL-ViT and the Anthropic client are loaded lazily and cached as module-level
globals so Streamlit reruns don't reload them.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import config
from app_settings import db as settings_db


# Setting keys for the LLM provider/credentials.
SETTING_PROVIDER = "llm_provider"          # "claude" or "openai"
SETTING_ANTHROPIC_KEY = "anthropic_api_key"
SETTING_OPENAI_KEY = "openai_api_key"
SETTING_CLAUDE_MODEL = "claude_model"
SETTING_OPENAI_MODEL = "openai_model"
# When "0", the OWL-ViT detector is skipped entirely and quantities come
# from the LLM. Useful if the detector hangs (slow CPU, no GPU, model
# download in progress, etc.).
SETTING_ENABLE_DETECTOR = "enable_detector"

DEFAULT_PROVIDER = "claude"
DEFAULT_CLAUDE_MODEL = "claude-haiku-4-5"  # fast default for recognition; Sonnet/Opus selectable in Settings -> API
DEFAULT_OPENAI_MODEL = "gpt-4o"
DEFAULT_ENABLE_DETECTOR = False  # was True; OWL adds 2-5s, LLM count is usually close enough. Toggle in Settings -> API.


def detector_enabled() -> bool:
    """Read the user-toggleable detector flag."""
    settings_db.init_db()
    raw = settings_db.get(SETTING_ENABLE_DETECTOR, None)
    if raw is None:
        return DEFAULT_ENABLE_DETECTOR
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


def _get_llm_config() -> tuple[str, str, str]:
    """Resolve (provider, api_key, model) from settings, with env-var fallback."""
    settings_db.init_db()
    provider = settings_db.get(SETTING_PROVIDER, DEFAULT_PROVIDER) or DEFAULT_PROVIDER
    if provider == "openai":
        key = (
            settings_db.get(SETTING_OPENAI_KEY)
            or os.environ.get("OPENAI_API_KEY", "")
        )
        model = (
            settings_db.get(SETTING_OPENAI_MODEL, DEFAULT_OPENAI_MODEL)
            or DEFAULT_OPENAI_MODEL
        )
    else:
        provider = "claude"
        key = (
            settings_db.get(SETTING_ANTHROPIC_KEY)
            or os.environ.get("ANTHROPIC_API_KEY", "")
        )
        model = (
            settings_db.get(SETTING_CLAUDE_MODEL, DEFAULT_CLAUDE_MODEL)
            or DEFAULT_CLAUDE_MODEL
        )
    if not key:
        raise RuntimeError(
            f"No API key configured for provider '{provider}'. "
            "Set one in Settings → API."
        )
    return provider, key, model


@dataclass
class RecognizedItem:
    name: str
    category: str = "other"
    llm_quantity: int = 1
    detector_count: int = 0
    # Pixel-space bounding boxes from OWL-ViT, one per detected instance.
    # Each box is [x1, y1, x2, y2] in the original image's coordinate system.
    boxes: list[list[float]] = field(default_factory=list)
    # Rough used-market value in USD as estimated by the LLM. 0.0 means
    # "unknown / not worth estimating"; the user can edit before saving.
    estimated_value: float = 0.0


# ---- Lazy global caches ------------------------------------------------------
_anthropic_client = None
_owl_model = None
_owl_processor = None
_owl_device: Optional[str] = None
_prompt_cache: Optional[str] = None


_openai_client = None
_openai_client_key: Optional[str] = None
_anthropic_client_key: Optional[str] = None


def _get_anthropic_client(api_key: str):
    """Return a cached Anthropic client. Rebuilds if the key changed."""
    global _anthropic_client, _anthropic_client_key
    if _anthropic_client is not None and _anthropic_client_key == api_key:
        return _anthropic_client
    import anthropic

    _anthropic_client = anthropic.Anthropic(api_key=api_key)
    _anthropic_client_key = api_key
    return _anthropic_client


def _get_openai_client(api_key: str):
    """Return a cached OpenAI client. Rebuilds if the key changed."""
    global _openai_client, _openai_client_key
    if _openai_client is not None and _openai_client_key == api_key:
        return _openai_client
    from openai import OpenAI

    _openai_client = OpenAI(api_key=api_key)
    _openai_client_key = api_key
    return _openai_client


def _load_prompt() -> str:
    global _prompt_cache
    if _prompt_cache is None:
        text = config.PROMPT_PATH.read_text(encoding="utf-8").strip()
        # Inject the live category list from config so prompt + edit UI stay
        # in sync — edit categories in config.py and both update.
        text = text.replace("{CATEGORIES}", ", ".join(config.CATEGORIES))
        _prompt_cache = text
    return _prompt_cache


def _load_owl():
    """Load OWL-ViT v2 once and cache. Returns (model, processor, device)."""
    global _owl_model, _owl_processor, _owl_device
    if _owl_model is not None:
        return _owl_model, _owl_processor, _owl_device

    import torch
    from transformers import Owlv2ForObjectDetection, Owlv2Processor

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(
        f"[recognize] loading {config.OWL_MODEL_ID} on {device} "
        "(first run downloads ~700 MB)...",
        file=sys.stderr,
    )
    sys.stderr.flush()
    t0 = time.perf_counter()
    processor = Owlv2Processor.from_pretrained(config.OWL_MODEL_ID)
    model = (
        Owlv2ForObjectDetection.from_pretrained(config.OWL_MODEL_ID)
        .to(device)
        .eval()
    )
    print(
        f"[recognize] loaded OWL-ViT in {time.perf_counter() - t0:.1f}s",
        file=sys.stderr,
    )
    sys.stderr.flush()

    _owl_model = model
    _owl_processor = processor
    _owl_device = device
    return model, processor, device


# ---- Image helpers -----------------------------------------------------------
def _encode_image(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    ext = path.suffix.lower().lstrip(".")
    if ext == "jpg":
        ext = "jpeg"
    return base64.standard_b64encode(data).decode("ascii"), f"image/{ext}"


# ---- LLM identification ------------------------------------------------------
def _parse_items_from_response(text: str) -> list[RecognizedItem]:
    if not text:
        return []
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()
    obj = None
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                obj = json.loads(match.group(0))
            except json.JSONDecodeError:
                return []
        else:
            return []
    if not isinstance(obj, dict):
        return []
    items_raw = obj.get("items", [])
    if not isinstance(items_raw, list):
        return []
    items: list[RecognizedItem] = []
    for entry in items_raw:
        estimated_value = 0.0
        if isinstance(entry, dict):
            name = str(entry.get("name", "")).strip().lower()
            category = (
                str(entry.get("category", "other")).strip().lower() or "other"
            )
            # Accept estimated_value_usd or estimated_value, numeric or numeric-string.
            raw_val = entry.get("estimated_value_usd")
            if raw_val is None:
                raw_val = entry.get("estimated_value")
            if raw_val is not None:
                try:
                    estimated_value = max(0.0, float(raw_val))
                except (TypeError, ValueError):
                    estimated_value = 0.0
        elif isinstance(entry, str):
            name = entry.strip().lower()
            category = "other"
        else:
            continue
        if name:
            items.append(
                RecognizedItem(
                    name=name, category=category, estimated_value=estimated_value
                )
            )
    return items


# Transient API errors we should retry: HTTP 429 (rate limit), 502/503/504
# (gateway / upstream), and Anthropic's 529 ("overloaded"). Both SDK clients
# raise exceptions exposing `status_code` on the HTTP error subclass, so we
# match by attribute rather than by exception type to stay SDK-agnostic.
_RETRYABLE_STATUS = {429, 502, 503, 504, 529}
_MAX_RETRIES = 4
_BASE_BACKOFF_S = 1.5


def _is_retryable(exc: Exception) -> bool:
    code = getattr(exc, "status_code", None)
    if code in _RETRYABLE_STATUS:
        return True
    # Sometimes the SDK wraps the body and exposes it in str(exc) — fall back
    # to a substring check for the Anthropic 'overloaded' marker.
    msg = str(exc).lower()
    if "overloaded" in msg or "rate_limit" in msg or "rate limit" in msg:
        return True
    return False


def _call_with_retry(call):
    """Invoke `call()` and retry up to _MAX_RETRIES times for transient
    upstream errors (rate limits, gateway timeouts, Anthropic overload).
    Sleeps with exponential backoff + jitter."""
    import random
    import time as _time

    for attempt in range(_MAX_RETRIES + 1):
        try:
            return call()
        except Exception as exc:
            if attempt >= _MAX_RETRIES or not _is_retryable(exc):
                raise
            wait = _BASE_BACKOFF_S * (2 ** attempt) + random.uniform(0, 0.5)
            print(
                f"[recognize] transient API error "
                f"({type(exc).__name__}: {exc}); "
                f"retry {attempt + 1}/{_MAX_RETRIES} in {wait:.1f}s",
                file=sys.stderr,
            )
            sys.stderr.flush()
            _time.sleep(wait)


def _vision_completion(prompt: str, image_b64: str, media_type: str) -> str:
    """Send (image + prompt) to whichever LLM is configured; return the text.

    Transient upstream errors (429/502/503/504/529) are retried with
    exponential backoff up to _MAX_RETRIES times before giving up. Non-
    retryable errors (auth failures, invalid model, etc.) propagate
    immediately so the caller surfaces a real error message to the user.
    """
    provider, key, model = _get_llm_config()
    if provider == "openai":
        client = _get_openai_client(key)
        resp = _call_with_retry(lambda: client.chat.completions.create(
            model=model,
            max_completion_tokens=config.LLM_MAX_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": (
                                    f"data:{media_type};base64,{image_b64}"
                                ),
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
        ))
        return resp.choices[0].message.content or ""
    # Default: Anthropic Claude
    client = _get_anthropic_client(key)
    msg = _call_with_retry(lambda: client.messages.create(
        model=model,
        max_tokens=config.LLM_MAX_TOKENS,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    ))
    return "".join(
        b.text for b in msg.content if getattr(b, "type", None) == "text"
    )


def _identify_with_llm(image_path: Path) -> list[RecognizedItem]:
    image_b64, media_type = _encode_image(image_path)
    prompt = _load_prompt()
    text = _vision_completion(prompt, image_b64, media_type)
    return _parse_items_from_response(text)


# ---- Detector ----------------------------------------------------------------
def _count_with_owl(
    image_path: Path, labels: list[str]
) -> tuple[list[int], list[list[list[float]]]]:
    """Per-label detection with OWL-ViT v2 + per-label NMS.

    Returns (counts_per_label, boxes_per_label).
    `boxes_per_label[i]` is a list of [x1, y1, x2, y2] in the original image's
    pixel coordinates, one per surviving detection for labels[i].
    """
    if not labels:
        return [], []

    import torch
    import torchvision.ops as ops
    from PIL import Image

    print(
        f"[recognize] count_with_owl: {len(labels)} label(s) on "
        f"{image_path.name}",
        file=sys.stderr,
    )
    sys.stderr.flush()
    t_load = time.perf_counter()
    model, processor, device = _load_owl()
    image = Image.open(image_path).convert("RGB")
    print(
        f"[recognize] OWL ready in {time.perf_counter() - t_load:.1f}s; "
        f"running inference on {device}…",
        file=sys.stderr,
    )
    sys.stderr.flush()

    # OWL-ViT expects nested list: outer = per-image, inner = queries.
    texts = [labels]

    t_inf = time.perf_counter()
    inputs = processor(text=texts, images=image, return_tensors="pt")
    inputs = {
        k: (v.to(device) if hasattr(v, "to") else v) for k, v in inputs.items()
    }

    with torch.no_grad():
        outputs = model(**inputs)
    print(
        f"[recognize] inference done in {time.perf_counter() - t_inf:.1f}s",
        file=sys.stderr,
    )
    sys.stderr.flush()

    target_sizes = torch.tensor([image.size[::-1]], device=device)  # (h, w)

    if hasattr(processor, "post_process_grounded_object_detection"):
        results = processor.post_process_grounded_object_detection(
            outputs=outputs,
            target_sizes=target_sizes,
            threshold=config.OWL_THRESHOLD,
            text_labels=texts,
        )
    else:
        results = processor.post_process_object_detection(
            outputs=outputs,
            threshold=config.OWL_THRESHOLD,
            target_sizes=target_sizes,
        )

    detected = results[0]
    boxes = detected["boxes"]
    scores = detected["scores"]

    # Newer transformers returns text_labels (strings); older returns labels (indices).
    if "labels" in detected and isinstance(detected["labels"], torch.Tensor):
        label_idx = detected["labels"]
    elif "text_labels" in detected:
        text_labels = detected["text_labels"]
        idxs = [labels.index(t) if t in labels else -1 for t in text_labels]
        label_idx = torch.tensor(idxs, dtype=torch.long, device=boxes.device)
    else:
        label_idx = torch.zeros(len(boxes), dtype=torch.long, device=boxes.device)

    counts = [0] * len(labels)
    boxes_per_label: list[list[list[float]]] = [[] for _ in labels]
    for li in range(len(labels)):
        mask = label_idx == li
        if not mask.any():
            continue
        label_boxes = boxes[mask]
        label_scores = scores[mask]
        keep = ops.nms(label_boxes, label_scores, iou_threshold=config.OWL_NMS_IOU)
        counts[li] = int(keep.numel())
        # Keep the boxes that survived NMS, as CPU-side Python lists.
        boxes_per_label[li] = label_boxes[keep].cpu().tolist()
    return counts, boxes_per_label


# ---- Public entry point ------------------------------------------------------
# Items whose individual identity is best captured by reading the
# label/spine/cover text rather than the generic category name.
_TEXT_LABELED_KEYWORDS = {
    "book",
    "novel",
    "textbook",
    "magazine",
    "journal",
    "dvd",
    "blu-ray",
    "bluray",
    "cd",
    "vhs",
    "video game",
    "game cartridge",
    "vinyl",
    "lp",
}


def _is_text_labeled(item: RecognizedItem) -> bool:
    """Heuristic: should we try to read this item's title individually?"""
    name_lower = item.name.lower()
    return any(kw in name_lower for kw in _TEXT_LABELED_KEYWORDS)


def _read_title_from_crop(
    image_path: Path, box: list[float]
) -> Optional[str]:
    """Crop the image to `box` and ask the LLM to read the title/label.

    For tall, narrow crops (book spines, DVD spines, etc.) we rotate the
    image 90° CCW so vertical text reads horizontally — modern VLMs are
    materially more accurate on horizontal text. We also pad generously
    (15% rather than 1%) so first/last characters on tilted books aren't
    clipped. Returns the title string, or None if unreadable.
    """
    import io

    from PIL import Image, ImageOps

    img = Image.open(image_path).convert("RGB")
    img = ImageOps.exif_transpose(img)

    if len(box) < 4:
        return None
    x1, y1, x2, y2 = box[:4]
    # Generous padding so edge text on tilted / partially-visible spines
    # doesn't get clipped. Books especially benefit from this.
    w = max(1, x2 - x1)
    h = max(1, y2 - y1)
    pad_x = max(12, int(w * 0.15))
    pad_y = max(12, int(h * 0.15))
    crop_box = (
        max(0, int(x1 - pad_x)),
        max(0, int(y1 - pad_y)),
        min(img.width, int(x2 + pad_x)),
        min(img.height, int(y2 + pad_y)),
    )
    cropped = img.crop(crop_box)

    # Auto-rotate tall crops (probably a book spine) so the spine text is
    # roughly horizontal. We send both orientations and let the LLM pick.
    cw, ch = cropped.size
    if ch > cw * 1.4:
        rotated = cropped.rotate(90, expand=True)
    else:
        rotated = cropped

    buf = io.BytesIO()
    rotated.save(buf, format="JPEG", quality=92)
    image_b64 = base64.standard_b64encode(buf.getvalue()).decode("ascii")

    title_prompt = (
        "You are looking at a single labeled object — a book, DVD, "
        "magazine, video game, or similar. The image may have been "
        "rotated; the text inside may run vertically, horizontally, or "
        "at an angle. Identify the TITLE printed on the spine, cover, "
        "or front label, regardless of orientation. Mentally rotate to "
        "read it correctly.\n\n"
        "Return ONLY the title as plain UTF-8 text. No quotes, no author, "
        "no subtitle (unless inseparable from the main title), no "
        "commentary, no prefix like 'Title:'. If illegible or you aren't "
        "confident, return exactly: UNKNOWN"
    )
    text = _vision_completion(title_prompt, image_b64, "image/jpeg")
    return _normalize_title(text)


def extract_book_titles_from_shelf(image_path: Path) -> list[dict]:
    """Single-shot bookshelf extraction.

    For photos of multiple books (a shelf, a stack, a table), it's much
    more accurate to give the WHOLE image to the VLM and let it enumerate
    titles than to detect boxes + crop + per-crop title. The VLM gets full
    context (cover next to spine, series numbering, etc.) and we only pay
    one API call.

    Returns: list of {name, quantity} dicts. Quantity is almost always 1
    (one physical book per visible spine/cover); the LLM sets it >1 if it
    spots duplicate copies. Empty list on failure or no books.
    """
    image_b64, media_type = _encode_image(image_path)
    prompt = (
        "This photo shows one or more books — possibly a full shelf, "
        "a stack, a pile, or just a single book. Books may be:\n"
        "  - standing upright on a shelf, showing their spines\n"
        "  - lying flat showing their cover\n"
        "  - tilted, rotated, or partially hidden behind others\n"
        "  - in any orientation: vertical spine, horizontal spine, "
        "upside-down, sideways\n"
        "\n"
        "Mentally rotate each book and read its title regardless of "
        "orientation. Be exhaustive — every visible book should appear "
        "exactly once.\n"
        "\n"
        "Return a JSON array. Each entry: {\"name\": <title string>, "
        "\"quantity\": <integer, default 1; >1 only for visibly "
        "duplicate copies>}. Use the printed title verbatim if you can "
        "read it confidently. If a title is illegible, omit that book "
        "entirely rather than guessing. Do NOT include subtitles unless "
        "they're inseparable. Do NOT include the author. Do NOT include "
        "non-book items.\n"
        "\n"
        "Return ONLY the JSON array, no preamble or explanation."
    )
    text = _vision_completion(prompt, image_b64, media_type)
    if not text:
        return []
    cleaned = text.strip()
    m = re.search(r"```(?:json)?\s*(.+?)```", cleaned, re.DOTALL)
    if m:
        cleaned = m.group(1).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for row in data:
        if not isinstance(row, dict):
            continue
        name = (row.get("name") or "").strip()
        if not name or name.upper() == "UNKNOWN":
            continue
        # De-dupe by case-folded name.
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            qty = int(row.get("quantity") or 1)
        except (TypeError, ValueError):
            qty = 1
        out.append({"name": name, "quantity": max(1, qty)})
    return out


def _normalize_title(text: str) -> Optional[str]:
    title = (text or "").strip().strip('"').strip("'").strip()
    if not title or title.upper() == "UNKNOWN":
        return None
    return title


def identify_receipt(image_path: Path) -> dict:
    """Vision-LLM pass tuned for grocery / hardware-store receipts.

    Returns a dict ``{items: [...], store: str|None, total: float|None,
    date: 'YYYY-MM-DD'|None}``. Each item has keys name/quantity/price.

    Uses the same provider + retry logic as ``identify_items()`` but with
    a receipt-specific prompt that asks for line-items + receipt header
    fields rather than visible objects.
    """
    image_b64, media_type = _encode_image(image_path)
    prompt = (
        "You are looking at a paper receipt. Extract a JSON object with "
        "exactly these keys and NOTHING else:\n"
        "  store: store / merchant name (string, or null if unreadable)\n"
        "  date: ISO date of the purchase as YYYY-MM-DD (string, or null)\n"
        "  total: grand total in USD (number, or null)\n"
        "  items: array of line items. Each item is "
        "{name, quantity, price}. name is human-readable (expand "
        "'BNNAS' -> 'bananas'); quantity is integer (default 1); "
        "price is number in USD (or null).\n"
        "Skip subtotals, taxes, tips, store info, loyalty discounts in "
        "the items list. If the image isn't a receipt, return "
        "{\"items\": [], \"store\": null, \"date\": null, \"total\": null}."
    )
    text = _vision_completion(prompt, image_b64, media_type)
    empty = {"items": [], "store": None, "total": None, "date": None}
    if not text:
        return empty
    import json as _json
    import re as _re

    cleaned = text.strip()
    m = _re.search(r"```(?:json)?\s*(.+?)```", cleaned, _re.DOTALL)
    if m:
        cleaned = m.group(1).strip()
    try:
        data = _json.loads(cleaned)
    except _json.JSONDecodeError:
        return empty
    # Backward compat: model may still emit a bare array.
    if isinstance(data, list):
        data = {"items": data, "store": None, "total": None, "date": None}
    if not isinstance(data, dict):
        return empty
    raw_items = data.get("items") or []
    if not isinstance(raw_items, list):
        raw_items = []
    items: list[dict] = []
    for row in raw_items:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        try:
            qty = int(row.get("quantity") or 1)
        except (TypeError, ValueError):
            qty = 1
        try:
            price = float(row.get("price")) if row.get("price") else None
        except (TypeError, ValueError):
            price = None
        items.append({"name": name, "quantity": max(1, qty), "price": price})
    store = data.get("store")
    if store is not None:
        store = str(store).strip() or None
    date = data.get("date")
    if date is not None:
        date = str(date).strip() or None
    total = data.get("total")
    try:
        total = float(total) if total is not None else None
    except (TypeError, ValueError):
        total = None
    return {"items": items, "store": store, "total": total, "date": date}


def identify_receipt_items(image_path: Path) -> list[dict]:
    """Backward-compatible wrapper returning just the line items list.

    Prefer ``identify_receipt`` for new callers that also want
    store/date/total."""
    return identify_receipt(image_path)["items"]


def identify_items(image_path: Path) -> list[RecognizedItem]:
    """Stage 1: ask the LLM to identify item types in the photo."""
    return _identify_with_llm(image_path)


def count_items(
    image_path: Path, labels: list[str]
) -> tuple[list[int], list[list[list[float]]]]:
    """Stage 2: OWL-ViT counts instances of each label.
    Returns (counts_per_label, boxes_per_label). Falls back to zeros on error.

    If the detector is disabled in Settings, returns zeros immediately so the
    LLM-reported quantities are used downstream.
    """
    if not detector_enabled():
        print(
            "[recognize] detector disabled in settings; skipping OWL-ViT",
            file=sys.stderr,
        )
        return [0] * len(labels), [[] for _ in labels]
    try:
        return _count_with_owl(image_path, labels)
    except Exception as exc:
        print(
            f"[recognize] detector failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return [0] * len(labels), [[] for _ in labels]


def has_text_items(items: list[RecognizedItem]) -> bool:
    """Are any of these items the kind we want to title-refine per-instance?"""
    return any(_is_text_labeled(it) for it in items)


def refine_text_items(
    image_path: Path,
    identified: list[RecognizedItem],
    counts: list[int],
    boxes_per_label: list[list[list[float]]],
) -> list[RecognizedItem]:
    """Stage 3: for text-labeled items, crop each detected instance and read
    its title via the LLM. Generic items pass through with detector count + boxes.
    """
    refined: list[RecognizedItem] = []
    for item, count, boxes in zip(identified, counts, boxes_per_label):
        if _is_text_labeled(item) and boxes:
            for box in boxes:
                try:
                    title = _read_title_from_crop(image_path, box)
                except Exception as exc:
                    print(
                        f"[recognize] title read failed: "
                        f"{type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )
                    title = None
                refined.append(
                    RecognizedItem(
                        name=title or item.name,
                        category=item.category,
                        llm_quantity=1,
                        detector_count=1,
                        boxes=[list(box)],
                    )
                )
        else:
            item.detector_count = count
            item.boxes = boxes
            refined.append(item)
    return refined


def recognize_items(image_path: Path) -> list[RecognizedItem]:
    """All-in-one — convenience wrapper around the three stages above."""
    identified = identify_items(image_path)
    if not identified:
        return []
    labels = [it.name for it in identified]
    counts, boxes_per_label = count_items(image_path, labels)
    return refine_text_items(image_path, identified, counts, boxes_per_label)
