#!/usr/bin/env python3
"""Install only kuggis's hooks, preserving other agent settings and hooks."""
import json
from pathlib import Path
import shlex


def install(path, command, events, json_output=False):
    data = json.loads(path.read_text()) if path.exists() else {}
    hooks = data.setdefault("hooks", {})
    # Remove our previous registrations, including events no longer used.
    for event, entries in list(hooks.items()):
        kept = []
        for entry in entries:
            handlers = [h for h in entry.get("hooks", [])
                        if not h.get("command", "").startswith(command + " ")]
            if handlers:
                kept.append(dict(entry, hooks=handlers))
        hooks[event] = kept
    for event, action, matcher in events:
        invocation = command + " " + action
        if json_output:
            invocation += " && printf '{}'"
        entry = {"hooks": [{"type": "command", "command": invocation}]}
        if matcher:
            entry["matcher"] = matcher
        hooks.setdefault(event, []).append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def main():
    home = Path.home()
    command = shlex.quote(str(home / ".box/hook.sh"))
    common = [
        ("SessionStart", "idle", None),
        ("UserPromptSubmit", "prompt", None),
        ("PostToolUse", "working", None),
        ("Stop", "idle", None),
    ]
    install(home / ".claude/settings.json", command, common + [
        ("PreToolUse", "waiting question", "AskUserQuestion"),
        ("Notification", "waiting permission", "permission_prompt|elicitation_dialog"),
    ])
    install(home / ".codex/hooks.json", command, common + [
        ("PermissionRequest", "waiting permission", None),
        ("PreToolUse", "waiting question", "request_user_input"),
    ], json_output=True)


if __name__ == "__main__":
    main()
