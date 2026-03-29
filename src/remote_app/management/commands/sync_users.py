"""Sync user accounts from swf-monitor via the SSH tunnel.

Calls swf-monitor's /api/users/ endpoint and creates matching local
Django accounts. When the endpoint includes password hashes, copies
them so users have the same credentials on both systems.

Usage:
    python manage.py sync_users
    python manage.py sync_users --set-password changeme   # fallback if no hash
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
            help='Fallback password for new accounts when no hash available from upstream',
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
        updated_count = 0
        unchanged_count = 0

        for u in users:
            username = u.get('username', '').strip()
            if not username:
                continue
            pw_hash = u.get('password', '')
            user, created = User.objects.get_or_create(
                username=username,
                defaults={'is_active': u.get('is_active', True)},
            )
            if created:
                if pw_hash:
                    # Copy hash directly — same credentials, no plaintext
                    user.password = pw_hash
                    user.save(update_fields=['password'])
                elif options['set_password']:
                    user.set_password(options['set_password'])
                    user.save(update_fields=['password'])
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'  Created: {username}'))
            elif pw_hash and user.password != pw_hash:
                # Update existing user's password hash to match upstream
                user.password = pw_hash
                user.save(update_fields=['password'])
                updated_count += 1
                self.stdout.write(f'  Updated password: {username}')
            else:
                unchanged_count += 1

        self.stdout.write(
            f'Done. {created_count} created, {updated_count} updated, '
            f'{unchanged_count} unchanged (of {len(users)} from swf-monitor).'
        )
