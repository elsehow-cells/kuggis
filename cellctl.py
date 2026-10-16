#!/usr/bin/env python3
"""CLI entry point; no model execution. Writes require an exact reviewed plan hash."""
import argparse
import json
import os
from pathlib import Path
import sys
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cells import adoption, control, policy


def configured(config, cell):
    if not policy.NAME.fullmatch(cell):
        raise ValueError('invalid cell name')
    path = config/'cells'/(cell + '.json')
    if not path.exists():
        raise ValueError(f'{cell} has no contract; start with kuggis onboard --policy <file>')
    return policy.load(path)


def for_project(config, name):
    matches = []
    for path in (config/'cells').glob('*.json'):
        raw = json.loads(path.read_text())
        if raw.get('version') == 2:
            value = policy.validate(raw)
            for p in value['projects']:
                if p['name'] == name:
                    matches.append((value, p))
    if len(matches) > 1:
        raise ValueError('project belongs to multiple contracts')
    return matches[0] if matches else (None, None)


def summary(observation):
    for name, row in observation.items():
        print(name + ': ' + ('development verified; isolation not certified' if row['ready'] else 'setup incomplete'))
        for issue in row['issues']:
            print('  - ' + issue)
        if row.get('actions'):
            print('  Planned: ' + ', '.join(row['actions']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='operation', required=True)
    for name in ('onboard', 'reconcile', 'audit'):
        cmd = subs.add_parser(name)
        cmd.add_argument('cell', nargs='?')
        cmd.add_argument('--policy', type=Path)
        cmd.add_argument('--json', action='store_true')
        if name != 'audit':
            cmd.add_argument('--apply', metavar='PLAN_SHA256')
    cmd = subs.add_parser('adopt')
    cmd.add_argument('path', type=Path)
    cmd.add_argument('--cell', required=True)
    cmd.add_argument('--project')
    cmd.add_argument('--session')
    cmd.add_argument('--agent', default='pi', choices=['claude', 'codex', 'pi'])
    cmd.add_argument('--include', action='append', default=[])
    cmd.add_argument('--brief')
    cmd.add_argument('--json', action='store_true')
    cmd.add_argument('--apply', metavar='PLAN_SHA256')
    for name in ('guard', 'export'):
        cmd = subs.add_parser(name)
        cmd.add_argument('project')
        if name == 'guard':
            cmd.add_argument('session')
        else:
            cmd.add_argument('kind', choices=['contract', 'instructions'])
    args = parser.parse_args()
    config = Path(os.environ.get('KUGGIS_CONFIG', str(Path.home()/'.config/kuggis')))
    services = control.Services()
    if args.operation in ('guard', 'export'):
        cell, project = for_project(config, args.project)
        if not cell:
            return 0 # legacy routing remains available, visibly unverified
        control.check_ownership(config, cell)
        if args.operation == 'export':
            print(json.dumps(policy.contract(cell, project)) if args.kind == 'contract' else
                  policy.instructions(cell, project), end='\n' if args.kind == 'contract' else '')
            return 0
        if not adoption.SESSION.fullmatch(args.session):
            raise ValueError('invalid session name')
        # Existing sessions remain accessible for recovery even when configuration drifts.
        live = services.ssh(project['vm'], 'import json,subprocess\nprint(json.dumps(subprocess.run(["tmux","has-session","-t",' + repr('=' + args.session) + '],capture_output=True).returncode == 0))\n')
        if live is True:
            return 0
        rows = control.audit(cell, config, services)
        if not rows[project['name']]['ready']:
            raise ValueError('setup incomplete; run kuggis reconcile ' + cell['cell'] + ': ' + '; '.join(rows[project['name']]['issues']))
        return 0
    if args.operation == 'adopt':
        cell = configured(config, args.cell)
        manifest, blobs, project = adoption.prepare(args.path, cell, args.project, args.session,
                                                    args.agent, args.include, args.brief)
        if not args.apply:
            if args.json:
                print(json.dumps(manifest, indent=2))
                return 0
            print(f"Adopt {manifest['session']} into {cell['cell']} / {project['name']} on {project['vm']}.")
            print(f"Development repo: {project['repo']}; upstream {project['upstream']} remains owner-controlled.")
            print(f"{len(manifest['commits'])} commits: {manifest['base']} → {manifest['head']}")
            print('Changed code: ' + ', '.join(manifest['changed_files']))
            for name, file in manifest['files'].items():
                print(f"Transfer {name} ({file['bytes']} bytes, SHA256 {file['sha256']})")
            print('Untracked files are excluded unless explicitly listed for transfer above.')
            print('Review the selected code and file contents before moving them into this public development cell.')
            print('Nothing uploaded or started. Repeat with --apply ' + manifest['approval'])
            return 0
        result = adoption.apply(manifest, blobs, project, cell, config, services, args.apply)
        print(json.dumps(result, indent=2))
        print(f"Resume: kuggis {cell['cell']} {manifest['session']} --project {project['name']} --agent {args.agent}")
        return 0
    cell = policy.load(args.policy) if args.policy else configured(config, args.cell or '')
    if args.cell and cell['cell'] != args.cell:
        raise ValueError('policy file names a different cell')
    if args.operation == 'audit':
        observation = control.audit(cell, config, services)
        if args.json:
            print(json.dumps(observation, indent=2))
        else:
            summary(observation)
        return 0 if all(row['ready'] for row in observation.values()) else 1
    if args.apply:
        result = control.apply(cell, config, services, args.apply)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            summary(result['projects'])
            for url in result['pull_requests']:
                print('Review and merge CI prerequisite: ' + url)
        return 0 if all(row['ready'] for row in result['projects'].values()) else 1
    plan = control.plan(cell, config, services)
    if args.json:
        print(json.dumps(plan, indent=2))
        return 0
    print(cell['cell'] + ': agents squash-merge after cell-test and independent cell-review; no human PR approval.')
    print('Upstream, publication, submissions, private data and paid experiments still require the owner.')
    for p in cell['projects']:
        print(f"{p['name']}: {p['repo']} on {p['vm']}; upstream {p['upstream']} stays separate")
        print('  Offline tests: ' + p['test'])
    summary(plan['projects'])
    print('Use --json to inspect exact workflow, instruction, and observed configuration details.')
    print('No changes applied. Applying may create VMs/forks, change GitHub settings, and deploy adapters.')
    print('Repeat this command with --apply ' + plan['approval'])
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        sys.exit('kuggis: ' + str(exc))
