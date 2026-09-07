"""UserPromptSubmit hook: route informal chat commands through the prompt generator.

Claude Code pipes the submitted prompt to this script as JSON on stdin. Whatever the
script prints to stdout is appended to the model's context for that turn. The script
decides whether the message looks like a work request; if so it injects a reminder to
run the /do sequence (prompt-generator -> target agent -> docs-scribe) instead of
starting to read files directly.

Kept dependency-free so it runs on the system Python without the project venv.
"""

from __future__ import annotations

import json
import sys

# Messages that are clearly not work requests: slash commands, one-word replies,
# approvals, and questions about the conversation itself.
_SKIP_EXACT = {
    "y",
    "yes",
    "n",
    "no",
    "ok",
    "okay",
    "approved",
    "approve",
    "go",
    "go ahead",
    "proceed",
    "continue",
    "thanks",
    "thank you",
}

# Verbs that usually open an engineering request. Matching is deliberately loose;
# a false positive only costs one short reminder line.
_WORK_VERBS = (
    "add",
    "build",
    "change",
    "check",
    "create",
    "debug",
    "fix",
    "implement",
    "improve",
    "investigate",
    "make",
    "move",
    "optimi",
    "refactor",
    "remove",
    "rename",
    "replace",
    "show",
    "speed",
    "test",
    "update",
    "why",
    "write",
)

_REMINDER = (
    "[prompt-router] This looks like an informal work request. Before reading any "
    "source file, run the /do sequence: launch the `prompt-generator` agent with the "
    "user's exact words, print the brief it returns, then delegate the brief to the "
    "TARGET AGENT it names, and finish with `docs-scribe`. Do not investigate or "
    "implement in the main session. If the user is only asking a question or replying "
    "to you, ignore this reminder."
)


def _looks_like_work(prompt: str) -> bool:
    text = prompt.strip().lower()
    if not text or text.startswith("/"):
        return False
    if text in _SKIP_EXACT:
        return False
    if len(text.split()) < 3:
        return False
    return any(verb in text for verb in _WORK_VERBS)


def main() -> int:
    """Read the hook payload, print the reminder when warranted, always exit 0."""
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    prompt = payload.get("prompt", "") if isinstance(payload, dict) else ""
    if _looks_like_work(str(prompt)):
        sys.stdout.write(_REMINDER)
    return 0


if __name__ == "__main__":
    sys.exit(main())
