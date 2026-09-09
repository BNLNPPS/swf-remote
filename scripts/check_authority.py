#!/usr/bin/env python3
"""Exercise the authority paths a user actually hits.

Run before deploying a change to sign-in membership resolution, after
swf-monitor's authority endpoint changes, and once more against the deployed
site. Failures here surface to a person mid-action, so the paths that must not
break are checked against live GitHub rather than mocked.

Scope is what swf-remote owns: observing membership and recording it. The
rule that decides whether an account may act is enforced in swf-monitor and is
checked there — reimplementing it here would be a second copy to drift.

Needs a GitHub token with the read:org scope in GH_TOKEN, or the `gh` CLI
logged in. The token stands in for a signed-in user's own token, which is what
the sign-in hook uses.

    scripts/check_authority.py
"""
from __future__ import annotations

import os
import subprocess
from contextlib import contextmanager
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / 'src'
sys.path.insert(0, str(SRC))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'swf_remote_project.settings')

import django  # noqa: E402
django.setup()

from django.conf import settings  # noqa: E402
settings.ALLOWED_HOSTS = ['*']  # in-process only, for the test client

from django.contrib.auth.models import User  # noqa: E402
from django.test import Client  # noqa: E402
from allauth.socialaccount.models import SocialAccount  # noqa: E402

from remote_app import authority  # noqa: E402

@contextmanager
def preserved_last_login(user):
    """Sign a real account in without leaving a sign-in that never happened.

    The checks run against the live database, and Client.force_login fires the
    login signal, which stamps last_login. That column is shown on the User
    admin page and read when deciding a grant, so a test must not write it.
    Restored with queryset.update, which fires no signals.
    """
    from django.contrib.auth.models import User as U
    before = U.objects.filter(pk=user.pk).values_list('last_login', flat=True).first()
    try:
        yield
    finally:
        U.objects.filter(pk=user.pk).update(last_login=before)


results: list[tuple[bool, str, str]] = []


def check(name: str, condition: bool, detail: str = '') -> None:
    results.append((condition, name, detail))
    print(f'{"PASS" if condition else "FAIL"}  {name}' + (f'  — {detail}' if detail else ''))


def token() -> str:
    tok = os.environ.get('GH_TOKEN')
    if tok:
        return tok
    return subprocess.run(['gh', 'auth', 'token'], capture_output=True,
                          text=True, check=True).stdout.strip()


def main() -> int:
    org = settings.EIC_ORG
    tok = token()

    # ── Membership observation against live GitHub ─────────────────────────
    # A member must read as a member. A false negative here does not lock a
    # collaborator out by itself, but it writes eic=false over a true value.
    check(f'member of {org} resolves True',
          authority.resolve_membership(tok, org) is True)

    # A non-member must read as a non-member, not as indeterminate: an
    # indeterminate result writes nothing and leaves a stale value standing.
    absent = authority.resolve_membership(tok, 'python')
    check('non-member org resolves False', absent is False, f'got {absent!r}')

    # A bad credential must be indeterminate, never False. Writing False here
    # would revoke every account that signed in during a GitHub outage.
    bad = authority.resolve_membership('ghp_' + 'x' * 36, org)
    check('invalid token resolves None, not False', bad is None, f'got {bad!r}')

    check('unknown org resolves False',
          authority.resolve_membership(tok, 'org-that-does-not-exist-' + 'z' * 12) is False)

    # ── The sweep writes eic, never rights ─────────────────────────────────
    # This is the whole basis of the model: a person's grant must survive
    # every subsequent sign-in, which holds only if the sweep cannot write
    # the field that carries it.
    import inspect
    source = inspect.getsource(authority.refresh_for)
    check('sign-in path never calls the rights endpoint',
          'record_rights' not in source and 'RIGHTS_PATH' not in source)

    # An unknown rights value is refused rather than stored, so a typo cannot
    # create a level that enforcement does not recognise.
    check('record_rights() refuses an unknown level',
          authority.record_rights('swf-remote-sync', 'administrator') is False)

    # ── Degradation while the endpoint is absent ───────────────────────────
    # Until swf-monitor ships the endpoint this returns False and logs. It
    # must not raise, or every sign-in raises with it.
    try:
        # Clears rather than asserts: a service account has no GitHub
        # membership, so this exercises the call without writing a claim.
        wrote = authority.record_membership('swf-remote-sync', None)
        check('record_membership() returns a bool and never raises', isinstance(wrote, bool),
              f'returned {wrote!r}')
    except Exception as e:
        check('record() returns a bool and never raises', False, repr(e))

    # ── Sign-in must survive a failing membership check ────────────────────
    linked = SocialAccount.objects.filter(provider='github').first()
    if linked:
        client = Client()
        try:
            with preserved_last_login(linked.user):
                client.force_login(linked.user)
                landed = client.get('/prod/').status_code
            check('login with a GitHub-linked account still completes',
                  landed in (200, 302), f'/prod/ returned {landed}')
        except Exception as e:
            check('login with a GitHub-linked account still completes', False, repr(e))
    else:
        check('login with a GitHub-linked account still completes', False,
              'no GitHub-linked account to test with')

    # A local account has no GitHub token: the sweep must decline quietly and
    # leave the rights the BNL sync established.
    local = (User.objects
             .exclude(id__in=SocialAccount.objects.values('user_id'))
             .first())
    if local:
        check('local account: sweep writes nothing',
              authority.refresh_for(local) is None, local.username)

    failed = [n for ok, n, _ in results if not ok]
    print(f'\n{len(results) - len(failed)}/{len(results)} passed')
    if failed:
        print('failed: ' + ', '.join(failed))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
