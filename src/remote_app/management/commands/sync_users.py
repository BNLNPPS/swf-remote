"""Sync user accounts from swf-monitor via the SSH tunnel.

Calls swf-monitor's /api/users/ endpoint and creates matching local
Django accounts. Existing users are left untouched. Run anytime to
ensure devcloud accounts match BNL.

Usage:
    python manage.py sync_users
    python manage.py sync_users --set-password changeme
"""

import logging

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from remote_app import monitor_client

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Sync user accounts from swf-monitor'

    def add_arguments(self, parser):
        parser.add_argument(
            '--set-password',
            help='Set this password on newly created accounts (default: unusable password)',
        )

    def handle(self, *args, **options):
        data = monitor_client._get('/api/users/')
        if 'error' in data:
            self.stderr.write(self.style.ERROR(f"Failed to fetch users: {data['error']}"))
            return

        users = data.get('users', [])
        if not users:
            self.stdout.write('No users returned from swf-monitor.')
            return

        User = get_user_model()
        created_count = 0
        existing_count = 0

        for u in users:
            username = u.get('username', '').strip()
            if not username:
                continue
            user, created = User.objects.get_or_create(
                username=username,
                defaults={'is_active': u.get('is_active', True)},
            )
            if created:
                if options['set_password']:
                    user.set_password(options['set_password'])
                    user.save()
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'  Created: {username}'))
            else:
                existing_count += 1

        self.stdout.write(
            f'Done. {created_count} created, {existing_count} already existed '
            f'(of {len(users)} from swf-monitor).'
        )
