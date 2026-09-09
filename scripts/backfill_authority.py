#!/usr/bin/env python3
"""Populate the account authority attributes for accounts that predate them.

An account may act when `rights` is not `read` and either `eic` is true or
`rights` grants it. Accounts created before either field existed carry
neither, so they can read but not act. This writes what each account is
entitled to, once.

What gets written, and why each is the honest value:

  GitHub-linked accounts get `eic` from the organization's member listing,
  together with the GitHub login the check was made against. Membership is
  read through the `gh` CLI rather than from each account's own OAuth token:
  every existing token was issued before the read:org scope was added and
  cannot answer the question. The listing is authoritative for private
  membership provided the token's owner is an organization member.

  Accounts with no GitHub identity get `rights: basic` and no `eic` at all.
  Their access was established inside the BNL authentication perimeter,
  through the swf-monitor account sync from pandaserver02. Writing `eic:
  false` for them would be recording a GitHub fact about an account that has
  no GitHub identity, and writing `eic: true` would be a fabrication.

  GitHub accounts that are not organization members get `eic: false` — the
  observation — and also `rights: basic`, grandfathering the people already
  working on the system while they go through the joining procedure. That
  grant is a person's decision, not an observation, which is why it lands in
  `rights`; a later sign-in re-observes `eic` and leaves `rights` untouched.

Dry run by default. Pass --apply to write.

    scripts/backfill_authority.py
    scripts/backfill_authority.py --apply
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / 'src'
sys.path.insert(0, str(SRC))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'swf_remote_project.settings')

import django  # noqa: E402
django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from allauth.socialaccount.models import SocialAccount  # noqa: E402

from remote_app import authority  # noqa: E402


def org_members(org: str) -> set[str]:
    """Lowercased logins of every visible member of the organization."""
    out = subprocess.run(
        ['gh', 'api', '--paginate', f'/orgs/{org}/members?per_page=100',
         '--jq', '.[].login'],
        capture_output=True, text=True, check=True,
    )
    return {line.strip().lower() for line in out.stdout.splitlines() if line.strip()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply', action='store_true',
                    help='write the attributes; otherwise report only')
    args = ap.parse_args()

    org = settings.EIC_ORG
    members = org_members(org)
    print(f'{len(members)} members visible in the {org} organization\n')

    links = {
        s.user_id: (s.extra_data or {}).get('login')
        for s in SocialAccount.objects.filter(provider='github')
    }

    # (username, eic, github, rights, basis). eic and rights go to separate
    # endpoints upstream, so an account needing both takes two calls.
    plan: list[tuple[str, bool | None, str, str | None, str]] = []
    for user in User.objects.order_by('username'):
        login = links.get(user.id)
        if login:
            member = login.lower() in members
            if member:
                plan.append((user.username, True, login, None,
                             f'{login} is a member; access follows eic'))
            else:
                plan.append((user.username, False, login, 'basic',
                             f'{login} is not a member; granted basic'))
        else:
            plan.append((user.username, None, '', 'basic',
                         'no GitHub identity; established through the BNL account sync'))

    width = max(len(name) for name, _, _, _, _ in plan)
    for name, eic, _, rights, basis in plan:
        shown = ', '.join(
            p for p in (f'eic={eic}' if eic is not None else '',
                        f'rights={rights}' if rights else '') if p)
        print(f'{name:{width}s}  {shown:24s}  {basis}')

    members_n = sum(1 for _, e, _, _, _ in plan if e is True)
    granted = sum(1 for _, _, _, r, _ in plan if r == 'basic')
    print(f'\n{members_n} recorded as members, {granted} granted basic, '
          f'{len(plan)} accounts')

    if not args.apply:
        print('\nDry run. Pass --apply to write.')
        return 0

    failures = 0
    for name, eic, github, rights, _ in plan:
        if eic is not None and not authority.record_membership(name, eic, github):
            failures += 1
            print(f'FAILED (membership): {name}')
        if rights and not authority.record_rights(name, rights):
            failures += 1
            print(f'FAILED (rights): {name}')
    print(f'\nfailures: {failures}')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
