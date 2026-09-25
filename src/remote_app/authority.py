"""Organization membership, observed at sign-in and recorded upstream.

Two things decide whether an account may act on the production system, and
they are kept apart because they have different owners:

    eic     unset | true | false          observed; written only by this module
    rights  unset | read | basic | ops    granted; written only by a person

An account may act when `rights` is not `read` and either `eic` is true or
`rights` grants it (`basic` or `ops`). Reading monitoring information needs
only a signed-in account, at every level.

Provenance is carried by which field a value sits in rather than by a marker
recording who wrote it. This module maintains `eic` and nothing else, so a
grant made by a person is never undone by a later sign-in; a person maintains
`rights` and nothing else, so someone who leaves the organization loses access
at their next sign-in without anyone acting. `rights: read` is an explicit
refusal that outranks membership.

Both fields live on the account in swf-monitor, beside the identity that
component already establishes from `X-Remote-User`, and enforcement is there
too — so a person reaching swf-monitor directly inside the perimeter is judged
by the same rule as one arriving through this proxy. swf-remote is where
GitHub sign-in happens, which is the only reason membership is observed here
rather than there.

A check that cannot reach an answer writes nothing. Recording a negative on a
network failure or a revoked token would strip access from an account that
still holds it, so an indeterminate result leaves the stored value alone.

See docs/live-data-access.md.
"""
from __future__ import annotations

import logging

import httpx
from allauth.account.signals import user_logged_in
from django.conf import settings
from django.dispatch import receiver

from . import monitor_client

logger = logging.getLogger(__name__)

GITHUB_API = 'https://api.github.com'
TIMEOUT = 15

# swf-monitor exposes membership and rights as separate endpoints, so the
# path a sign-in travels cannot reach `rights` at all — the separation is
# enforced by URL rather than by inspecting a request body in a handler both
# callers share.
AUTHORITY_PATH = '/api/user-authority/'
RIGHTS_PATH = '/api/user-rights/'

# Identity presented to swf-monitor for the authority write. It is deliberately
# distinct from the general sync identity and from any person: the endpoint
# writes privilege, so it refuses a caller wearing someone's name. The value is
# reserved in ACCOUNT_USERNAME_BLACKLIST so no GitHub login can become it.
SERVICE_USER = 'swf-remote-authority'

RIGHTS_VALUES = ('read', 'basic', 'ops')


def github_token(user) -> str | None:
    """The user's stored GitHub OAuth token, or None if they have no link."""
    try:
        from allauth.socialaccount.models import SocialToken
        token = (SocialToken.objects
                 .filter(account__user=user, account__provider='github')
                 .order_by('-id')
                 .first())
        return token.token if token else None
    except Exception as e:
        logger.error(f"authority: reading GitHub token for {user}: {e}")
        return None


def github_login(user) -> str | None:
    """The user's GitHub login name, or None if they have no link."""
    try:
        from allauth.socialaccount.models import SocialAccount
        account = (SocialAccount.objects
                   .filter(user=user, provider='github')
                   .order_by('-id')
                   .first())
        return (account.extra_data or {}).get('login') if account else None
    except Exception as e:
        logger.error(f"authority: reading GitHub account for {user}: {e}")
        return None


# Scopes under which /user/memberships can see a private membership.
ORG_READ_SCOPES = {'read:org', 'write:org', 'admin:org'}


def check_membership(token: str, org: str | None = None) -> tuple[bool | None, str]:
    """Whether the token's owner belongs to the organization, and if not
    established, why.

    Returns (True|False, '') on a definite answer and (None, reason) when the
    answer could not be established. Uses the caller's own token against
    /user/memberships, so a private membership — GitHub's default — is
    visible, but only to a token carrying read:org. Without it a private
    member reads as absent, so a 404 is believed only from a token whose
    X-OAuth-Scopes include an org-read scope: every token issued before the
    scope was requested would otherwise record members as non-members.
    """
    org = org or settings.EIC_ORG
    url = f'{GITHUB_API}/user/memberships/orgs/{org}'
    try:
        resp = httpx.get(url, timeout=TIMEOUT, headers={
            'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github+json',
        })
    except Exception as e:
        logger.error(f"authority: GitHub membership check failed: {e}")
        return None, f'GitHub could not be reached ({type(e).__name__})'

    scopes = {s.strip() for s in resp.headers.get('X-OAuth-Scopes', '').split(',')
              if s.strip()}
    if resp.status_code in (200, 404) and not scopes & ORG_READ_SCOPES:
        return None, ('the GitHub token lacks the read:org scope, so a private '
                      'membership cannot be seen; sign in again to grant it')
    if resp.status_code == 200:
        state = (resp.json() or {}).get('state')
        if state == 'active':
            return True, ''
        # 'pending' is an unaccepted invitation — not yet a member.
        logger.info(f"authority: membership state '{state}' for org {org}")
        return False, ''
    if resp.status_code == 404:
        return False, ''
    if resp.status_code in (401, 403):
        detail = ''
        try:
            detail = str((resp.json() or {}).get('message', ''))[:200]
        except Exception:
            pass
        return None, (f'GitHub refused the membership check ({resp.status_code}'
                      f'{": " + detail if detail else ""}); the token may be '
                      f'revoked, or the {org} organization has not approved '
                      f'this application')
    return None, f'GitHub answered the membership check with {resp.status_code}'


def resolve_membership(token: str, org: str | None = None) -> bool | None:
    """check_membership without the reason."""
    return check_membership(token, org)[0]


def _save_status(username: str, **fields) -> None:
    """Keep the account's latest check where the account menu reads it."""
    from django.contrib.auth.models import User
    from .models import AuthorityStatus

    user = User.objects.filter(username=username).first()
    if user is None:
        return
    AuthorityStatus.objects.update_or_create(user=user, defaults=fields)


def record_membership(username: str, eic: bool | None, github: str = '') -> bool:
    """Record observed organization membership on the account in swf-monitor.

    This endpoint refuses `rights`, so no fault in the sign-in path can reach
    a grant. `eic=None` clears the observation. Only a write swf-monitor
    accepted counts; the account menu's copy is updated after it.
    """
    if not username:
        return False
    attributes: dict = {'eic': eic}
    if github:
        attributes['github'] = github
    result = monitor_client._post(
        AUTHORITY_PATH,
        {'username': username, 'authority': attributes},
        as_user=SERVICE_USER,
    )
    if not isinstance(result, dict) or result.get('error') \
            or not isinstance(result.get('authority'), dict):
        logger.error(f"authority: recording {attributes} for {username} failed: "
                     f"{(result or {}).get('error') if isinstance(result, dict) else result!r}")
        return False
    from django.utils import timezone
    _save_status(username, github=github, eic=eic, checked_at=timezone.now(),
                 failed='', failed_at=None)
    logger.info(f"authority: recorded {attributes} for {username}")
    return True


def report_failure(username: str, reason: str, github: str = '') -> None:
    """A GitHub sign-in whose check reached no answer: surface it everywhere.

    The account menu shows it (local copy), swf-monitor records it for the
    authority_check alarm and the User admin page, and the log carries it at
    ERROR. The stored `eic` is left alone upstream: a check without an answer
    is not an observation.
    """
    from django.utils import timezone
    logger.error(f"authority: membership check for {username} ({github or 'no login'}) "
                 f"reached no answer: {reason}")
    _save_status(username, github=github, failed=reason, failed_at=timezone.now())
    attributes: dict = {'check_failed': reason}
    if github:
        attributes['github'] = github
    result = monitor_client._post(
        AUTHORITY_PATH,
        {'username': username, 'authority': attributes},
        as_user=SERVICE_USER,
    )
    if not isinstance(result, dict) or result.get('error'):
        # The monitor's alarm still catches an account with no record at all.
        logger.error(f"authority: reporting the failed check for {username} "
                     f"upstream failed too: {result!r}")


def record_rights(username: str, rights: str | None) -> bool:
    """Grant or clear rights on the account in swf-monitor.

    A person's decision, never the sweep's: the sign-in path does not call
    this, and the endpoint it posts to refuses `eic`. `rights=None` clears the
    grant.
    """
    if not username:
        return False
    if rights is not None and rights not in RIGHTS_VALUES:
        logger.error(f"authority: refusing unknown rights {rights!r} for {username}")
        return False
    result = monitor_client._post(
        RIGHTS_PATH,
        {'username': username, 'rights': rights},
        as_user=SERVICE_USER,
    )
    if isinstance(result, dict) and result.get('error'):
        logger.error(f"authority: granting rights {rights!r} to {username} "
                     f"failed: {result['error']}")
        return False
    logger.info(f"authority: granted rights {rights!r} to {username}")
    return True


def refresh_for(user) -> bool | None:
    """Observe one signed-in user's membership and record it upstream.

    Writes `eic` and the GitHub login the check was made against, so the
    account pages can show which identity was tested — several accounts carry
    a Django username unlike their GitHub login. Never writes `rights`.

    Every GitHub-linked account ends in one of two outcomes: a membership
    write swf-monitor accepted, or a reported failure (report_failure). From
    the 9/9 backfill to 9/25 every sign-in took a third, silent path — no
    token was stored, and this function returned without a word.

    Returns the membership observed, or None when nothing was observed.
    """
    login = github_login(user) or ''
    token = github_token(user)
    if not token:
        if login:
            report_failure(user.username, 'no stored GitHub token for the '
                           'account, so membership could not be asked', login)
        # Otherwise a local account, with no GitHub identity to observe. Its
        # access was established inside the BNL perimeter and is carried by
        # `rights`.
        return None
    member, reason = check_membership(token)
    if member is None:
        report_failure(user.username, reason, login)
        return None
    if not record_membership(user.username, member, login):
        report_failure(user.username, 'swf-monitor did not accept the '
                       'membership write', login)
        return None
    return member


@receiver(user_logged_in)
def refresh_on_login(sender, request, user, **kwargs):
    """Re-observe the account's membership on every sign-in."""
    try:
        refresh_for(user)
    except Exception as e:
        # Sign-in must not fail because the check did: the account keeps
        # whatever it already holds, and the failure is reported like any
        # other check that reached no answer.
        logger.error(f"authority: refresh on login for {user} failed: {e}")
        try:
            report_failure(user.username, f'the check raised {type(e).__name__}',
                           github_login(user) or '')
        except Exception as inner:
            logger.error(f"authority: reporting that failure raised too: {inner}")
