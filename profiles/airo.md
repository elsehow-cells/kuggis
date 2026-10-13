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
  dashboard run on another machine you can't reach. Deploys are a `git pull`
  there after a merge, which the user does.
- **Public repo.** The repo is public: no personal information in commits, and
  experiment write-ups stay out of it. If you can't open a PR against
  forecastingresearch/airo from here, push the branch to the fork (`origin`)
  and tell the user.
- **Not on this machine:** the Graph 4 simulator harness (forecastbench-sim)
  and the archived private repo.
