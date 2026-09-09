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


def resolve_membership(token: str, org: str | None = None) -> bool | None:
    """Whether the token's owner belongs to the organization.

    Returns True or False on a definite answer, None when the answer could not
    be established. Uses the caller's own token against /user/memberships, so
    a private membership — GitHub's default — is visible; this is what the
    read:org scope is for.
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
        return None

    if resp.status_code == 200:
        state = (resp.json() or {}).get('state')
        if state == 'active':
            return True
        # 'pending' is an unaccepted invitation — not yet a member.
        logger.info(f"authority: membership state '{state}' for org {org}")
        return False
    if resp.status_code == 404:
        return False
    if resp.status_code in (401, 403):
        logger.error(
            f"authority: GitHub returned {resp.status_code} for {url} — the "
            f"token is missing the read:org scope, or was revoked; leaving "
            f"the stored value alone")
        return None
    logger.error(f"authority: GitHub {resp.status_code} for {url}")
    return None


def record_membership(username: str, eic: bool | None, github: str = '') -> bool:
    """Record observed organization membership on the account in swf-monitor.

    This endpoint refuses `rights`, so no fault in the sign-in path can reach
    a grant. `eic=None` clears the observation.
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
    if isinstance(result, dict) and result.get('error'):
        logger.error(f"authority: recording {attributes} for {username} failed: "
                     f"{result['error']}")
        return False
    logger.info(f"authority: recorded {attributes} for {username}")
    return True


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

    Returns the membership observed, or None when nothing was written.
    """
    token = github_token(user)
    if not token:
        # A local account, with no GitHub identity to observe. Its access was
        # established inside the BNL perimeter and is carried by `rights`.
        return None
    member = resolve_membership(token)
    if member is None:
        return None
    record_membership(user.username, member, github_login(user) or '')
    return member


@receiver(user_logged_in)
def refresh_on_login(sender, request, user, **kwargs):
    """Re-observe the account's membership on every sign-in."""
    try:
        refresh_for(user)
    except Exception as e:
        # Sign-in must not fail because the check did: the account keeps
        # whatever it already holds.
        logger.error(f"authority: refresh on login for {user} failed: {e}")
