"""Quick smoke test of the JARVIS agent. Run with PYTHONPATH=/opt/house-inventory."""
from assistant import chat

trace = chat.turn(
    [{"role": "user", "content": "What is on my schedule today and what should I be aware of?"}],
    "Justin",
)
for entry in trace:
    k = entry.get("kind")
    if k == "tool_call":
        print(f"  -> {entry['name']}({entry.get('args', {})})")
    elif k == "assistant":
        print(f"\n[assistant]\n{entry['text'][:600]}\n")
