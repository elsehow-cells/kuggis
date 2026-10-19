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
- **Merging.** The "Cell contract" block below is the merge path: push your
  branch to the fork (`origin`), open the PR with
  `gh pr create -R elsehow/airo --base main --head <branch>`, have a separate
  session on this VM record the review with `~/.box/pr-gate.py review`, and
  merge with `~/.box/pr-gate.py merge` once `cell-test` and `cell-review` pass
  for that exact head. Keep the review inside this cell, not with the
  Thinker. Never open or merge a PR on `forecastingresearch/airo`.
- **Not on this machine:** the Graph 4 simulator harness (forecastbench-sim)
  and the archived private repo.
