#!/usr/bin/env python3
"""Focused browser CSRF/header checks using synthetic requests, without DB writes."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE','swf_remote_project.settings')
import django
django.setup()
from django.conf import settings
from django.http import HttpResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.test import RequestFactory, override_settings, SimpleTestCase
from remote_app.teamcomms import browser_csrf, _authenticated_request, _response_headers, proxy

@override_settings(ALLOWED_HOSTS=['epic-devcloud.org'], CSRF_TRUSTED_ORIGINS=['https://epic-devcloud.org'])
class BrowserChecks(SimpleTestCase):
    def request(self, method='get', **headers):
        r=getattr(RequestFactory(),method)('/prod/teamcomms/browser-csrf',secure=True,HTTP_HOST='epic-devcloud.org',**headers)
        r.user=SimpleNamespace(is_authenticated=True,is_active=True)
        return r
    def test_masked_token_sets_host_cookie_and_protects_posts(self):
        middleware=CsrfViewMiddleware(lambda r:HttpResponse())
        request=self.request();middleware.process_request(request)
        response=middleware.process_response(request,browser_csrf(request))
        body=json.loads(response.content)
        self.assertEqual(body['header_name'],'X-CSRFToken')
        self.assertEqual(len(body['token']),64)
        self.assertEqual(response['Cache-Control'],'no-store')
        self.assertIn(settings.CSRF_COOKIE_NAME,response.cookies)
        secret=response.cookies[settings.CSRF_COOKIE_NAME].value
        for token,expected in ((body['token'],None),('',403)):
            post=self.request('post',HTTP_X_CSRFTOKEN=token,HTTP_ORIGIN='https://epic-devcloud.org')
            post.COOKIES[settings.CSRF_COOKIE_NAME]=secret;middleware.process_request(post)
            _,rejection=_authenticated_request(post)
            self.assertEqual(rejection.status_code if rejection else None,expected)
    def test_endpoint_needs_session_and_get(self):
        request=self.request();request.user.is_authenticated=False
        self.assertEqual(browser_csrf(request).status_code,401)
        self.assertEqual(browser_csrf(self.request(HTTP_AUTHORIZATION='Bearer synthetic')).status_code,401)
        self.assertEqual(browser_csrf(self.request('post')).status_code,405)
    def test_proxy_preserves_security_headers_and_login_redirect(self):
        upstream=SimpleNamespace(headers={'Content-Security-Policy':"default-src 'self'",'X-Content-Type-Options':'nosniff','Referrer-Policy':'same-origin','Set-Cookie':'untrusted=1'})
        response=_response_headers(upstream,HttpResponse())
        self.assertEqual(response['X-Content-Type-Options'],'nosniff')
        self.assertNotIn('Set-Cookie',response)
        request=self.request(HTTP_ACCEPT='text/html');request.user.is_authenticated=False
        with override_settings(SWF_TEAMCOMMS_SERVICE_TOKEN='fixture-only'):
            result=proxy(request,subpath='entries')
        self.assertEqual(result.status_code,302)
        self.assertIn('next=',result['Location'])
if __name__=='__main__':unittest.main()
