"""Agent adapter contracts with fake executables; no VM changes or model calls."""
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from vm import events

ROOT = Path(__file__).resolve().parent


class Agents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        self.box = self.home / ".box"
        shutil.copytree(ROOT / "vm", self.box)
        for p in self.box.glob("*.sh"):
            p.chmod(0o700)
        (self.box / "needs-you").chmod(0o700)
        (self.box / "config").write_text("BOX_REPO=example/demo\nBOX_PROJECT=demo\n")
        (self.box / "env").write_text("")
        self.bin = self.home / "bin"
        self.bin.mkdir()
        self.log = self.home / "calls"
        self.log.touch()
        self.env = dict(os.environ, HOME=str(self.home), BOX_SESSION="task", BOX_AGENT="claude",
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"], CALLS=str(self.log))
        for key in ("BOX_SESSION_ID", "BOX_RUN_ID"):
            self.env.pop(key, None)
        for agent in events.AGENTS:
            self.script(agent, 'printf "%s\\n" "$0 $*" >>"$CALLS"')
        self.script("tmux", '''case "$1" in
has-session) [ "${LIVE:-0}" = 1 ] ;;
list-sessions) printf 'task\\nother\\n' ;;
list-clients) : ;;
*) printf 'tmux %s\\n' "$*" >>"$CALLS" ;;
esac''')
        self.script("stat", 'echo 0')
        self.script("systemd-run", 'exit 0')
        self.script("curl", 'echo forbidden-notification >>"$CALLS"; exit 99')

    def script(self, name, body):
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o700)

    def run_box(self, script, *args, env=None, cwd=None):
        return subprocess.run(["bash", str(self.box / script), *args], env=env or self.env,
                              cwd=cwd or self.home, input="", text=True, capture_output=True, timeout=15)

    def start(self, agent="claude", name="task"):
        e = events.emit(self.box, name, agent, "starting")
        return dict(self.env, BOX_AGENT=agent, BOX_SESSION=name,
                    BOX_SESSION_ID=e["session_id"], BOX_RUN_ID=e["run_id"])

    def hook(self, action, *args, env=None):
        r = self.run_box("hook.sh", action, *args, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_every_agent_has_same_needs_you_and_status(self):
        for agent in sorted(events.AGENTS):
            with self.subTest(agent=agent):
                env = self.start(agent)
                self.hook("prompt", env=env)
                self.assertEqual(events.read(self.box / "state/task"), "working")
                r = self.run_box("needs-you", "blocked", "synthetic private text", env=env)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.hook("working", env=env)
                self.hook("idle", env=env)
                r = self.run_box("session.sh", "status", env=dict(env, LIVE="1"))
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("waiting on you (blocked)", r.stdout)
                if agent != "claude":
                    self.assertIn(f"({agent})", r.stdout)
                bar = self.run_box("status.sh", "left", "other", env=env)
                self.assertIn("⚑ task", bar.stdout)
                self.hook("prompt", env=env)
                self.hook("idle", env=env)
                self.assertEqual(events.read(self.box / "state/task"), "idle")
                self.assertFalse((self.box / "needs/task").exists())
                self.assertEqual(events.check(self.box)["errors"], [])
        self.assertNotIn("synthetic private text", (self.box / "events.jsonl").read_text())
        self.assertNotIn("forbidden-notification", self.log.read_text())

    def test_permission_clears_on_tool_completion_not_persistent_needs(self):
        env = self.start("codex")
        self.hook("waiting", "permission", env=env)
        self.assertEqual(events.read(self.box / "state/task"), "waiting")
        self.hook("working", env=env)
        self.assertEqual(events.read(self.box / "state/task"), "working")
        self.assertEqual(events.check(self.box)["errors"], [])

    def test_stable_identity_restart_late_hook_and_name_reuse(self):
        first = events.emit(self.box, "task", "claude", "starting")
        second = events.emit(self.box, "task", "codex", "starting")
        self.assertEqual(first["session_id"], second["session_id"])
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertIsNone(events.emit(self.box, "task", "claude", "idle",
                          expected_id=first["session_id"], expected_run=first["run_id"]))
        events.emit(self.box, "task", "codex", "closed")
        self.assertIsNone(events.emit(self.box, "task", "codex", "stopped",
                                     expected_id=second["session_id"]))
        third = events.emit(self.box, "task", "pi", "starting")
        self.assertNotEqual(third["session_id"], first["session_id"])
        self.assertEqual(events.check(self.box)["errors"], [])

    def test_existing_needs_marker_migrates_without_losing_attention(self):
        (self.box / "state").mkdir()
        (self.box / "needs").mkdir()
        (self.box / "state/task").write_text("idle")
        (self.box / "needs/task").write_text("blocked")
        events.emit(self.box, "task", "codex", "starting")
        report = events.check(self.box)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["jobs"][0]["needs"], "blocked")

    def test_late_hook_does_not_page_or_recreate_state(self):
        env = self.start("codex")
        events.emit(self.box, "task", "codex", "closed")
        (self.box / "config").write_text("BOX_PROJECT=demo\nBOX_NTFY=synthetic-topic\n")
        self.hook("needs_you", "blocked", env=env)
        self.assertFalse((self.box / "state/task").exists())
        self.assertNotIn("forbidden-notification", self.log.read_text())

    def test_each_agent_resumes_only_its_own_history(self):
        env = self.start()
        import re
        sanitized = re.sub(r"[^A-Za-z0-9]", "-", str(self.home))
        history = self.home / ".claude/projects" / sanitized
        history.mkdir(parents=True)
        (history / "saved.jsonl").write_text("{}")
        history = self.home / ".codex/sessions"
        history.mkdir(parents=True)
        (history / "saved.jsonl").write_text(json.dumps({"cwd": str(self.home)}, separators=(",", ":")))
        for agent, expected in [("claude", "claude --continue"), ("codex", "codex resume --last"),
                                ("pi", "pi --session-dir")]:
            r = subprocess.run(["bash", "-c", '. "$HOME/.box/agents.sh"; agent_command "$1" task; printf "%s " "${AGENT_COMMAND[@]}"', "test", agent],
                               env=env, cwd=self.home, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(r.stdout.startswith(expected), r.stdout)
            if agent == "pi":
                self.assertIn(env["BOX_SESSION_ID"], r.stdout)

    def test_concurrent_append_has_unique_ordered_sequences(self):
        self.start()
        cmd = [shutil.which("python3"), "-I", str(self.box / "events.py"), "emit", "working"]
        def run(_):
            return subprocess.run(cmd, env=self.env, capture_output=True).returncode
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(list(pool.map(run, range(24))), [0] * 24)
        lines = (self.box / "events.jsonl").read_text().splitlines()
        self.assertEqual([json.loads(s)["seq"] for s in lines], list(range(1, 26)))
        self.assertEqual(events.check(self.box)["errors"], [])

    def test_fold_rejects_shapes_duplicates_and_damaged_tail_and_finds_drift(self):
        first = events.emit(self.box, "task", "pi", "starting")
        bad = dict(first, version=99)
        extra = dict(first, prompt="must not be accepted")
        jobs, errors = events.fold(map(json.dumps, [first, first, bad, extra, None]))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(len(errors), 4)
        with (self.box / "events.jsonl").open("a") as f:
            f.write('{"partial":')
        events.emit(self.box, "task", "pi", "idle")
        report = events.check(self.box)
        self.assertEqual(len(report["errors"]), 1)
        self.assertEqual(report["jobs"][0]["state"], "idle")
        (self.box / "state/task").write_text("working\n")
        self.assertIn("task: shadow state differs", events.check(self.box)["errors"])

    def test_missing_and_unknown_agents_fail_before_creating_worktree(self):
        (self.bin / "pi").unlink()
        # Make availability deterministic even if developer has Pi installed.
        self.script("pi", "exit 0")
        (self.bin / "pi").unlink()
        for name in ("nonsense", "../bad"):
            r = self.run_box("session.sh", "attach", "task", name)
            self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.home / "demo").exists())
        r = subprocess.run(["bash", "-c", '. "$HOME/.box/agents.sh"; PATH=/nonexistent; agent_check pi'],
                           env=self.env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not installed", r.stderr)

    def test_switch_or_delivery_to_active_other_runtime_refused(self):
        env = dict(self.start("codex"), LIVE="1")
        brief = self.home / "brief.md"
        brief.write_text("synthetic brief")
        for args in [("attach", "task", "pi"), ("deliver", "task", "pi", str(brief))]:
            r = self.run_box("session.sh", *args, env=env)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("running codex", r.stderr)
        self.assertNotIn("send-keys", self.log.read_text())
        self.assertNotIn("attach-session", self.log.read_text())

    def test_run_selects_each_agent_delivers_brief_and_stops(self):
        for agent in sorted(events.AGENTS):
            env = self.start(agent)
            (self.box / "first").mkdir(exist_ok=True)
            (self.box / "first/task").write_text("synthetic task")
            r = self.run_box("run.sh", "task", agent, "0", env["BOX_SESSION_ID"], env["BOX_RUN_ID"], env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(f"/bin/{agent} ", self.log.read_text())
            self.assertIn("synthetic task", self.log.read_text())
            self.assertFalse((self.box / "first/task").exists())
            self.assertEqual(events.read(self.box / "state/task"), "stopped")
        self.assertIn("--extension", self.log.read_text())
        self.assertEqual(events.check(self.box)["errors"], [])

    def test_finish_refuses_dirty_work_and_cleans_all_markers_when_safe(self):
        env = self.start("pi")
        wt = self.home / "demo/.claude/worktrees/task"
        wt.mkdir(parents=True)
        self.script("git", 'case "$*" in *"status --porcelain"*) echo " M file" ;; esac')
        r = self.run_box("session.sh", "done", "task", env=env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("uncommitted", r.stderr)
        self.assertNotIn("kill-session", self.log.read_text())
        self.script("git", 'exit 0')
        self.hook("needs_you", "done", env=env)
        (self.box / "first").mkdir()
        (self.box / "first/task").write_text("old")
        r = self.run_box("session.sh", "done", "task", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        for folder in ("state", "agent", "needs", "ids", "first"):
            self.assertFalse((self.box / folder / "task").exists(), folder)
        self.assertEqual(events.check(self.box)["jobs"][0]["state"], "closed")

    def test_hook_configuration_is_idempotent_preserves_unrelated_handlers(self):
        p = self.home / ".codex/hooks.json"
        p.parent.mkdir()
        p.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other-hook"}]}]}}))
        command = [shutil.which("python3"), "-I", str(self.box / "configure-hooks.py")]
        for _ in range(2):
            subprocess.run(command, env=self.env, check=True)
        hooks = json.loads(p.read_text())["hooks"]
        self.assertEqual(len(hooks["Stop"]), 2)
        self.assertEqual(hooks["Stop"][0]["hooks"][0]["command"], "other-hook")
        for path in (p, self.home / ".claude/settings.json"):
            data = json.loads(path.read_text())
            for entries in data["hooks"].values():
                for entry in entries:
                    for h in entry["hooks"]:
                        if ".box/hook.sh" in h["command"]:
                            self.assertNotIn("allow", h["command"])

    @unittest.skipUnless(shutil.which("node"), "Node required for Pi extension contract")
    def test_pi_extension_reports_lifecycle_without_exposing_payloads(self):
        self.start("pi")
        # The extension intentionally uses plain JS; load identical source as ESM.
        extension = self.home / "extension.mjs"
        extension.write_text((self.box / "pi-extension.ts").read_text())
        driver = self.home / "driver.mjs"
        driver.write_text('''import setup from "./extension.mjs";
const hooks = new Map(), bus = new Map();
setup({on: (n, f) => hooks.set(n, f), events: {on: (n, f) => bus.set(n, f)}});
await hooks.get("session_start")({});
await hooks.get("input")({source: "interactive", text: "private prompt"});
await hooks.get("agent_start")({});
bus.get("kuggis:needs-you")({why: "permission", text: "secret"});
await hooks.get("tool_execution_end")({});
await hooks.get("agent_settled")({});
await hooks.get("session_shutdown")({});
''')
        result = subprocess.run(["node", str(driver)], env=dict(self.env, BOX_AGENT="pi"),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        records = [json.loads(l) for l in (self.box / "events.jsonl").read_text().splitlines()]
        self.assertEqual([r["event"] for r in records],
                         ["starting", "idle", "prompt", "working", "waiting", "working", "idle", "stopped"])
        self.assertNotIn("private prompt", str(records))
        self.assertNotIn("secret", str(records))


if __name__ == "__main__":
    unittest.main()
