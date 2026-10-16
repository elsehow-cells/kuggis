#!/usr/bin/env python3
"""Import an approved, bounded job package without executing repository code."""
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile
import tempfile

# -I intentionally disables cwd imports; load our installed sibling explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import events


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True, stderr=subprocess.PIPE).strip()


def unpack(data):
    if len(data) > 100 * 1024 * 1024:
        raise ValueError('package too large')
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as tar:
        for member in tar:
            path = PurePosixPath(member.name)
            if (not member.isfile() or path.is_absolute() or '..' in path.parts or member.name in files
                    or str(path) != member.name
                    or not (member.name in ('manifest.json', 'job.bundle') or
                            (len(path.parts) > 1 and path.parts[0] == 'artifacts'))
                    or member.size > 100 * 1024 * 1024 or len(files) >= 1000):
                raise ValueError('invalid archive member')
            files[member.name] = tar.extractfile(member).read()
    manifest = json.loads(files.pop('manifest.json'))
    approval = manifest.pop('approval')
    calculated = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    manifest['approval'] = approval
    if (calculated != approval or set(files) != set(manifest['files']) or 'job.bundle' not in files
            or manifest.get('version') != 1 or manifest.get('operation') != 'adopt'):
        raise ValueError('manifest mismatch')
    for name, content in files.items():
        if manifest['files'][name] != {'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)}:
            raise ValueError('artifact changed')
    return manifest, files


def adopt(home, data):
    manifest, files = unpack(data)
    box = home/'.box'
    c = json.loads((box/'cell-contract.json').read_text())
    for key in ('cell', 'project', 'repo', 'policy_hash'):
        if manifest[key] != c[key]:
            raise ValueError('destination contract changed')
    name, head, base = manifest['session'], manifest['head'], manifest['base']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', name) or name == c['branch']:
        raise ValueError('invalid job name')
    if not all(re.fullmatch('[0-9a-f]{40}', sha) for sha in (head, base)) or manifest['agent'] not in events.AGENTS:
        raise ValueError('invalid head/base/runtime')
    if manifest.get('brief') and (manifest['brief'] not in files or not manifest['brief'].startswith('artifacts/')):
        raise ValueError('brief is absent')
    repo = home/c['repo'].split('/')[1]
    if git(repo, 'remote', 'get-url', 'origin') != 'https://github.int.exe.xyz/' + c['repo'] + '.git':
        raise ValueError('repository origin differs from contract')
    (box/'jobs').mkdir(exist_ok=True)
    with (box/'adopt.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        dest = box/'jobs'/manifest['approval']
        if (dest/'receipt.json').exists():
            return json.loads((dest/'receipt.json').read_text())
        # Never overwrite an existing session/worktree or unrelated branch.
        exists = subprocess.run(['tmux', 'has-session', '-t', '=' + name], capture_output=True).returncode == 0
        if exists or (repo/'.claude/worktrees'/name).exists() or ((box/'state'/name).exists() and not (dest/'pending.json').exists()):
            raise ValueError('job already exists; choose a new session name')
        git(repo, 'fetch', '--quiet', 'origin', c['branch'])
        if git(repo, 'merge-base', base, 'origin/' + c['branch']) != base:
            raise ValueError('bundle base is not in the destination default-branch history')
        with tempfile.TemporaryDirectory(dir=box) as temp:
            bundle = Path(temp)/'job.bundle'; bundle.write_bytes(files['job.bundle'])
            git(repo, 'bundle', 'verify', str(bundle))
            listed = git(repo, 'bundle', 'list-heads', str(bundle)).splitlines()
            if listed != [head + ' HEAD']:
                raise ValueError('bundle exports a different head')
            ref = 'refs/kuggis/imports/' + manifest['approval']
            git(repo, 'fetch', '--quiet', '--no-tags', str(bundle), 'HEAD:' + ref)
            try:
                existing = git(repo, 'rev-parse', '--verify', 'refs/heads/' + name)
            except subprocess.CalledProcessError:
                existing = None
            if existing and existing != head:
                raise ValueError('branch already exists at another head')
            if not existing:
                git(repo, 'branch', name, head)
        dest.mkdir(exist_ok=True)
        events.atomic(dest/'pending.json', json.dumps(manifest))
        for path, content in files.items():
            if path == 'job.bundle':
                continue
            target = dest/path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        handoff = dest/'handoff.md'
        handoff.write_text(f"Imported job {name} at {head}. Existing work is preserved; do not repeat completed experiments.\n" +
                           (f"Read the owner's selected brief: {dest/manifest['brief']}\n" if manifest.get('brief') else
                            'Ask the owner what remains to do before running experiments.\n'))
        if (box/'ids'/name).exists():
            event = json.loads((box/'ids'/name).read_text())
        else:
            event = events.emit(box, name, manifest['agent'], 'starting')
        events.emit(box, name, manifest['agent'], 'stopped')
        (box/'first').mkdir(exist_ok=True)
        (box/'first'/name).write_text(f"Read {handoff}. Continue this imported job under the cell contract.")
        receipt = {'session': name, 'session_id': event['session_id'], 'head': head,
                   'approval': manifest['approval'], 'started': False}
        (dest/'manifest.json').write_text(json.dumps(manifest))
        events.atomic(dest/'receipt.json', json.dumps(receipt))
        (dest/'pending.json').unlink(missing_ok=True)
        return receipt


if __name__ == '__main__':
    try:
        print(json.dumps(adopt(Path.home(), sys.stdin.buffer.read(100 * 1024 * 1024 + 1))))
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        sys.exit('adopt: ' + str(exc))
