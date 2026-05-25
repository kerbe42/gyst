"""One-shot rewrite of _stat_card in pages.py.

Replaces the rx.card(..., **({"as_":"a"...})) hack (which Reflex doesn't
support cleanly) with a body-then-rx.link wrapper, while keeping the
equal-height row structure.
"""
from pathlib import Path

p = Path("/opt/house-inventory/house_demo/house_demo/pages.py")
src = p.read_text()

OLD_NEEDLE = '            **({"as_": "a", "href": href} if href else {}),\n'

if OLD_NEEDLE not in src:
    print("OLD NEEDLE NOT FOUND — nothing to do")
    raise SystemExit(0)

# Find the function body around the needle and rewrite the whole inner.
start = src.find('def _stat_card(')
assert start >= 0, "_stat_card not found"
# Find the closing of the function — next top-level `def `.
end = src.find('\ndef ', start + 1)
old_block = src[start:end]

new_block = '''def _stat_card(
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
'''

src = src.replace(old_block, new_block, 1)
p.write_text(src)
print("patched")
