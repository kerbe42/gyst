"""JARVIS-style chat loop with tool use.

A `turn(messages, system, user_name)` function runs one user turn:
  - sends the conversation to the configured LLM (Claude or OpenAI)
  - if the model wants tools, runs them and feeds results back
  - loops until the model emits a plain text response

Returns a list of "trace" entries describing what happened:
  [
    {"kind": "tool_call", "name": "search_inventory", "args": {...}},
    {"kind": "tool_result", "name": "search_inventory", "result": [...]},
    ...
    {"kind": "assistant", "text": "Found 3 matches, sir."},
  ]

The UI uses the trace to render the conversation with inline tool chips.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from inventory import recognize as _recog  # provider/key/model + clients

from . import tools as _tools


# Hard cap on tool-use rounds so a confused model can't loop forever.
_MAX_TOOL_ROUNDS = 8


def _household_brief() -> str:
    """Compact snapshot of the household that gets injected at the top of
    every conversation. Saves the model a tool call per turn for the
    really common reads (who lives here, what room names exist)."""
    try:
        from chores import db as chores_db
        from inventory import db as inv_db
        from notes import db as notes_db
        people = [p["name"] for p in chores_db.list_people()]
        rooms = inv_db.list_room_names() or []
        memories = notes_db.memory_list(limit=40)
    except Exception:
        people, rooms, memories = [], [], []

    expiring: list[dict] = []
    try:
        from inventory import db as inv_db  # noqa: F811
        expiring = inv_db.items_expiring_within(7) or []
    except Exception:
        expiring = []

    expiring_block = ""
    if expiring:
        lines = []
        for it in expiring[:8]:
            nm = it.get("name") or "?"
            dt = it.get("expires_at") or "?"
            lines.append(f"  - {nm} ({dt})")
        expiring_block = (
            "\nFood expiring this week:\n" + "\n".join(lines)
        )

    mem_block = ""
    if memories:
        mem_block = (
            "\nKnown facts/preferences (call `recall(key)` for fresh "
            "value, or just use these):\n"
            + "\n".join(
                f"  - {m['key']}: {m['value'][:160]}"
                for m in memories
            )
        )

    from datetime import datetime
    now = datetime.now().strftime("%A %b %d, %Y %I:%M %p")

    return (
        f"\n## Current snapshot\n"
        f"Server time: {now}\n"
        f"Household members: {', '.join(people) if people else 'none'}\n"
        f"Rooms: {', '.join(rooms[:30]) if rooms else 'none'}"
        f"{expiring_block}"
        f"{mem_block}\n"
    )


def _jarvis_system_prompt(user_name: str | None) -> str:
    """The personality / behavior contract that sets the JARVIS feel."""
    name = (user_name or "").strip()
    addressee = name if name else "sir"
    return (
        "You are JARVIS, the resident assistant of a household management "
        "system called GYST. Your tone is concise, helpful, slightly "
        f"formal, occasionally dry. Address the user as '{addressee}' "
        "when natural — never overdo it. Don't fawn; don't apologize "
        "unnecessarily; don't pad. Brevity over ceremony.\n"
        "\n"
        "## How you work\n"
        "You have a suite of tools that read and write the household's "
        "actual data — inventory, chores, groceries, meals, "
        "appointments, notes, announcements. Use them aggressively "
        "rather than guessing.\n"
        "\n"
        "Rules:\n"
        " - For any question mentioning relative time ('tomorrow', "
        "'next week', 'in an hour'), call `now` first to anchor.\n"
        " - For any read question, call the relevant list/search tool "
        "before answering — never claim something is or isn't there "
        "without checking.\n"
        " - EXECUTE THE TOOL when the user gives an instruction. "
        "Do not preview, do not ask should-I, do not say I-will "
        "without doing it. Act, then confirm in one short sentence "
        "with the concrete result (e.g. Done -- added Take out trash "
        "due Tue, assigned to Justin).\n"
        " - This applies to deletes too. Delete the dentist "
        "appointment is an order, not a question. Call "
        "delete_appointment immediately, then confirm. Only ask "
        "back if the target is ambiguous (multiple similar "
        "matches) -- in that case list the matches and ask which, "
        "doing nothing else.\n"
        " - Never describe what you are about to do as if waiting "
        "for approval. Either do it, or ask one specific "
        "disambiguating question. Nothing in between.\n"
        " - When the user gives a vague request, infer reasonable "
        "defaults silently. For example, 'remind me to take out the "
        "trash tomorrow' -> add a task with due_date = tomorrow's "
        "date, no recurrence.\n"
        " - When suggesting actions, be specific: name the item, the "
        "date, the assignee. Don't say 'a task' — say 'Take out the "
        "trash, due Tuesday.'\n"
        " - You can chain tools. For 'plan dinner tomorrow using what "
        "we have', call `inventory_in_room('kitchen')` or "
        "`search_inventory` for relevant ingredients, then "
        "`list_meals` for context, then propose 1-3 options.\n"
        " - When you don't have a tool for something, say so plainly.\n"
        "\n"
        "## Style\n"
        " - Short sentences. Avoid filler.\n"
        " - Markdown bullets for lists with more than 3 items.\n"
        " - Currency formatted like $12.45.\n"
        " - Dates formatted like 'Tue May 14'. Times like '2:30 PM'.\n"
        " - Acknowledge what you just did, then offer the next "
        "obvious follow-up if there is one. Otherwise stop talking.\n"
        " - When you learn something durable about the household — a "
        "preference, recurring pattern, family member's schedule — "
        "save it via `remember(key, value)` so future conversations "
        "benefit. Recall when relevant.\n"
        + _household_brief()
        + "\nBegin. The user's message follows."
    )


# ---- Claude (Anthropic) path -------------------------------------------------
def _turn_anthropic(client, model: str, messages: list[dict],
                    system: str) -> list[dict]:
    trace: list[dict] = []
    work = list(messages)
    rounds = 0
    while rounds < _MAX_TOOL_ROUNDS:
        rounds += 1
        resp = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            tools=_tools.claude_tool_definitions(),
            messages=work,
        )
        wants_tools = False
        tool_uses: list[dict] = []
        text_parts: list[str] = []
        for block in resp.content:
            kind = getattr(block, "type", None)
            if kind == "text":
                text_parts.append(block.text)
            elif kind == "tool_use":
                wants_tools = True
                tool_uses.append({
                    "id": block.id,
                    "name": block.name,
                    "input": dict(block.input) if block.input else {},
                })

        if not wants_tools:
            text = "".join(text_parts).strip()
            trace.append({"kind": "assistant", "text": text})
            return trace

        # Re-emit the assistant's tool_use turn into `work` verbatim so the
        # follow-up call has the right context.
        work.append({"role": "assistant", "content": [
            {"type": "text", "text": "".join(text_parts)}
            if text_parts else None,
        ] + [
            {
                "type": "tool_use", "id": tu["id"],
                "name": tu["name"], "input": tu["input"],
            }
            for tu in tool_uses
        ]})
        # Drop the leading None placeholder if no text was emitted.
        work[-1]["content"] = [c for c in work[-1]["content"] if c]

        tool_results: list[dict] = []
        for tu in tool_uses:
            trace.append({
                "kind": "tool_call", "name": tu["name"], "args": tu["input"],
            })
            result = _tools.call_tool(tu["name"], tu["input"])
            trace.append({
                "kind": "tool_result", "name": tu["name"], "result": result,
            })
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu["id"],
                "content": json.dumps(result, default=str)[:8000],
            })
        work.append({"role": "user", "content": tool_results})

    trace.append({
        "kind": "assistant",
        "text": "I'm getting tangled up. Try restating the request?",
    })
    return trace


# ---- OpenAI path -------------------------------------------------------------
def _turn_openai(client, model: str, messages: list[dict],
                 system: str) -> list[dict]:
    trace: list[dict] = []
    work = [{"role": "system", "content": system}] + messages
    rounds = 0
    while rounds < _MAX_TOOL_ROUNDS:
        rounds += 1
        resp = client.chat.completions.create(
            model=model,
            messages=work,
            tools=_tools.openai_tool_definitions(),
            tool_choice="auto",
            max_completion_tokens=2048,
        )
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []
        if not tool_calls:
            trace.append({
                "kind": "assistant", "text": (msg.content or "").strip(),
            })
            return trace

        # Echo the assistant's tool-call turn back into context.
        work.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ],
        })
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            trace.append({
                "kind": "tool_call", "name": name, "args": args,
            })
            result = _tools.call_tool(name, args)
            trace.append({
                "kind": "tool_result", "name": name, "result": result,
            })
            work.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, default=str)[:8000],
            })

    trace.append({
        "kind": "assistant",
        "text": "I'm getting tangled up. Try restating the request?",
    })
    return trace


# ---- Public entry point ------------------------------------------------------
def turn(messages: list[dict], user_name: str | None = None) -> list[dict]:
    """Run one user turn through the agentic loop. `messages` is the prior
    conversation as a list of {role, content} pairs (role in 'user'|'assistant').
    Returns a trace of tool calls + final assistant text."""
    try:
        provider, key, model = _recog._get_llm_config()
    except Exception as exc:
        return [{
            "kind": "assistant",
            "text": (
                "I can't reach an LLM right now — API keys aren't set. "
                "Open Settings → API to configure one."
            ),
        }]
    system = _jarvis_system_prompt(user_name)
    if provider == "openai":
        client = _recog._get_openai_client(key)
        return _turn_openai(client, model, messages, system)
    client = _recog._get_anthropic_client(key)
    return _turn_anthropic(client, model, messages, system)
