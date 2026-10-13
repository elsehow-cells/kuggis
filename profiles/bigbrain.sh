# box profile for elsehow/BigBrain. bootstrap.sh runs box_setup once per
# VM in the main checkout; run.sh runs box_worktree in each new session's
# worktree, as the repo's CLAUDE.md asks ("bun install once in the new
# worktree, and again in web/ui").
BUN_VERSION=1.3.14 # matches .github/workflows/ci.yml

box_setup() {
  if [ "$(bun --version 2>/dev/null)" != "$BUN_VERSION" ]; then
    curl -fsSL https://bun.sh/install | bash -s "bun-v$BUN_VERSION"
  fi
  bun install --frozen-lockfile
  bun install --frozen-lockfile --cwd web/ui
  # Chromium for the browser suites and headless viewer checks.
  bun run browser:install
}

box_worktree() {
  bun install --frozen-lockfile
  bun install --frozen-lockfile --cwd web/ui
}
