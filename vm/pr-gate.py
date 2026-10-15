#!/usr/bin/env python3
"""In-cell quality gate. GitHub and cell credentials carry the security boundary."""
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review


def run(args, body=None):
    p = subprocess.run(args, input=json.dumps(body) if body is not None else None,
                       text=True, capture_output=True, check=True)
    return p.stdout


def api(repo, path, body=None):
    args = ['gh', 'api', f'repos/{repo}/{path}']
    if body is not None:
        args += ['--method', 'POST', '--input', '-']
    return json.loads(run(args, body))


def execute(action, number, head, verdict=None):
    box = Path.home() / '.box'
    c = json.loads((box/'cell-contract.json').read_text())
    repo = c['repo']
    pr = api(repo, 'pulls/' + str(number))
    if (pr['state'] != 'open' or pr['head']['sha'] != head or pr['base']['ref'] != c['branch']
            or pr['base']['repo']['full_name'].lower() != repo.lower()
            or pr['head']['repo']['full_name'].lower() != repo.lower()):
        raise ValueError('PR must be open, internal to the development repo, and at the reviewed head')
    name = os.environ.get('BOX_SESSION', '')
    sid = os.environ.get('BOX_SESSION_ID', '')
    if not name or not sid:
        raise ValueError('restart in a managed kuggis session before recording reviews or merging')
    identity = json.loads((box/'ids'/name).read_text())
    if identity['session_id'] != sid or identity['run_id'] != os.environ.get('BOX_RUN_ID'):
        raise ValueError('stale session identity')
    if action == 'review':
        if verdict not in ('pass', 'fail'):
            raise ValueError('verdict must be pass or fail')
        # A distinct managed reviewer job, not merely a different shell process.
        if name == pr['head']['ref']:
            raise ValueError('the author job cannot review its own PR')
        author_file = box/'ids'/pr['head']['ref']
        if author_file.exists() and json.loads(author_file.read_text())['session_id'] == sid:
            raise ValueError('the reviewer must be a different job')
        # Only bounded identifiers are posted; never raw diffs or review text.
        api(repo, 'issues/' + str(number) + '/comments',
            {'body': f'kuggis-cell-review/v1 {head} {sid} {verdict}'})
        print('Recorded ' + verdict + ' for ' + head + '; wait for the cell-review status workflow')
        return
    if action != 'merge':
        raise ValueError('unknown gate operation')
    # Branch-protection inspection requires administration permissions, which
    # the VM deliberately lacks. The operator audits it before job launch;
    # GitHub enforces it at merge time. Never copy operator credentials here.
    # gh aggregates check runs and commit statuses; every required check must
    # exist and actually pass. Neutral, skipped, pending and absent are not pass.
    checks = json.loads(run(['gh', 'pr', 'checks', str(number), '-R', repo, '--json', 'name,state']))
    for required in c['checks']:
        found = [x for x in checks if x['name'] == required]
        if not found or any(x['state'].upper() != 'SUCCESS' for x in found):
            raise ValueError(required + ' has not succeeded')
    statuses = api(repo, 'commits/' + head + '/statuses?per_page=100')
    status = next((x for x in statuses if x['context'] == 'cell-review'), None)
    verdict = review.latest(lambda path: api(repo, path), number, head)
    if (not status or status['state'] != 'success' or not verdict or verdict['verdict'] != 'pass'
            or status.get('description') != review.description(verdict)):
        raise ValueError('no independent review for this head')
    if verdict['reviewer'] == sid:
        raise ValueError('the author cannot supply its own review')
    # GitHub refuses a changed head and re-evaluates required checks atomically.
    run(['gh', 'pr', 'merge', str(number), '-R', repo, '--squash', '--match-head-commit', head])
    merged = api(repo, 'pulls/' + str(number))
    if not merged.get('merged'):
        raise ValueError('merge was not confirmed')
    print(merged['html_url'])


if __name__ == '__main__':
    try:
        action, number, head, *rest = sys.argv[1:]
        if not number.isdecimal() or len(head) != 40 or any(c not in '0123456789abcdef' for c in head):
            raise ValueError('expected PR number and full head SHA')
        execute(action, int(number), head, rest[0] if len(rest) == 1 else None)
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as exc:
        sys.exit('cell gate: ' + str(exc))
