#!/usr/bin/env python3
"""One bounded live check of devcloud TeamComms authentication and streaming.

Uses the dedicated host login file. Creates an AI token for native acceptance
in a private output file and a temporary human token, revoked during the check.
Session and message records remain as labeled acceptance evidence.
"""

import argparse
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import time
import uuid

import httpx


class Form(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.csrf = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input' and attrs.get('name') == 'csrfmiddlewaretoken':
            self.csrf = attrs.get('value')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def login(client, base, credential_file):
    values = {}
    for line in credential_file.read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.removeprefix('export ').split('=', 1)
            values[key.strip()] = value.strip().strip('\"\'')
    url = base + '/accounts/login/'
    page = client.get(url)
    page.raise_for_status()
    csrf = Form(page.text).csrf
    require(csrf, 'Login form has no CSRF token')
    response = client.post(url, data={
        'username': values['SWF_REMOTE_CLAUDE_USER'],
        'password': values['SWF_REMOTE_CLAUDE_PASSWORD'],
        'csrfmiddlewaretoken': csrf,
    }, headers={'Referer': url})
    response.raise_for_status()
    page = client.get(base + '/account/tokens/')
    require(page.status_code == 200 and '/accounts/login/' not in str(page.url)
            and 'name="label"' in page.text, 'Login did not reach the account tokens page')
    return page


def issue(client, url, *, ai, service_kind=''):
    page = client.get(url)
    csrf = Form(page.text).csrf
    require(csrf, 'Tokens form has no CSRF token')
    data = {'label': ('TeamComms ' + service_kind if service_kind else
                      'TeamComms live acceptance ' + ('AI' if ai else 'human')),
            'csrfmiddlewaretoken': csrf}
    if ai:
        data['teamcomms_ai'] = 'on'
    if service_kind:
        data['teamcomms_service_kind'] = service_kind
    page = client.post(url, data=data, headers={'Referer': url})
    page.raise_for_status()
    found = re.search(r'swfr_[A-Za-z0-9_-]{43}', page.text)
    require(found is not None, 'Token issuance did not return a token')
    raw = found.group(0)
    prefix = raw[5:13]
    row = next((s for s in re.findall(r'<tr\b[^>]*>.*?</tr>', page.text, re.S)
                if 'swfr_' + prefix in s), '')
    token_id = re.search(r'name="revoke" value="(\d+)"', row)
    require(token_id is not None, 'Issued token row has no revocation control')
    return raw, token_id.group(1)


def events(response):
    current = {}
    for line in response.iter_lines():
        if not line:
            if current:
                yield current
            current = {}
        elif line.startswith('event: '):
            current['event'] = line[7:]
        elif line.startswith('data: '):
            current['data'] = json.loads(line[6:])
        elif line.startswith('id: '):
            current['id'] = line[4:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='https://epic-devcloud.org/prod')
    parser.add_argument('--credentials', type=Path, default=Path('/home/admin/.swf-remote-claude-ec2dev.env'))
    parser.add_argument('--ai-token-file', type=Path, required=True)
    args = parser.parse_args()
    require(not args.ai_token_file.exists(), 'AI token output file already exists')
    base = args.base.rstrip('/')
    tc = base + '/teamcomms'
    with httpx.Client(timeout=35, follow_redirects=True) as browser, httpx.Client(timeout=35) as machine:
        login(browser, base, args.credentials)
        response = browser.get(tc + '/api/whoami')
        require(response.status_code == 200, f'Browser identity HTTP {response.status_code}')
        human = response.json()
        require(machine.get(tc + '/api/whoami').status_code == 401, 'Anonymous request was not rejected')
        refused = browser.post(tc + '/api/comms/sessions', json={})
        require(refused.status_code == 403, 'Cookie mutation without CSRF was not rejected')
        print('PASS browser identity, anonymous denial, cookie CSRF denial', flush=True)
        tokens_url = base + '/account/tokens/'
        human_token, revoke_id = issue(browser, tokens_url, ai=False)
        ai_token, _ = issue(browser, tokens_url, ai=True)
        args.ai_token_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(args.ai_token_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as output:
            output.write(ai_token + '\n')
        machine.headers['Authorization'] = 'Bearer ' + human_token
        response = machine.get(tc + '/api/whoami')
        require(response.status_code == 200 and response.json() == human, 'Human token identity differs from browser')
        ai_response = machine.get(tc + '/api/whoami', headers={'Authorization': 'Bearer ' + ai_token})
        require(ai_response.status_code == 200, f'AI identity HTTP {ai_response.status_code}')
        ai = ai_response.json()
        require(ai['kind'] == 'ai' and ai['operator_id'] == human['participant_id'],
                'AI identity was not bound to its human operator')
        print('PASS human token and bound AI identity; AI token saved privately', flush=True)
        run = str(uuid.uuid4())
        response = machine.post(tc + '/api/comms/sessions', json={
            'native_id': run, 'client': 'program', 'host': 'ec2dev',
            'name': 'TeamComms public integration acceptance',
        })
        require(response.status_code == 200, f'Session registration HTTP {response.status_code}: {response.text}')
        session = response.json()['session_id']
        message_id = str(uuid.uuid4())
        sent = machine.post(tc + '/api/comms/messages', json={
            'message_id': message_id, 'content': 'TeamComms public proxy acceptance',
            'audience': {'session_ids': [session]},
        })
        require(sent.status_code == 200, f'Message publication HTTP {sent.status_code}')
        with machine.stream('GET', tc + '/api/comms/stream', params={'session_id': session}) as response:
            require(response.status_code == 200, f'Stream HTTP {response.status_code}')
            for event in events(response):
                if event.get('event') == 'message':
                    cursor = event['id']
                    break
            else:
                raise RuntimeError('Published message did not arrive on stream')
        print('PASS public message publication and immediate stream delivery', flush=True)
        started = time.monotonic()
        with machine.stream('GET', tc + '/api/comms/stream', params={'session_id': session},
                            headers={'Last-Event-ID': cursor}) as response:
            require(response.status_code == 200, f'Reconnect HTTP {response.status_code}')
            stream = events(response)
            first = next(stream)
            require(first.get('event') == 'ready' and str(first['data']['after']) == cursor,
                    'Last-Event-ID cursor was not preserved')
            page = browser.get(tokens_url)
            revoke = browser.post(tokens_url, data={
                'revoke': revoke_id, 'csrfmiddlewaretoken': Form(page.text).csrf,
            }, headers={'Referer': tokens_url})
            revoke.raise_for_status()
            for event in stream:
                require(event.get('event') != 'message', 'Reconnect replayed acknowledged cursor')
                if event.get('event') == 'error':
                    require(event['data'].get('status') == 401, 'Revocation returned wrong stream error')
                    break
            else:
                raise RuntimeError('Revoked stream remained open')
        require(machine.get(tc + '/api/whoami').status_code == 401, 'Revoked token remains usable')
        print(f'PASS reconnect cursor and live revocation ({time.monotonic() - started:.1f}s)', flush=True)
        print('Live acceptance session:', session)


if __name__ == '__main__':
    main()
