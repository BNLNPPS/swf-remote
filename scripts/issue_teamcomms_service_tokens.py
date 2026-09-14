#!/usr/bin/env python3
"""Issue program/connector tokens through existing account login and token UI."""

import argparse
import json
import os
from pathlib import Path
import stat

import httpx
from check_teamcomms import issue, login


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='https://epic-devcloud.org/prod')
    parser.add_argument('--credentials', type=Path, default=Path('/home/admin/.swf-remote-claude-ec2dev.env'))
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    directory = args.output_dir.expanduser().resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError('Output directory must be private and owned by this user')
    for name in ('program-token', 'connector-token', 'token-records.json'):
        if (directory / name).exists():
            raise ValueError('Output already exists; retain existing tokens or choose a new directory')
    records = {}
    with httpx.Client(follow_redirects=True, timeout=35) as client:
        login(client, args.base, args.credentials)
        for kind in ('program', 'connector'):
            raw, token_id = issue(client, args.base + '/account/tokens/', ai=False, service_kind=kind)
            path = directory / (kind + '-token')
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as stream:
                stream.write(raw + '\n')
            records[kind] = {'token_id': token_id, 'file': str(path)}
            # Retain revocation references even if later issuance fails.
            record_path = directory / 'token-records.json'
            fd = os.open(record_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(records, stream, indent=2)
            print(f'Issued {kind} token into private file {path}')


if __name__ == '__main__':
    main()
