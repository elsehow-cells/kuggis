## This project: AIRO

- **Ask before spending.** The model and search keys in this environment are
  capped dev keys, separate from the production cron's, but they cost real
  money. Before any command that calls a model or search API
  (`code/run_unified.py`, `code/run_ladder_joint.py`, anything that reaches
  litellm or `redlines/tools.py`), tell the user what it will run and roughly
  what it will cost, and wait for a yes.
- **No keys needed for the rest.** `python3 -m redlines build` and `pytest`
  run without keys. This worktree's `.venv` is already active.
- **Production lives elsewhere.** The forecast cron and the published
  dashboard run on another machine you can't reach, from
  `forecastingresearch/airo`. Merging into `elsehow/airo` does not deploy.
  Promoting work upstream and deploying are the user's job.
- **Public repo.** The repo is public: no personal information in commits, and
  experiment write-ups stay out of it. Keep personal information out of PRs
  and reviews too.
- **Finish by merging on the fork.** For AIRO, this replaces the generic
  "Finishing" instruction above: you may merge your own PR into
  `elsehow/airo` once the checks and review below pass. Push your branch to
  the fork (`origin`) and open the PR explicitly with
  `gh pr create -R elsehow/airo --base main --head <branch>`.
  Never open or merge a PR on `forecastingresearch/airo`.
- **Check and review the current head.** Record the PR's head SHA with
  `gh pr view <number> -R elsehow/airo --json headRefOid -q .headRefOid`.
  Wait for CI with `gh pr checks <number> -R elsehow/airo --watch`, and
  verify that the `test` check actually succeeded for that head: missing,
  skipped, cancelled, pending or failing is not a pass. Have a separate
  reviewer agent on this dev VM review the diff for that same head; resolve
  its findings before merging. Keep the review inside this cell, not with
  the Thinker. If you push any changes, repeat CI and review for the new head.
- **Squash only after both pass.** Run
  `gh pr merge <number> -R elsehow/airo --squash --match-head-commit <sha>`
  using the head that passed CI and review. Verify the PR is merged, then
  report its URL and run `~/.box/needs-you done "Merged elsehow/airo#<number>"`.
  The user still closes the session with `kuggis done`.
- **Never bypass a failure.** Never merge a failing PR, use `--admin`, weaken
  checks or protections to get a merge through, or seek broader credentials.
  Fix failures and repeat CI and review. If you cannot proceed (including a
  missing check, unavailable reviewer or refused merge), leave the PR open
  and run `~/.box/needs-you blocked "<what is stuck and what you need>"`
  before ending the turn. Waiting for running CI alone is not a blocker.
- **Not on this machine:** the Graph 4 simulator harness (forecastbench-sim)
  and the archived private repo.
