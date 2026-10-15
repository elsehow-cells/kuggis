"""Read-only dashboard projection. This is not the cell policy or event fold.

Private display definitions live in $KUGGIS_CONFIG/cells/*.json. Membership
here groups the UI; it grants no access and does not certify isolation.
"""
import hashlib
import json
import re
from pathlib import Path

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
ORDER = ("trusted", "forecasting", "merrillfront-dev", "bigbrain-dev",
         "bigbrain-others", "hiring")
DEFAULTS = {
    "airo": "forecasting", "agent-box": "forecasting",
    "merrillfront": "merrillfront-dev", "ibkr-transition": "merrillfront-dev",
    "bigbrain": "bigbrain-dev", "fri-hiring": "hiring",
}


def load_definitions(config):
    definitions, owners = {}, {}
    for path in sorted((Path(config) / "cells").glob("*.json")):
        raw = path.read_text()
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) - {"version", "cell", "projects", "definition"}:
            raise ValueError(f"{path.name}: invalid display definition")
        name, projects = data.get("cell"), data.get("projects")
        if (type(data.get("version")) is not int or data["version"] != 1
                or not isinstance(name, str) or not NAME.fullmatch(name)
                or name != path.stem or name in ("operator", "unassigned")
                or not isinstance(projects, list)
                or any(not isinstance(p, str) or not NAME.fullmatch(p) for p in projects)
                or not isinstance(data.get("definition", {}), dict)):
            raise ValueError(f"{path.name}: expected version 1, matching cell name and project names")
        for project in projects:
            if project == "kuggis":
                raise ValueError("kuggis belongs outside the cells")
            if project in owners:
                raise ValueError(f"project {project} belongs to more than one cell")
            owners[project] = name
        definitions[name] = {
            "source": str(path), "sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "text": raw, "enforced": False,
        }
    return definitions, owners


def project(snapshot, config):
    definitions, owners = load_definitions(config)
    cells = {}

    def cell(name):
        if name not in cells:
            cells[name] = {"name": name, "rows": [], "projects": [],
                           "definition": definitions.get(name), "needs_you": 0}
        return cells[name]

    def membership(p):
        name = p["name"]
        if name == "kuggis":
            return "operator"
        if name in owners:
            return owners[name]
        inferred = DEFAULTS.get(name, DEFAULTS.get(p.get("profile"), "unassigned"))
        return "unassigned" if inferred in definitions else inferred

    mapping = {p["name"]: membership(p) for p in snapshot["projects"]}
    for name in definitions:
        cell(name)
    for p in snapshot["projects"]:
        cell(mapping[p["name"]])["projects"].append(p["name"])

    # The source exposes only brief metadata, never brief contents or reviews.
    briefs = snapshot.get("briefs", [])
    if snapshot.get("thinker_installed") or briefs:
        cell("trusted")["rows"].append({
            "id": "thinker", "kind": "thinker", "name": "Thinker", "project": "",
            "state": f"{len(briefs)} brief{'s' if len(briefs) != 1 else ''} waiting" if briefs else "no pending briefs",
            "needs_you": bool(briefs), "command": "kuggis think", "age": "",
        })

    for s in sorted(snapshot["sessions"], key=lambda x: (x["project"], x["name"])):
        name = mapping.get(s["project"], "unassigned")
        if s["name"] == "-":
            if s["state"] != "unreachable":
                continue
            row = {"id": f"vm:{s['project']}", "kind": "vm", "name": s["project"],
                   "project": s["project"], "state": "unreachable", "age": "",
                   "needs_you": True, "command": f"kuggis sh {s['project']}"}
        else:
            valid = NAME.fullmatch(s["project"]) and NAME.fullmatch(s["name"])
            row = {**s, "id": f"session:{s['project']}/{s['name']}", "kind": "session",
                   "needs_you": s["state"].startswith(("waiting", "stopped")),
                   "command": f"kuggis {s['project']} {s['name']}" if valid else None}
        cell(name)["rows"].append(row)

    for b in sorted(briefs, key=lambda x: x["id"]):
        name = mapping.get(b["project"], "unassigned")
        cell(name)["rows"].append({
            "id": f"brief:{b['id']}", "kind": "door", "name": f"brief / {b['session']}",
            "project": b["project"], "state": "awaiting dispatch", "needs_you": True,
            "since": b["since"], "command": "kuggis dispatch", "age": "",
        })

    def rank(name):
        return (ORDER.index(name), "") if name in ORDER else (len(ORDER) + (name in ("operator", "unassigned")), name)

    result = []
    for name in sorted(cells, key=rank):
        c = cells[name]
        c["projects"].sort()
        c["needs_you"] = sum(r["needs_you"] for r in c["rows"])
        working = sum(r["state"].startswith(("starting", "working", "running")) for r in c["rows"])
        status = []
        if working:
            status.append(f"{working} working")
        if c["needs_you"]:
            status.append(f"{c['needs_you']} need{'s' if c['needs_you'] == 1 else ''} you")
        c["status"] = " · ".join(status) if status else ("no sessions" if not c["rows"] else "quiet")
        result.append(c)
    return {"cells": result, "now": snapshot["now"], "source": "session snapshot"}
