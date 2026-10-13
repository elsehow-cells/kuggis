#!/usr/bin/env bash
# VM side of box: list, attach to, and end sessions. A session is a tmux
# session and a git worktree of the same name under the repo's
# .claude/worktrees/, plus a state file the Claude hooks keep current.
set -euo pipefail
. ~/.box/config
. ~/.box/env

REPO=$HOME/${BOX_REPO##*/}
WT=$REPO/.claude/worktrees
STATE=$HOME/.box/state
AGENT=$HOME/.box/agent # claude | codex, per session; absent means claude

die() { echo "box: $*" >&2; exit 1; }
alive() { tmux has-session -t "=$1" 2>/dev/null; }
agent_of() { cat "$AGENT/$1" 2>/dev/null || echo claude; }

ago() {
  local s=$1
  if [ "$s" -lt 60 ]; then echo "${s}s"
  elif [ "$s" -lt 3600 ]; then echo "$((s / 60))m"
  elif [ "$s" -lt 86400 ]; then echo "$((s / 3600))h"
  else echo "$((s / 86400))d"
  fi
}

status() {
  local f name state now
  now=$(date +%s)
  for f in "$STATE"/*; do
    [ -f "$f" ] || continue
    name=$(basename "$f")
    if ! alive "$name"; then
      state=stopped
    elif [ "$(agent_of "$name")" = codex ]; then
      state=running # Codex reports finished turns only, not working/waiting
    else
      state=$(cat "$f")
      [ "$state" = waiting ] && state="waiting on you"
    fi
    [ "$(agent_of "$name")" = claude ] || state="$state (codex)"
    printf '%s\t%s\t%s\n' "$name" "$state" "$(ago $((now - $(stat -c %Y "$f"))))"
  done
}

new_worktree() {
  local name=$1 wt=$2 base
  git -C "$REPO" fetch -q --prune origin
  if git -C "$REPO" show-ref -q --verify "refs/heads/$name"; then
    git -C "$REPO" worktree add -q "$wt" "$name"
  elif git -C "$REPO" show-ref -q --verify "refs/remotes/origin/$name"; then
    git -C "$REPO" worktree add -q --track -b "$name" "$wt" "origin/$name"
  else
    base=$(git -C "$REPO" symbolic-ref -q --short refs/remotes/origin/HEAD || echo origin/main)
    git -C "$REPO" worktree add -q --no-track -b "$name" "$wt" "$base"
  fi
}

# Start the tmux server under the systemd user manager (lingering, so it
# outlives every ssh connection) and with a command line that names no
# session, path or agent, so a broad `pkill -f` can't hit it. Idempotent.
ensure_server() {
  local cmd=(tmux start-server \; set -g exit-empty off)
  XDG_RUNTIME_DIR=/run/user/$(id -u) systemd-run --user --scope --quiet "${cmd[@]}" 2>/dev/null ||
    "${cmd[@]}"
}

attach() {
  local name=$1 want=${2:-} wt=$WT/$1 fresh=0 agent
  mkdir -p "$STATE" "$AGENT"
  agent=$(agent_of "$name")
  if alive "$name"; then
    [ -z "$want" ] || [ "$want" = "$agent" ] ||
      echo "box: $name is already running $agent; attaching to that" >&2
  else
    if [ ! -d "$wt" ]; then
      new_worktree "$name" "$wt"
      fresh=1
    fi
    agent=${want:-$agent}
    echo "$agent" >"$AGENT/$name"
    echo starting >"$STATE/$name"
    ensure_server
    tmux new-session -d -s "$name" -c "$wt" "$HOME/.box/run.sh $name $agent $fresh"
  fi
  # -d drops any other client, such as one left by a laptop that went to sleep.
  exec tmux attach-session -d -t "=$name"
}

finish() {
  local name=$1 force=${2:-} wt=$WT/$1
  [ -d "$wt" ] || [ -f "$STATE/$name" ] || die "no session $name"
  if [ -d "$wt" ] && [ "$force" != --force ]; then
    [ -z "$(git -C "$wt" status --porcelain)" ] ||
      die "$name has uncommitted changes (--force discards them)"
    git -C "$REPO" fetch -q --prune origin
    if [ -n "$(git -C "$wt" log --oneline HEAD --not --remotes)" ]; then
      # A squash-merged branch's commits are on no remote; a merged PR is enough.
      [ "$(cd "$wt" && gh pr view --json state -q .state 2>/dev/null)" = MERGED ] ||
        die "$name has commits on no remote and no merged PR (push them, or --force)"
    fi
  fi
  tmux kill-session -t "=$name" 2>/dev/null || true
  if [ -d "$wt" ]; then
    git -C "$REPO" worktree remove ${force:+--force} "$wt"
    git -C "$REPO" branch -D "$name" >/dev/null 2>&1 || true
  fi
  rm -f "$STATE/$name" "$AGENT/$name"
  echo "done: $name"
}

case ${1:-} in
  status) status ;;
  attach) attach "$2" "${3:-}" ;;
  done) finish "$2" "${3:-}" ;;
  *) die "usage: session.sh status | attach <name> [claude|codex] | done <name> [--force]" ;;
esac
