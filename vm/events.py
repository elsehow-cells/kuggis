#!/usr/bin/env python3
"""Versioned job events, shadow fold, and compatibility state files (stdlib only).

This is a VM-local diagnostic log, not a security boundary or the cell carrier.
It contains identifiers and enum values only: never prompts, tool input or output.
"""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
AGENTS = {"claude", "codex", "pi"}
ACTIONS = {"starting", "prompt", "working", "idle", "waiting", "needs_you", "stopped", "closed"}
REASONS = {"question", "permission", "blocked", "done"}
FIELDS = {"version", "source", "seq", "time", "session_id", "run_id", "name", "agent", "event", "why"}


def atomic(path, value):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as f:
        f.write(value)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


@contextlib.contextmanager
def locked(root):
    root.mkdir(parents=True, exist_ok=True)
    with (root / "events.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def read(path, default=""):
    return path.read_text().strip() if path.exists() else default


def valid(e):
    if not isinstance(e, dict) or set(e) != FIELDS:
        return False
    if type(e["version"]) is not int or e["version"] != 1:
        return False
    if type(e["seq"]) is not int or e["seq"] < 1 or type(e["time"]) is not int or e["time"] < 0:
        return False
    if not all(isinstance(e[k], str) for k in FIELDS - {"version", "seq", "time"}):
        return False
    if not NAME.fullmatch(e["name"]) or e["agent"] not in AGENTS or e["event"] not in ACTIONS:
        return False
    if e["why"] not in (REASONS if e["event"] in {"waiting", "needs_you"} else {""}):
        return False
    try:
        return all(str(uuid.UUID(e[k])) == e[k] for k in ("source", "session_id", "run_id"))
    except ValueError:
        return False


def transition(previous, action, why):
    state, needs = previous
    if action == "starting":
        return "starting", needs
    if action == "prompt":
        return "working", ""
    if action == "needs_you":
        return "waiting", why
    if action == "waiting":
        return "waiting", needs or why
    if action in {"working", "idle"}:
        # Explicit needs-you survives tool completions and automatic continuations.
        return ("waiting", needs) if needs else (action, "")
    return action, needs if action == "stopped" else ""


def append(root, event):
    """Caller holds events.lock. Reserve before append; crashes may leave gaps."""
    event["seq"] = int(read(root / "event-seq", "0")) + 1
    atomic(root / "event-seq", str(event["seq"]))
    with (root / "events.jsonl").open("ab+") as f:
        if f.tell():
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                f.write(b"\n")  # retain a damaged tail as a rejected line
        f.write((json.dumps(event, separators=(",", ":")) + "\n").encode())
        f.flush()
        os.fsync(f.fileno())
    return event


def emit(root, name, agent, action, why="", expected_id="", expected_run=""):
    if not NAME.fullmatch(name) or agent not in AGENTS or action not in ACTIONS:
        raise ValueError("invalid session, agent or event")
    if why not in (REASONS if action in {"waiting", "needs_you"} else {""}):
        raise ValueError("invalid reason")
    with locked(root):
        for d in ("ids", "state", "needs", "agent"):
            (root / d).mkdir(exist_ok=True)
        ident_path = root / "ids" / name
        ident = json.loads(read(ident_path, "null"))
        migrating = ident is None
        # Hooks cannot resurrect a closed job. Legacy live jobs migrate once.
        if ident is None:
            if action not in {"starting", "closed"} and not (root / "state" / name).exists():
                return None
            if expected_id:
                return None
            ident = {"session_id": str(uuid.uuid4()), "run_id": str(uuid.uuid4())}
        if expected_id and expected_id != ident["session_id"]:
            return None
        if expected_run and expected_run != ident["run_id"]:
            return None
        if action == "starting":
            ident["run_id"] = str(uuid.uuid4())
        atomic(ident_path, json.dumps(ident))
        source = read(root / "event-source") or str(uuid.uuid4())
        atomic(root / "event-source", source)
        needs_path, state_path = root / "needs" / name, root / "state" / name
        template = dict(version=1, source=source, time=int(time.time()),
                        **ident, name=name, agent=agent)
        # Bootstrap an existing needs marker into the shadow log once, so a
        # sync/restart doesn't hide a pending question or produce permanent drift.
        if migrating and read(needs_path) in REASONS:
            append(root, dict(template, event="needs_you", why=read(needs_path)))
        event = append(root, dict(template, event=action, why=why))
        # Temporary permission/question hooks clear when tool execution resumes;
        # only explicit needs-you writes the durable needs marker.
        old = read(state_path, "starting"), read(needs_path)
        state, _ = transition(old, action, why)
        if action == "needs_you":
            atomic(needs_path, why)
        elif action in {"prompt", "closed"}:
            needs_path.unlink(missing_ok=True)
        if action == "closed":
            for d in ("state", "agent", "ids", "first"):
                (root / d / name).unlink(missing_ok=True)
        else:
            atomic(state_path, state + "\n")
            atomic(root / "agent" / name, agent + "\n")
        return event


def fold(lines):
    jobs, sequences, errors = {}, {}, []
    for number, line in enumerate(lines, 1):
        try:
            if len(line) > 4096:
                raise ValueError()
            event = json.loads(line)
            if not valid(event):
                raise ValueError()
        except (ValueError, TypeError):
            errors.append(f"line {number}: invalid event")
            continue
        source, seq = event["source"], event["seq"]
        if seq <= sequences.get(source, 0):
            errors.append(f"line {number}: duplicate or out-of-order sequence")
            continue
        sequences[source] = seq
        key = source, event["session_id"]
        old = jobs.get(key, {"state": "starting", "needs": ""})
        state, _ = transition((old["state"], old["needs"]), event["event"], event["why"])
        needs = old["needs"]
        if event["event"] == "needs_you":
            needs = event["why"]
        elif event["event"] in {"prompt", "closed"}:
            needs = ""
        jobs[key] = dict(event, state=state, needs=needs)
    return list(jobs.values()), errors


def check(root):
    # Check the fold against the retained compatibility files under the same lock.
    with locked(root):
        path = root / "events.jsonl"
        with path.open() if path.exists() else contextlib.nullcontext([]) as lines:
            jobs, errors = fold(lines)
        active = {j["name"]: j for j in jobs if j["state"] != "closed"}
        for name, job in active.items():
            if read(root / "state" / name) != job["state"] or read(root / "needs" / name) != job["needs"]:
                errors.append(f"{name}: shadow state differs")
        for path in (root / "state").glob("*"):
            if path.name not in active:
                errors.append(f"{path.name}: no events yet (restart session to migrate)")
        return {"jobs": jobs, "errors": errors}


def main():
    root = Path.home() / ".box"
    if sys.argv[1:] == ["check"]:
        result = check(root)
        print(json.dumps(result))
        return 1 if result["errors"] else 0
    if len(sys.argv) not in {3, 4} or sys.argv[1] != "emit":
        raise ValueError("usage: events.py emit EVENT [REASON] | check")
    name = os.environ.get("BOX_SESSION", "")
    if not NAME.fullmatch(name):
        raise ValueError("invalid session name")
    agent = os.environ.get("BOX_AGENT") or read(root / "agent" / name, "claude")
    event = emit(root, name, agent, sys.argv[2], sys.argv[3] if len(sys.argv) == 4 else "",
                 os.environ.get("BOX_SESSION_ID", ""), os.environ.get("BOX_RUN_ID", ""))
    if event is None:
        return 3  # stale or closed job: caller must not page
    if sys.argv[2] == "starting":
        print(event["session_id"], event["run_id"])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError) as exc:
        print(f"box events: {exc}", file=sys.stderr)
        sys.exit(1)
