"""
Django settings for swf-remote — external ePIC PanDA monitoring frontend.

Consumes swf-monitor REST endpoints via SSH tunnel.
"""

from pathlib import Path
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SWF_REMOTE_SECRET_KEY')
DEBUG = config('SWF_REMOTE_DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('SWF_REMOTE_ALLOWED_HOSTS', default='localhost,127.0.0.1').split(',')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    # GitHub is the only provider. allauth calls this package family
    # "socialaccount"; that is its name for third-party OAuth, not an
    # indication that any consumer identity provider is enabled. A provider
    # absent from INSTALLED_APPS has no URL and no code path.
    'allauth.socialaccount.providers.github',
    'remote_app',
]

# django.contrib.sites is deliberately absent: allauth treats it as optional
# and resolves the host from the request, so the provider credentials live in
# settings rather than in a database row that has to be kept in step.

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'remote_app.proxy_identity.ProxyIdentityMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'swf_remote_project.expire_old_cookies.ExpireOldCookiesMiddleware',
    'allauth.account.middleware.AccountMiddleware',
]

ROOT_URLCONF = 'swf_remote_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            BASE_DIR / 'templates',                    # swf-remote overrides (base.html, etc.)
            BASE_DIR / 'monitor_templates',            # symlink to swf-monitor templates
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'swf_remote_project.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('SWF_REMOTE_DB_NAME', default='swf_remote'),
        'USER': config('SWF_REMOTE_DB_USER', default='swf_remote'),
        'PASSWORD': config('SWF_REMOTE_DB_PASSWORD', default=''),
        'HOST': config('SWF_REMOTE_DB_HOST', default='localhost'),
        'PORT': config('SWF_REMOTE_DB_PORT', default='5432'),
    },
}

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'America/New_York'
USE_I18N = True
USE_TZ = True

# Subpath deployment (e.g. /prod on epic-devcloud.org)
FORCE_SCRIPT_NAME = config('SWF_REMOTE_FORCE_SCRIPT_NAME', default='') or None

STATIC_URL = config('SWF_REMOTE_STATIC_URL', default='/static/')
STATIC_ROOT = BASE_DIR.parent / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Cookie scoping — unique names prevent conflicts with other apps on same domain
_subpath = FORCE_SCRIPT_NAME or ""
CSRF_COOKIE_PATH = _subpath or "/"
SESSION_COOKIE_PATH = _subpath or "/"
CSRF_COOKIE_NAME = 'csrftoken_prod'
SESSION_COOKIE_NAME = 'sessionid_prod'

# Behind Apache reverse proxy
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# Authentication
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'monitor_app:prod_home'
LOGOUT_REDIRECT_URL = 'monitor_app:home'

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

# GitHub sign-in. An account is created on first sign-in, so collaborators
# need no locally provisioned username or password. Signing in confers no
# privilege beyond an ordinary account: it establishes an identity that
# outlives a request, which anonymous traffic cannot supply. Cache policy is
# enforced upstream in swf-monitor — see docs/live-data-access.md.
SOCIALACCOUNT_ONLY = False
SOCIALACCOUNT_AUTO_SIGNUP = True
# Signing in with GitHub on an address that already has an account signs into
# that account and links it, rather than stopping at a signup form. The match
# is against verified EmailAddress rows, so an account is reachable this way
# only once it has been marked verified — see docs/live-data-access.md.
SOCIALACCOUNT_EMAIL_AUTHENTICATION = True
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True
SOCIALACCOUNT_EMAIL_REQUIRED = False
# Must be set explicitly: it otherwise follows EMAIL_REQUIRED above, and when
# off the provider's /user/emails call is skipped entirely. Without that call
# no address arrives marked verified, and email authentication — which
# considers verified provider addresses only — can never match an account.
SOCIALACCOUNT_QUERY_EMAIL = True
SOCIALACCOUNT_EMAIL_VERIFICATION = 'none'
ACCOUNT_EMAIL_VERIFICATION = 'none'
# Provider sign-in is reached by POST from the login page, so a third party
# cannot start the flow with a bare link.
SOCIALACCOUNT_LOGIN_ON_GET = False
SOCIALACCOUNT_PROVIDERS = {
    'github': {
        'APP': {
            'client_id': config('SWF_REMOTE_GITHUB_CLIENT_ID', default=''),
            'secret': config('SWF_REMOTE_GITHUB_SECRET', default=''),
            'key': '',
        },
        # Identity only. read:org would be required to check eic membership,
        # which is deliberately not a condition of signing in. user:email is
        # what makes GitHub report whether an address is verified, which
        # email authentication requires before it will match an account.
        'SCOPE': ['read:user', 'user:email'],
    },
}

# swf-monitor REST base URL (via SSH tunnel to pandaserver02)
SWF_MONITOR_URL = config('SWF_REMOTE_MONITOR_URL', default='https://localhost:18443/swf-monitor')

# Service token for the SSE stream proxy hop (monitor_client.stream_sse). The
# monitor's SSE endpoint honors Authorization: Token, not the X-Remote-User the
# HTML proxy uses, so this is provisioned separately on ec2dev. See
# swf-monitor/docs/SSE_PUSH.md.
SWF_MONITOR_TOKEN = config('SWF_REMOTE_MONITOR_TOKEN', default='')
