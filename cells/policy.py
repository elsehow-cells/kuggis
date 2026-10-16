"""Development-cell contracts. These verify merge readiness, not OS isolation."""
import hashlib
import json
from pathlib import Path
import re
import time
import textwrap

NAME = re.compile(r"[a-z][a-z0-9-]{0,62}\Z")
REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
RESERVED = {'operator', 'unassigned', 'home', 'ls', 'cells', 'cell', 'prs', 'web',
            'dispatch', 'think', 'new', 'sync', 'sh', 'put', 'done', 'token', 'help',
            'onboard', 'reconcile', 'audit', 'adopt'}
CHECKS = ['cell-test', 'cell-review']
TTL = 900


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate(data):
    if not isinstance(data, dict) or set(data) != {'version', 'cell', 'merge', 'spending', 'projects', 'doors'}:
        raise ValueError('expected a version 2 cell contract (version, cell, merge, spending, projects, doors)')
    if data['version'] != 2 or type(data['version']) is not int:
        raise ValueError('unsupported cell contract version')
    if not isinstance(data['cell'], str) or not NAME.fullmatch(data['cell']) or data['cell'] in RESERVED:
        raise ValueError('invalid cell name')
    if not isinstance(data['merge'], dict) or type(data['merge'].get('human_approvals')) is not int:
        raise ValueError('merge human_approvals must be the integer zero')
    if data['merge'] != {'strategy': 'squash', 'checks': CHECKS, 'human_approvals': 0}:
        raise ValueError('development cells require squash, cell-test + cell-review, and zero human approvals')
    if data['spending'] != 'ask':
        raise ValueError('only spending=ask is supported until enforceable budgets are implemented')
    if not isinstance(data['projects'], list) or not data['projects']:
        raise ValueError('a cell needs at least one project')
    names, repos, vms = set(), set(), set()
    for p in data['projects']:
        if not isinstance(p, dict) or set(p) != {'name', 'repo', 'upstream', 'vm', 'profile', 'branch', 'test'}:
            raise ValueError('project needs name, repo, upstream, vm, profile, branch, test')
        if any(not isinstance(p[k], str) for k in p):
            raise ValueError('project fields must be strings')
        for k in ('name', 'vm'):
            if not NAME.fullmatch(p[k]) or p[k] in RESERVED or p[k] == 'kuggis':
                raise ValueError(f'invalid project {k}')
        if p['name'] in names or p['repo'].lower() in repos or p['vm'] in vms:
            raise ValueError('project names, repositories and VMs must be unique within a cell')
        names.add(p['name']); repos.add(p['repo'].lower()); vms.add(p['vm'])
        if not REPO.fullmatch(p['repo']) or not REPO.fullmatch(p['upstream']) or p['repo'].lower() == p['upstream'].lower():
            raise ValueError('name distinct development and upstream GitHub repositories explicitly')
        if not NAME.fullmatch(p['branch']) or (p['profile'] != '-' and not NAME.fullmatch(p['profile'])):
            raise ValueError('invalid branch or profile')
        if not p['test'].strip() or len(p['test']) > 2000 or '\x00' in p['test']:
            raise ValueError('provide an explicit offline CI setup/test command')
    if data['doors'] != {'upstream': 'yours', 'publish': 'yours', 'submission': 'yours', 'private_data': 'yours'}:
        raise ValueError('this version requires owner approval for upstream, publication, submissions and private data')
    return data


def load(path):
    return validate(json.loads(Path(path).read_text()))


def instructions(policy, project):
    return f'''## Cell contract: {policy['cell']}

This block overrides generic finishing instructions and project merge instructions.
Development repository: {project['repo']}. Base branch: {project['branch']}.
Upstream {project['upstream']} is outside this development boundary.

- Work only in your job's worktree. Never publish private data in this public cell.
- Ask the owner before paid model/search experiments, deployments, publications,
  upstream PRs or submissions. An internal merge does not authorize any of these.
- Run the project's offline tests: `{project['test']}`.
- Open PRs explicitly against {project['repo']}, never the upstream repository.
- Have a separate agent session on this VM review the current PR head. Give it
  the PR number and exact head SHA. It must inspect the diff, resolve findings,
  and record its verdict with `~/.box/pr-gate.py review PR HEAD pass|fail`.
  The author session cannot record its own review. Never manufacture a pass.
- Merge through `~/.box/pr-gate.py merge PR HEAD`. It requires successful cell-test
  and cell-review checks and a separate review of that exact head, then squash
  merges with --match-head-commit. Changed heads require new tests and review.
- Fix failing tests or reviews. Never bypass checks, use --admin, change protection,
  or seek credentials. If blocked, run `~/.box/needs-you blocked "what is needed"`.
- After verifying merge, report the PR URL and run `~/.box/needs-you done "merged"`.
  The owner closes the job with kuggis done.

These are development rules, not a claim of OS/network isolation. Publication,
submission and private-data doors are owner-operated; automated carriers are not
installed by this contract. Do not attempt those crossings from this VM.
'''


def contract(policy, project):
    return {'version': 1, 'cell': policy['cell'], 'policy_hash': digest(policy),
            'project': project['name'], 'repo': project['repo'], 'branch': project['branch'],
            'checks': CHECKS, 'instructions_hash': hashlib.sha256(instructions(policy, project).encode()).hexdigest()}


def workflow(project):
    # Known action releases, pinned rather than taking mutable tags at runtime.
    return '''# Managed by kuggis's development-cell contract. Changes are reviewed in a PR.
name: cell-tests
on:
  pull_request:
  push:
    branches: [%s]
permissions:
  contents: read
jobs:
  cell-test:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803
        with:
          persist-credentials: false
      - uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1
        with:
          python-version: "3.12"
      - uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020
        with:
          node-version: "22"
      - name: Offline tests
        run: %s
''' % (json.dumps(project['branch']), json.dumps(project['test']))


def review_workflow(project):
    script = (Path(__file__).resolve().parents[1]/'vm/review.py').read_text()
    return '''# Managed by kuggis. Runs trusted default-branch code; never checks out a PR.
name: cell-review-verdict
on:
  issue_comment:
    types: [created, edited, deleted]
permissions:
  issues: read
  pull-requests: read
  statuses: write
concurrency:
  group: cell-review-${{ github.event.issue.number }}
  cancel-in-progress: false
jobs:
  record-review:
    if: github.event.issue.pull_request && github.event.comment.user.login == 'exe-dev-github-integration[bot]'
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - name: Record the latest exact-head verdict
        env:
          GH_TOKEN: ${{ github.token }}
          CELL_BRANCH: %s
        run: |
          python3 - <<'PY'
%s          PY
''' % (json.dumps(project['branch']), textwrap.indent(script, '          '))


def cached(config, policy, project, now=None):
    """Only fresh observations of this exact policy + runtime installation count."""
    now = time.time() if now is None else now
    path = Path(config) / 'readiness' / (policy['cell'] + '.json')
    try:
        report = json.loads(path.read_text())
        if report['policy_hash'] != digest(policy):
            return 'setup incomplete: policy changed'
        if not 0 <= now - report['checked_at'] <= TTL:
            return 'verification expired; run audit'
        from .control import expected_hashes
        if report.get('runtime_hashes') != expected_hashes():
            return 'verification expired; installed kuggis changed'
        row = report['projects'][project]
        if not row['ready']:
            return 'setup incomplete: ' + '; '.join(row['issues'])
        return 'development verified (isolation not certified)'
    except (OSError, ValueError, KeyError, TypeError):
        return 'setup incomplete: not verified'
