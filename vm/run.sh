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

# Shared lifecycle; agent adapters only choose the executable and resume flags.
. ~/.box/agents.sh
export BOX_AGENT=$agent
export BOX_SESSION_ID=${4:?session identity} BOX_RUN_ID=${5:?run identity}
delivery_pid=''
cleanup() {
  [ -z "$delivery_pid" ] || kill "$delivery_pid" 2>/dev/null || true
  ~/.box/hook.sh stopped
}
trap cleanup EXIT
agent_command "$agent" "$name" || exit $?
set -- "${AGENT_COMMAND[@]}"

# A brief from kuggis dispatch is the session's first message, given once.
first=~/.box/first/$name
if [ -f "$first" ]; then
  msg=$(cat "$first")
  rm -f "$first"
  if [ "${1:-} ${2:-}" = "codex resume" ]; then
    # `codex resume --last` reads a trailing argument as a session name, so the
    # brief is typed in once its screen is up.
    same_run() {
      jq -e --arg id "$BOX_SESSION_ID" --arg run "$BOX_RUN_ID" \
        '.session_id == $id and .run_id == $run' "$HOME/.box/ids/$name" >/dev/null 2>&1
    }
    (sleep 8 && same_run && tmux send-keys -t "=$name:" -l -- "$msg" &&
      sleep 0.3 && same_run && tmux send-keys -t "=$name:" Enter) &
    delivery_pid=$!
  else
    set -- "$@" "$msg"
  fi
fi

"$@"
rc=$?
cleanup
trap - EXIT
if [ $rc -ne 0 ]; then
  echo "box: $1 exited with $rc; press enter to close the session"
  read -r _
fi

exit "$rc"
