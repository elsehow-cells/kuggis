"""Explicit, content-addressed laptop -> development-cell job handoff."""
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import tempfile

from .control import Failure, run, audit
from .policy import digest

SESSION = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z')


def github_slug(url):
    for prefix in ('git@github.com:', 'https://github.com/', 'https://github.int.exe.xyz/'):
        if url.startswith(prefix):
            return url[len(prefix):].removesuffix('.git').lower()
    return None


def prepare(path, policy, project=None, session=None, agent='pi', includes=(), brief=None):
    source = Path(path).resolve()
    top = Path(run(['git', 'rev-parse', '--show-toplevel'], cwd=source).strip()).resolve()
    if source != top:
        raise Failure('adopt the worktree root, not a subdirectory')
    origin = github_slug(run(['git', 'remote', 'get-url', 'origin'], cwd=source).strip())
    matches = [p for p in policy['projects'] if origin in (p['repo'].lower(), p['upstream'].lower())
               and (project is None or p['name'] == project)]
    if len(matches) != 1:
        raise Failure('source remote must match exactly one declared project or upstream; choose --project')
    p = matches[0]
    branch = run(['git', 'symbolic-ref', '--short', 'HEAD'], cwd=source).strip()
    name = session or branch
    if not SESSION.fullmatch(name) or name == p['branch']:
        raise Failure('choose a job/session name distinct from the default branch')
    if agent not in {'claude', 'codex', 'pi'}:
        raise Failure('unknown agent runtime')
    if run(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=source).strip():
        raise Failure('commit or separately preserve tracked changes before adoption; no automatic stash/commit')
    head = run(['git', 'rev-parse', 'HEAD'], cwd=source).strip()
    base = run(['git', 'merge-base', 'HEAD', 'refs/remotes/origin/' + p['branch']], cwd=source).strip()
    if head == base:
        raise Failure('no job commits beyond the local origin/default-branch base')
    commits = run(['git', 'rev-list', '--reverse', f'{base}..{head}'], cwd=source).splitlines()
    files = run(['git', 'diff', '--name-only', base, head], cwd=source).splitlines()
    # Only selected commits; the rest of the source repository history stays local.
    with tempfile.TemporaryDirectory() as d:
        bundle = Path(d)/'job.bundle'
        run(['git', 'bundle', 'create', bundle, 'HEAD', '^' + base], cwd=source)
        bundle_bytes = bundle.read_bytes()
    blobs = {'job.bundle': bundle_bytes}
    seen = set()
    for value in [*includes, *([brief] if brief else [])]:
        file = Path(value)
        file = file if file.is_absolute() else source/file
        relative = file.relative_to(source)  # cannot smuggle files from outside the worktree
        if '..' in relative.parts or '.git' in relative.parts or file.is_symlink():
            raise Failure('only explicit regular worktree files may be included')
        if any(parent.is_symlink() for parent in [file, *file.parents] if parent != source and source in parent.parents):
            raise Failure('symlinked artifact paths are not supported')
        if not file.is_file() or file.stat().st_size > 20 * 1024 * 1024:
            raise Failure('each selected artifact must be a regular file under 20 MiB')
        if str(relative) in seen:
            continue
        seen.add(str(relative))
        blobs['artifacts/' + relative.as_posix()] = file.read_bytes()
    brief_path = 'artifacts/' + str(Path(brief).relative_to(source) if Path(brief).is_absolute() else Path(brief)) if brief else None
    manifest = {'version': 1, 'operation': 'adopt', 'cell': policy['cell'], 'policy_hash': digest(policy),
                'project': p['name'], 'repo': p['repo'], 'upstream': p['upstream'], 'vm': p['vm'],
                'session': name, 'agent': agent, 'base': base, 'head': head, 'commits': commits,
                'changed_files': files, 'brief': brief_path,
                'files': {name: {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)} for name, data in sorted(blobs.items())},
                'excluded_untracked_count': len(set(run(['git', 'ls-files', '--others', '--exclude-standard'], cwd=source).splitlines()) - seen)}
    manifest['approval'] = digest(manifest)
    return manifest, blobs, p


def archive(manifest, blobs):
    output = io.BytesIO()
    payload = dict(blobs, **{'manifest.json': json.dumps(manifest, sort_keys=True).encode()})
    with tarfile.open(fileobj=output, mode='w') as tar:
        for name, data in sorted(payload.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data); info.mode = 0o600; info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    if output.tell() > 100 * 1024 * 1024:
        raise Failure('handoff exceeds 100 MiB; select fewer artifacts')
    return output.getvalue()


def apply(manifest, blobs, p, policy, config, services, approval):
    if manifest['approval'] != approval:
        raise Failure('commits/files or destination changed; inspect and approve the new handoff')
    observed = audit(policy, config, services)
    if not observed[p['name']]['ready']:
        raise Failure('destination setup incomplete: ' + '; '.join(observed[p['name']]['issues']))
    import subprocess
    proc = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                           p['vm'] + '.exe.xyz', 'python3 -I ~/.box/adopt-job.py'],
                          input=archive(manifest, blobs), capture_output=True, timeout=180)
    if proc.returncode:
        raise Failure('remote adoption refused: ' + proc.stderr.decode(errors='replace')[:800])
    return json.loads(proc.stdout)
