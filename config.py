"""Shared configuration constants for the House App.

Per-tool constants are grouped below. Each tool's modules `import config`
and read what they need.
"""

from __future__ import annotations

from pathlib import Path

# Anchor every path to the project root (where this file lives) so that
# different runners (Streamlit, Reflex, ad-hoc scripts) all read and write
# the same data regardless of their working directory.
_PROJECT_ROOT: Path = Path(__file__).resolve().parent

# ---- Shared paths ------------------------------------------------------------
DATA_DIR: Path = _PROJECT_ROOT / "data"


# ---- Inventory tool ----------------------------------------------------------
# Rooms shown in the room selector for new captures.
ROOMS: list[str] = [
    "kitchen",
    "living room",
    "dining room",
    "master bedroom",
    "guest bedroom",
    "office",
    "garage",
    "basement",
    "attic",
    "laundry room",
    "bathroom",
    "hallway",
    "outside",
]

# Categories used by the LLM prompt and the edit UI.
# Grouped here by area for readability; the LLM sees them as a flat list.
CATEGORIES: list[str] = [
    # --- Kitchen & dining ---
    "cookware",
    "bakeware",
    "kitchen utensil",
    "small appliance",
    "large appliance",
    "dinnerware",
    "glassware",
    "drinkware",
    "cutlery",
    "food storage",
    "pantry / food",
    "spice / seasoning",
    "kitchen linen",
    # --- Tools & hardware ---
    "hand tool",
    "power tool",
    "garden tool",
    "automotive tool",
    "measuring tool",
    "hardware / fastener",
    "workshop supply",
    "paint / finish",
    "adhesive / tape",
    # --- Electronics ---
    "computer",
    "phone / tablet",
    "audio equipment",
    "video / display",
    "cable / wire",
    "charger / adapter",
    "battery",
    "camera",
    "gaming console",
    "smart home device",
    "office equipment",
    "networking gear",
    # --- Clothing & accessories ---
    "clothing",
    "footwear",
    "outerwear",
    "hat / accessory",
    "jewelry / watch",
    "bag / luggage",
    "belt",
    # --- Sports & outdoor ---
    "sports equipment",
    "exercise equipment",
    "bicycle / cycling",
    "camping / hiking",
    "fishing",
    "water sport",
    "winter sport",
    "team sport",
    "ball / racket",
    # --- Toys & hobbies ---
    "toy",
    "stuffed animal",
    "board game / puzzle",
    "card game",
    "musical instrument",
    "art supply",
    "craft supply",
    "sewing / knitting",
    "3d printing supply",
    "model / hobby kit",
    # --- Media ---
    "book",
    "magazine / journal",
    "dvd / blu-ray",
    "cd / music",
    "vinyl record",
    "video game / cartridge",
    # --- Decor & art ---
    "artwork",
    "framed photo",
    "vase / planter",
    "plant",
    "candle",
    "decor / ornament",
    "rug / textile",
    "mirror",
    "clock",
    "lighting / lamp",
    "wall hanging",
    # --- Consumables & supplies ---
    "cleaning supply",
    "toiletry / personal care",
    "cosmetic / makeup",
    "medicine / health",
    "first aid",
    "pet supply",
    "baby supply",
    "office supply",
    "paper / document",
    "stationery",
    # --- Furniture ---
    "seating",
    "table",
    "bed / mattress",
    "storage furniture",
    "desk",
    "outdoor furniture",
    "shelving",
    # --- Bedding & bath ---
    "bedding",
    "bath linen",
    "towel",
    "blanket / throw",
    "pillow",
    # --- Storage containers ---
    "container / bin",
    "box / case",
    "basket",
    "bag (storage)",
    "jar",
    # --- Vehicles & automotive ---
    "car / motorcycle",
    "scooter / skateboard",
    "automotive part",
    "automotive fluid",
    # --- Other ---
    "seasonal / holiday",
    "collectible",
    "memorabilia",
    "keys",
    "safety / emergency",
    "fire safety",
    "lawn / yard",
    "outdoor power equipment",
    "snow removal",
    "luggage tag / travel",
    "other",
]

PHOTOS_DIR: Path = DATA_DIR / "photos"
DB_PATH: Path = DATA_DIR / "inventory.db"  # legacy name kept for stability
PROMPT_PATH: Path = _PROJECT_ROOT / "inventory" / "prompts" / "identify.txt"

# LLM identification (Anthropic).
LLM_MODEL: str = "claude-opus-4-7"
LLM_MAX_TOKENS: int = 1024

# OWL-ViT v2 detection.
OWL_MODEL_ID: str = "google/owlv2-base-patch16-ensemble"
OWL_THRESHOLD: float = 0.15  # confidence floor; lower = more boxes
OWL_NMS_IOU: float = 0.3  # per-label NMS IoU; lower = stricter dedup


# ---- Chores tool -------------------------------------------------------------
CHORES_DB_PATH: Path = DATA_DIR / "chores.db"

# ---- Other modules -----------------------------------------------------------
ANNOUNCEMENTS_DB_PATH: Path = DATA_DIR / "announcements.db"
GROCERIES_DB_PATH: Path = DATA_DIR / "groceries.db"
MEALS_DB_PATH: Path = DATA_DIR / "meals.db"
APPOINTMENTS_DB_PATH: Path = DATA_DIR / "appointments.db"
NOTES_DB_PATH: Path = DATA_DIR / "notes.db"
NOTIFICATIONS_DB_PATH: Path = DATA_DIR / "notifications.db"

# Photos uploaded as proof-of-completion for chores live here.
CHORE_PHOTOS_DIR: Path = DATA_DIR / "chore_photos"

# TLS materials for HTTPS. Drop `cert.pem` + `key.pem` here (or use Caddy's
# `tls internal` to auto-generate a self-signed pair instead). See README.
TLS_DIR: Path = DATA_DIR / "tls"

# App settings (LLM provider, API keys, model names, etc.) database.
APP_SETTINGS_DB_PATH: Path = DATA_DIR / "app_settings.db"
# Encryption key for sensitive settings (API keys). File is chmod 600.
MASTER_KEY_PATH: Path = DATA_DIR / ".master_key"

MEAL_TYPES: list[str] = ["breakfast", "lunch", "dinner", "snack"]

# Recipes are user-managed in the Meals → Add → "Saved recipes" section,
# stored in meals.db. There are intentionally no pre-canned recipes.

# Pre-populated chore titles. Used as a quick-pick dropdown when adding a task.
CHORE_TEMPLATES: list[str] = [
    "Wash the dishes",
    "Empty the dishwasher",
    "Load the dishwasher",
    "Take out the kitchen trash",
    "Wipe down kitchen counters",
    "Clean the stovetop",
    "Clean the microwave",
    "Clean the oven",
    "Clean the refrigerator",
    "Mop the kitchen floor",
    "Sweep the kitchen",
    "Clean the toilet",
    "Scrub the shower / tub",
    "Wipe down bathroom mirrors",
    "Mop the bathroom floor",
    "Replace bathroom towels",
    "Restock toilet paper",
    "Make the bed",
    "Change the bedsheets",
    "Vacuum the bedroom",
    "Dust the bedroom",
    "Vacuum the living room",
    "Dust shelves and surfaces",
    "Wipe down windows",
    "Tidy the living room",
    "Take out the recycling",
    "Take out the trash",
    "Wash a load of laundry",
    "Dry a load of laundry",
    "Fold and put away laundry",
    "Wash bedding",
    "Iron clothes",
    "Mow the lawn",
    "Weed the garden",
    "Water the plants",
    "Rake the leaves",
    "Sweep the porch",
    "Shovel the snow",
    "Edge the lawn",
    "Feed the pets",
    "Walk the dog",
    "Clean the litter box",
    "Brush the pet",
    "Change air filter",
    "Replace light bulbs",
    "Clean ceiling fans",
    "Wipe baseboards",
    "Clean the windows",
    "Vacuum the car",
    "Wash the car",
]

# Default palette offered when creating a new person.
PERSON_COLORS: list[str] = [
    "#FF4136",  # red
    "#FF851B",  # orange
    "#FFDC00",  # yellow
    "#2ECC40",  # green
    "#39CCCC",  # teal
    "#0074D9",  # blue
    "#B10DC9",  # violet
    "#F012BE",  # magenta
    "#85144B",  # maroon
    "#AAAAAA",  # gray
]
