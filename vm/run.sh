#!/usr/bin/env bash
# Runs inside a box tmux session: set up a fresh worktree, then the agent.
# The session ends when the agent exits; `box <project> <name>` resumes the
# conversation that last ran in this worktree.
set -uo pipefail
. ~/.box/config
. ~/.box/env

name=$1 agent=$2 fresh=$3
export BOX_SESSION=$name

if [ "$fresh" = 1 ] && [ -f ~/.box/profile.sh ]; then
  . ~/.box/profile.sh
  if type box_worktree >/dev/null 2>&1; then
    box_worktree || echo "box: worktree setup failed; starting $agent anyway"
  fi
fi

# A project-local virtualenv (set up by the profile) is active for the agent.
if [ -f .venv/bin/activate ]; then . .venv/bin/activate; fi

case $agent in
  codex)
    cx=~/.codex/config.toml
    grep -qF "[projects.\"$PWD\"]" "$cx" 2>/dev/null ||
      printf '\n[projects."%s"]\ntrust_level = "trusted"\n' "$PWD" >>"$cx"
    # Codex rollouts record their cwd; `resume --last` filters by cwd.
    if grep -rqF "\"cwd\":\"$PWD\"" ~/.codex/sessions 2>/dev/null; then
      set -- codex resume --last
    else
      set -- codex
    fi ;;
  *)
    # Claude keeps transcripts under ~/.claude/projects/<cwd, non-alphanumerics as ->.
    if ls "$HOME/.claude/projects/$(pwd | sed 's/[^A-Za-z0-9]/-/g')"/*.jsonl >/dev/null 2>&1; then
      set -- claude --continue
    else
      set -- claude -n "$name"
    fi ;;
esac

"$@"
rc=$?
if [ $rc -ne 0 ]; then
  echo "box: $1 exited with $rc; press enter to close the session"
  read -r _
fi
