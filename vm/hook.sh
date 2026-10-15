#!/usr/bin/env bash
# All adapters report the same lifecycle. Never forwards raw hook payloads.
set -uo pipefail
name=${BOX_SESSION:-}
[ -n "$name" ] || exit 0
action=${1:-} reason=${2:-}
case $action in
  ping) action=idle; reason='' ;; # compatibility with older Codex notify config
  waiting) reason=${reason:-permission} ;;
  needs_you) ;;
  prompt|working|idle|stopped) reason='' ;;
  *) echo "box: unknown lifecycle event" >&2; exit 2 ;;
esac
args=(emit "$action")
[ -z "$reason" ] || args+=("$reason")
python3 -I ~/.box/events.py "${args[@]}"
rc=$?
[ "$rc" != 3 ] || exit 0 # late event from a closed or restarted session
[ "$rc" = 0 ] || exit "$rc"
# Refresh waiting flags for every runtime.
tmux list-clients -F '#{client_name}' 2>/dev/null |
  while read -r c; do tmux refresh-client -S -t "$c"; done >/dev/null 2>&1
case $action in waiting|needs_you) ;; *) exit 0 ;; esac
last=$(tmux list-clients -t "=$name" -F '#{client_activity}' 2>/dev/null | sort -n | tail -1)
[ -z "$last" ] || [ $(($(date +%s) - last)) -ge 120 ] || exit 0
. ~/.box/config 2>/dev/null
[ -n "${BOX_NTFY:-}" ] || exit 0
# Only explicit needs-you carries the agent's short line; ordinary tool and
# permission payloads may contain secrets and never reach notifications or log.
msg=${3:-$reason}
curl -fsS -m 5 -H "Title: $BOX_PROJECT/$name" -d "${msg:-waiting on you}" \
  "https://ntfy.sh/$BOX_NTFY" >/dev/null 2>&1 &
exit 0
