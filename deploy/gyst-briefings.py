"""GYST automated briefings.

Run by a systemd timer at 7 AM (morning) and 9 PM (evening). For each
subscribed household member, asks the LLM to compose a personalized
digest and pushes it as a notification.

Morning brief: today's tasks, today's appointments, expiring food,
                the weather (placeholder, easy to extend), what's for
                dinner if planned.
Evening brief: tomorrow's preview + nudges about anything pending.

The LLM gets the same tool surface JARVIS has during chat, so it
queries fresh data rather than us pre-computing everything.
"""
from __future__ import annotations

import argparse
import sys


def run(kind: str) -> int:
    """Returns number of briefings pushed."""
    from chores import db as chores_db
    from notifications import db as push_db
    from assistant import chat as assistant_chat

    chores_db.init_db()
    push_db.init_db()

    # Pre-compute an "Expiring soon" addendum so the morning brief always
    # surfaces it deterministically (rather than hoping the model fetches
    # it). Empty string when there's nothing to flag.
    expiring_addendum = ""
    if kind == "morning":
        try:
            from inventory import db as inv_db
            from assistant import tools as assistant_tools
            soon = inv_db.items_expiring_within(5) or []
        except Exception:
            soon = []
            assistant_tools = None  # type: ignore
        if soon:
            soon_lines = [
                f"  - {it.get('name', '?')} ({it.get('expires_at', '?')})"
                for it in soon[:8]
            ]
            recipe_lines: list[str] = []
            try:
                if assistant_tools is not None:
                    suggestions = assistant_tools.recipes_using_expiring_items(5)
                    suggestions = [
                        s for s in suggestions
                        if s.get("expiring_ingredients_matched")
                    ][:2]
                    for s in suggestions:
                        matched = ", ".join(
                            s["expiring_ingredients_matched"][:4]
                        )
                        recipe_lines.append(
                            f"  - {s['recipe_name']} (uses: {matched})"
                        )
            except Exception:
                recipe_lines = []
            expiring_addendum = (
                "\n\nExpiring soon:\n" + "\n".join(soon_lines)
            )
            if recipe_lines:
                expiring_addendum += (
                    "\nSuggested recipes:\n" + "\n".join(recipe_lines)
                )

    pushed = 0
    if kind == "morning":
        prompt = (
            "It's morning. Compose a tight 'morning briefing' as if "
            "you were a butler delivering it verbally. Cover:\n"
            "  - today's open tasks (limit ≤ 5, prioritize due-today)\n"
            "  - today's appointments\n"
            "  - any item expiring today or this week\n"
            "  - what's planned for dinner today, if anything\n"
            "Use 3-6 short lines, no headers, no fluff. Markdown bullets "
            "are fine."
            + (
                "\n\nAlso include this pre-computed 'Expiring soon' "
                "addendum verbatim at the end of the digest body:"
                + expiring_addendum
                if expiring_addendum
                else ""
            )
            + " End by sending one push_to_user notification with "
            "title='Morning briefing', body=<your digest>, "
            "url='/', kind='briefing_morning', cooldown_hours=8. "
            "Send the push to %s. Output only the push tool call; "
            "no further text."
        )
        push_kind = "briefing_morning"
        push_title = "Morning briefing"
    else:
        prompt = (
            "It's evening. Compose a tight 'evening preview' as if you "
            "were a butler. Cover:\n"
            "  - tomorrow's tasks (only those due tomorrow, ≤ 5)\n"
            "  - tomorrow's appointments\n"
            "  - any open task overdue today that wasn't completed\n"
            "  - what's for dinner tomorrow, if planned\n"
            "Use 3-6 short lines. End by sending one push_to_user "
            "notification with title='Evening preview', body=<digest>, "
            "url='/', kind='briefing_evening', cooldown_hours=8. "
            "Send the push to %s. Output only the push tool call."
        )
        push_kind = "briefing_evening"
        push_title = "Evening preview"

    for person in chores_db.list_people():
        uid = int(person["id"])
        if push_db.count_subscriptions_for_user(uid) == 0:
            continue
        # Run a one-shot turn through the agent with the briefing prompt.
        messages = [{"role": "user", "content": prompt % person["name"]}]
        try:
            trace = assistant_chat.turn(messages, person["name"])
        except Exception as exc:
            print(
                f"[briefings:{kind}] failed for {person['name']}: {exc}",
                file=sys.stderr,
            )
            continue
        # If the model didn't call push_to_user, fall back to pushing the
        # last assistant text manually.
        fallback_text = ""
        sent_via_tool = False
        for entry in trace:
            if entry.get("kind") == "tool_call" and entry.get("name") == "push_to_user":
                sent_via_tool = True
            elif entry.get("kind") == "assistant":
                fallback_text = entry.get("text") or fallback_text
        if not sent_via_tool and fallback_text:
            push_db.send_to_user(
                uid, title=push_title, body=fallback_text[:400], url="/",
            )
        pushed += 1
        print(
            f"[briefings:{kind}] sent to {person['name']}",
            file=sys.stderr,
        )

    return pushed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", choices=["dev", "prod"], required=True)
    parser.add_argument("--kind", choices=["morning", "evening"], required=True)
    args = parser.parse_args()
    root = "/opt/house-inventory" if args.env == "dev" else "/opt/gyst-prod"
    sys.path.insert(0, root)
    n = run(args.kind)
    print(f"[briefings:{args.kind}:{args.env}] pushed {n}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
