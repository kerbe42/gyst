"""Strip exception-type / message leaks from user-visible error strings.
Replaces a small set of well-known patterns with _safe_error(exc, "<generic>").
ValueError messages still flow through unchanged via _safe_error.
"""

from pathlib import Path

p = Path("/opt/house-inventory/house_demo/house_demo/states.py")
src = p.read_text()

REPLACEMENTS = [
    # (old_substring, new_substring)
    (
        'self.api_error = f"Couldn\'t save: {type(exc).__name__}: {exc}"',
        'self.api_error = _safe_error(exc, "Could not save API settings.")',
    ),
    (
        'self.user_error = f"Couldn\'t add: {exc}"',
        'self.user_error = _safe_error(exc, "Could not add user.")',
    ),
    (
        'self.manage_error = f"Couldn\'t save profile: {exc}"',
        'self.manage_error = _safe_error(exc, "Could not save profile.")',
    ),
    (
        'self.room_error = f"Couldn\'t add: {exc}"',
        'self.room_error = _safe_error(exc, "Could not add room.")',
    ),
    (
        'self.setup_error = f"Couldn\'t create user: {exc}"',
        'self.setup_error = _safe_error(exc, "Could not create the admin user.")',
    ),
    (
        'self.error = f"Upload failed: {type(exc).__name__}: {exc}"',
        'self.error = _safe_error(exc, "Upload failed. Try again or pick a smaller photo.")',
    ),
    (
        'self.error = f"Couldn\'t save to inventory: {type(exc).__name__}"',
        'self.error = _safe_error(exc, "Could not save items to inventory.")',
    ),
    (
        'self.edit_task_error = f"Couldn\'t save: {exc}"',
        'self.edit_task_error = _safe_error(exc, "Could not save task.")',
    ),
    (
        'self.error = f"Couldn\'t add: {exc}"',
        'self.error = _safe_error(exc, "Could not add.")',
    ),
    (
        'self.recipe_error = f"Couldn\'t save: {type(exc).__name__}: {exc}"',
        'self.recipe_error = _safe_error(exc, "Could not save recipe.")',
    ),
    (
        'self.recipe_error = f"Recipe not saved ({type(exc).__name__})."',
        'self.recipe_error = _safe_error(exc, "Recipe not saved.")',
    ),
    # The "manage_error = Couldn't save: {exc}" appears twice — handle both.
    (
        '            self.manage_error = f"Couldn\'t save: {exc}"',
        '            self.manage_error = _safe_error(exc, "Could not save credentials.")',
    ),
    # The chore-photo-upload one.
    (
        'f"Photo upload failed: {type(exc).__name__}: {exc}"',
        '_safe_error(exc, "Photo upload failed. Try again.")',
    ),
]

count = 0
for old, new in REPLACEMENTS:
    if old in src:
        src = src.replace(old, new)
        count += 1
        print(f"replaced: {old[:60]}...")
    else:
        # Some duplicates use the same literal pattern; that's fine.
        pass
print(f"replaced {count} patterns")

p.write_text(src)
