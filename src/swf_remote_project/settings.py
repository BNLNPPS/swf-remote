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
    'remote_app',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'swf_remote_project.expire_old_cookies.ExpireOldCookiesMiddleware',
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

# swf-monitor REST base URL (via SSH tunnel to pandaserver02)
SWF_MONITOR_URL = config('SWF_REMOTE_MONITOR_URL', default='https://localhost:18443/swf-monitor')
