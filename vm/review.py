#!/usr/bin/env python3
"""Bounded review verdicts, also embedded in the trusted GitHub workflow.

The VM app can write comments but only read statuses. Actions publishes the
status without checking out or running PR code and without another credential.
"""
import json
import os
import re
import urllib.request
import uuid

BOT = 'exe-dev-github-integration[bot]'
MARKER = re.compile(r'kuggis-cell-review/v1 ([0-9a-f]{40}) ([0-9a-f-]{36}) (pass|fail)\Z')


def latest(api, number, head):
    verdicts = []
    for page in range(1, 11):
        comments = api(f'issues/{number}/comments?per_page=100&page={page}')
        for comment in comments:
            match = MARKER.fullmatch(comment.get('body') or '')
            if comment['user']['login'] != BOT or not match or match[1] != head:
                continue
            try:
                if str(uuid.UUID(match[2])) != match[2]:
                    continue
            except ValueError:
                continue
            verdicts.append({'id': comment['id'], 'reviewer': match[2], 'verdict': match[3]})
        if len(comments) < 100:
            return max(verdicts, key=lambda v: v['id']) if verdicts else None
    raise ValueError('too many comments to verify the latest review')


def description(verdict):
    return f"Independent job {verdict['reviewer']} comment {verdict['id']}"


def publish(event, repo, branch, api):
    issue = event.get('issue', {})
    if not issue.get('pull_request') or event.get('comment', {}).get('user', {}).get('login') != BOT:
        return
    number = issue['number']
    if type(number) is not int or number < 1:
        raise ValueError('invalid PR number')
    pr = api(f'pulls/{number}')
    if (pr['state'] != 'open' or pr['base']['ref'] != branch or
            pr['base']['repo']['full_name'].lower() != repo.lower() or
            (pr['head']['repo'] or {}).get('full_name', '').lower() != repo.lower()):
        return
    head = pr['head']['sha']
    verdict = latest(api, number, head)
    if verdict:
        api('statuses/' + head, {'state': 'success' if verdict['verdict'] == 'pass' else 'failure',
            'context': 'cell-review', 'description': description(verdict)})
    else:
        api('statuses/' + head, {'state': 'failure', 'context': 'cell-review',
                               'description': 'No current exact-head review'})


if __name__ == '__main__':
    repo = os.environ['GITHUB_REPOSITORY']

    def api(path, body=None):
        request = urllib.request.Request('https://api.github.com/repos/' + repo + '/' + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                     'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    with open(os.environ['GITHUB_EVENT_PATH']) as f:
        publish(json.load(f), repo, os.environ['CELL_BRANCH'], api)
