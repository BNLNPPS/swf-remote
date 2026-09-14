#!/usr/bin/env python3
"""Focused token metadata/introspection checks without database writes or HTTP."""

import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'swf_remote_project.settings')
import django
django.setup()

from django.test import RequestFactory, override_settings
from django.utils import timezone
from remote_app.teamcomms import introspect
from remote_app.token_auth import issue_token


class IdentityChecks(unittest.TestCase):
    def response(self, kind='', ai=False, revoked=False, active=True):
        user = SimpleNamespace(pk=42, username='fixture', is_authenticated=True,
                               is_active=active, get_full_name=lambda: 'Fixture')
        token = SimpleNamespace(user=user, user_id=42, teamcomms_ai=ai,
                                teamcomms_service_kind=kind, revoked=timezone.now() if revoked else None)
        reference = SimpleNamespace(user_id=42, token_id=7, token=token, csrf_verified=False,
            method='POST', path='/api/comms/messages', query_string='', body_sha256='0' * 64,
            expires_at=timezone.now())
        request = RequestFactory().post('/teamcomms-auth/introspect/',
            data=json.dumps({'reference': 'r' * 64}), content_type='application/json',
            HTTP_AUTHORIZATION='Bearer fixture-service-secret')
        with override_settings(SWF_TEAMCOMMS_SERVICE_TOKEN='fixture-service-secret'), \
             patch('remote_app.teamcomms.TeamCommsAuthReference.objects') as manager:
            manager.select_related.return_value.filter.return_value.first.return_value = reference
            response = introspect(request)
        return response.status_code, json.loads(response.content)

    def test_service_subject_is_bound_to_account_not_label(self):
        for kind in ('program', 'connector'):
            with self.subTest(kind=kind):
                status, body = self.response(kind)
                self.assertEqual(status, 200)
                self.assertEqual((body['subject'], body['account_subject'], body['kind']),
                                 (kind + ':42', '42', kind))
                self.assertEqual(body['auth_method'], 'token')
                self.assertNotIn('operator', body)

    def test_existing_human_ai_identity_and_revocation(self):
        self.assertEqual(self.response()[1]['subject'], '42')
        ai = self.response(ai=True)[1]
        self.assertEqual(ai['subject'], 'ai:42')
        self.assertEqual(ai['operator']['subject'], '42')
        for kind in ('program', 'connector'):
            self.assertEqual(self.response(kind, revoked=True)[0], 401)
            self.assertEqual(self.response(kind, active=False)[0], 401)

    def test_invalid_metadata_is_rejected_before_issuance(self):
        with patch('remote_app.models.ApiToken.objects.create') as create:
            for kind, ai in (('admin', False), ('program', True), ('connector', True)):
                with self.assertRaises(ValueError):
                    issue_token(object(), teamcomms_ai=ai, teamcomms_service_kind=kind)
            create.assert_not_called()


if __name__ == '__main__':
    unittest.main()
