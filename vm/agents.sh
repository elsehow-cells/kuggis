#!/usr/bin/env bash
# Agent-specific launch/resume policy. The session lifecycle lives elsewhere.
agent_valid() { case $1 in claude|codex|pi) return 0 ;; *) return 1 ;; esac; }
agent_check() {
  agent_valid "$1" || { echo "box: unknown agent '$1' (claude, codex, pi)" >&2; return 2; }
  command -v "$1" >/dev/null || { echo "box: $1 is not installed on this VM" >&2; return 1; }
}
agent_command() {
  local agent=$1 name=$2 cx
  agent_check "$agent" || return
  case $agent in
    claude)
      if ls "$HOME/.claude/projects/$(pwd | sed 's/[^A-Za-z0-9]/-/g')"/*.jsonl >/dev/null 2>&1; then
        AGENT_COMMAND=(claude --continue)
      else
        AGENT_COMMAND=(claude -n "$name")
      fi ;;
    codex)
      mkdir -p ~/.codex
      cx=~/.codex/config.toml
      grep -qF "[projects.\"$PWD\"]" "$cx" 2>/dev/null ||
        printf '\n[projects."%s"]\ntrust_level = "trusted"\n' "$PWD" >>"$cx"
      if grep -rqF "\"cwd\":\"$PWD\"" ~/.codex/sessions 2>/dev/null; then
        AGENT_COMMAND=(codex resume --last)
      else
        AGENT_COMMAND=(codex)
      fi ;;
    pi)
      # A dedicated history directory prevents another worktree's history from
      # being resumed. --continue also creates a session when none exists.
      mkdir -p "$HOME/.box/pi-sessions/$BOX_SESSION_ID"
      AGENT_COMMAND=(pi --session-dir "$HOME/.box/pi-sessions/$BOX_SESSION_ID"
        --continue --extension "$HOME/.box/pi-extension.ts") ;;
  esac
}
