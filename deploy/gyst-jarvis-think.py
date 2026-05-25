"""JARVIS proactive 'thinking' pass.

Runs every few hours via a systemd timer. For each subscribed
household member, the agent gets to look at the current state of the
house and decide whether anything is worth a proactive push.

The prompt is deliberately conservative — JARVIS is told to be a
butler, not a notification spammer. Each potential push respects a
per-kind cooldown so the user isn't repeatedly nagged about the same
thing.
"""
from __future__ import annotations

import argparse
import sys


PROMPT_TEMPLATE = (
    "You are JARVIS, doing a quiet background check on the household. "
    "Survey the state of inventory, tasks, appointments, meals, "
    "groceries, and notes. Decide whether ANYTHING merits a proactive "
    "push notification to {name} right now.\n"
    "\n"
    "You are a butler, NOT a notification spammer. Push only for "
    "genuine, time-sensitive value:\n"
    "  - a chore that's overdue today and they're the assignee\n"
    "  - an appointment in the next 90 minutes that hasn't been "
    "    reminded yet\n"
    "  - a food item expiring tomorrow or today that they should use\n"
    "  - a clear pattern: 'you usually pick up milk Saturdays — it's "
    "    not on the list this week' (use `recall` to check past "
    "    patterns, but only push if confident)\n"
    "  - any pinned announcement they haven't seen (you can't know "
    "    'seen' — skip this for now)\n"
    "\n"
    "DO NOT push for: routine future tasks, low-priority reminders, "
    "things they'd see when they open the app anyway, anything you "
    "pushed recently.\n"
    "\n"
    "If you decide to push, call `push_to_user` with:\n"
    "  - title: ≤ 30 chars, butler-tone\n"
    "  - body: ≤ 120 chars, actionable\n"
    "  - url: the relevant in-app path\n"
    "  - kind: a short identifier so the throttle works\n"
    "  - cooldown_hours: 6 minimum, 24 for less-urgent items\n"
    "\n"
    "If nothing is worth a push, say exactly 'STAND_DOWN' as the "
    "final assistant text and don't call push_to_user. Output the "
    "tool call or STAND_DOWN — no other explanation needed.\n"
    "\n"
    "The user this run is checking: {name}."
)


def run() -> int:
    from chores import db as chores_db
    from notifications import db as push_db
    from assistant import chat as assistant_chat

    chores_db.init_db()
    push_db.init_db()

    sent = 0
    for person in chores_db.list_people():
        uid = int(person["id"])
        if push_db.count_subscriptions_for_user(uid) == 0:
            continue
        prompt = PROMPT_TEMPLATE.format(name=person["name"])
        messages = [{"role": "user", "content": prompt}]
        try:
            trace = assistant_chat.turn(messages, person["name"])
        except Exception as exc:
            print(
                f"[jarvis-think] failed for {person['name']}: {exc}",
                file=sys.stderr,
            )
            continue
        # Audit: count any push_to_user calls.
        for entry in trace:
            if (entry.get("kind") == "tool_call"
                    and entry.get("name") == "push_to_user"):
                sent += 1
        print(
            f"[jarvis-think] {person['name']}: "
            f"{sum(1 for e in trace if e.get('kind') == 'tool_call')} tool calls",
            file=sys.stderr,
        )
    return sent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", choices=["dev", "prod"], required=True)
    args = parser.parse_args()
    root = "/opt/house-inventory" if args.env == "dev" else "/opt/gyst-prod"
    sys.path.insert(0, root)
    n = run()
    print(f"[jarvis-think:{args.env}] pushed {n}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
