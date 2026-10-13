# box profile for elsehow/airo. bootstrap.sh runs box_setup once per VM;
# run.sh runs box_worktree in each new session's worktree, whose .venv it
# then activates for the agent.

box_setup() {
  command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
  # The editable install leaves this behind; keep it out of `git status`
  # so `box done` doesn't read it as unsaved work.
  grep -qxF 'redlines.egg-info/' .git/info/exclude || echo 'redlines.egg-info/' >>.git/info/exclude
}

box_worktree() {
  uv venv -q .venv
  uv pip install -q --python .venv/bin/python -e '.[acquire,test,paper]'
}
