# kuggis

Claude Code sessions on exe.dev VMs: one VM per project, one tmux session
and git worktree per session. Run `kuggis help` for the commands.

Setup on the laptop, once:

1. `ln -s ~/Projects/kuggis/kuggis ~/.local/bin/kuggis`
2. `ssh exe.dev integrations setup github` — link GitHub to exe.dev
3. `kuggis token` — mint a Claude token into the keychain
4. Optional, for `--codex` sessions: `ssh exe.dev integrations setup chatgpt`,
   then `ssh exe.dev integrations add llm --name codex --openai=chatgpt
   --openai-account=<name> --anthropic=disabled --fireworks=disabled
   --attach tag:box`. Codex then runs on your ChatGPT plan with no OpenAI
   credential on the VM.
5. Optional: put an ntfy topic in `~/.config/kuggis/ntfy` and subscribe to it
   on your phone, to get pinged when a session waits on you.

Then `kuggis new <project> <owner/repo>` and `kuggis <project> <session>`.
`kuggis` on its own shows what's waiting on you: briefs from the Thinker, open
PRs with its reviews, and every session, with a live preview of the highlighted
one (a session's current screen). Enter opens it, ctrl-x closes a session
(`kuggis done`), and the list refreshes itself. Detach from a session with
`C-b d` to come back to it. Merging a PR offers to close its session.
ctrl-t on a PR has the Thinker review it in the background (headless, in its
room, on Opus; `KUGGIS_REVIEW_MODEL` changes that); the row shows it working,
then its verdict.
It uses [fzf](https://github.com/junegunn/fzf) when installed (`brew install
fzf`), and a numbered menu otherwise.

`kuggis web` opens the cell dashboard on 127.0.0.1:7480
(`KUGGIS_WEB_PORT` changes it). Cells stay in a fixed order; sessions stay
alphabetical within their project, even when their state changes. A red dot
means the session needs you (including a stopped session or an unreachable
VM). Click a row, or focus it and press Enter, to copy its command. Session
commands still use the **project** name: `kuggis airo <session>`, not
`kuggis forecasting <session>`.

The Thinker appears under trusted when installed or when briefs are pending.
Pending briefs appear in their destination's cell with their waiting age;
clicking one copies `kuggis dispatch`. Unknown destinations appear under
unassigned. The Thinker row copies `kuggis think`. Opening this overview only
reads session state and brief metadata: it never starts a review or queries
GitHub. A failed refresh keeps the last snapshot visibly marked as stale.

The **PRs** link opens the existing review tools at `/reviews`: ask for a
Thinker review (T), merge (M), send a review to its session (S), or close a
session (X). AIRO agents review and merge on their VM; they don't need this
human review loop.
Only a page holding the token in `~/.config/kuggis/web.token` can use the API;
`kuggis web` opens it with that token. The themes are BigBrain's.

### Cell display definitions

This is the first UI step of the cells plan. It reads the existing session
snapshot, **not a typed event log**, and does not enforce cell isolation or
crossing rules. ForecastBench, publishing, releases, audit and seal are not
implemented. Only pending briefs currently produce crossing rows.

Without configuration, familiar project names (or the `airo`/`bigbrain`
profiles) supply display groupings. Unknown projects remain unassigned;
kuggis itself always appears under operator, outside cells. Click a heading
to inspect its read-only definition; inferred groupings are explicitly marked
as having no enforced definition.

Optional private display definitions live in
`~/.config/kuggis/cells/<cell>.json` (or `$KUGGIS_CONFIG/cells`). For example:

```json
{"version": 1, "cell": "forecasting", "projects": ["airo", "agent-box"]}
```

These small JSON files need no extra dependencies and are **display metadata**,
separate from the future enforced YAML policy in the plan. Their format is in
`web/cell-display.schema.json`; an optional `definition` object can hold notes
to inspect. The dialog shows the exact file and SHA256, never an enforcement
commit. Explicit membership replaces inference for that cell. Duplicate
membership, invalid files and attempts to put kuggis inside a cell surface as
errors. Configured cells remain visible even without sessions. The fixed order
is trusted, forecasting, merrillfront-dev, bigbrain-dev, bigbrain-others, hiring,
then custom cells alphabetically, then operator and unassigned.

Keep these definitions private; do not commit personal data or credentials.
No configuration is written by the dashboard. After upgrading kuggis, restart
an already-running `kuggis web` process to load the new server.

The Thinker, an agent that
reads your vault and the web from a contained room on the laptop, is in
`think/README.md`.

What lands on a VM: the Claude token (model requests only; claude.ai
connectors stay off). What never does: a GitHub token (exe.dev's GitHub
integration handles git and `gh` for one repo), your SSH keys, API keys.

`vm/` is copied to `~/.box` on each VM by `kuggis sync`; `profiles/<project>.sh`
holds per-project setup (`box_setup` once, `box_worktree` per session).

Inside a session, the tmux bar shows `project · session` in a colour fixed
per project, any other session on that VM that is waiting on you (`⚑ name 10m`),
and whether the worktree has uncommitted or unpushed work. `✓ pushed` means
`kuggis done` will go through. Terminal tabs are titled `project/session`.

The tool and its laptop config (`~/.config/kuggis`) are `kuggis`. The on-VM
plumbing deliberately kept the `box` prefix — the on-VM dir (`~/.box`), the
`BOX_*` session variables and the `box` VM tag — because renaming those would
have disturbed VMs that already exist. It's invisible from the laptop.

## Recovery

- **Laptop slept, terminal frozen.** The agent kept working on the VM, and
  `kuggis` reattaches on its own once ssh gives up on the dead connection (~45s
  after wake). Press Enter, `~`, `.` to skip the wait. Ctrl-C while it's
  reconnecting stops it; detaching (`C-b d`) leaves without reconnecting.
- **`kuggis` shows a session as `stopped`.** Its process is gone (VM restart, or
  the agent exited). `kuggis <project> <name>` starts it again: the conversation
  resumes (`claude --continue`, `codex resume --last`) and the worktree's files
  are as they were. Whatever command was mid-run is lost, and the agent waits
  for you, so tell it to carry on.
- **`waiting on you`** means a permission prompt or a finished turn. You get an
  ntfy ping unless you typed in that session in the last two minutes.
- **`kuggis done` refuses.** The worktree has uncommitted or unpushed work. Push
  it, or pass `--force` to discard it.
