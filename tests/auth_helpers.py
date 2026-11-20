from __future__ import annotations

import hashlib
import hmac
import json
import re
from urllib.parse import unquote

from app import db
from app.models.user import Role, User

WHATSAPP_SECRET = 'test-app-secret'
BUSINESS_NUMBER = '+254700000000'


def whatsapp_text_payload(sender_wa_id: str, text: str, message_id: str = 'wamid-1') -> bytes:
    return json.dumps({
        'entry': [{'changes': [{'value': {'messages': [{
            'id': message_id, 'from': sender_wa_id, 'type': 'text', 'text': {'body': text},
        }]}}]}],
    }).encode()


def extract_token(text: str) -> str:
    match = re.search(r'token=([^\s&]+)', text)
    assert match, f'no token in {text!r}'
    return unquote(match.group(1))


class CapturingEmailSender:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)


class AuthFlowMixin:
    """Helpers for BaseTestCase subclasses exercising auth flows."""

    def configure_channels(self):
        self.app.config.update(
            WHATSAPP_APP_SECRET=WHATSAPP_SECRET,
            WHATSAPP_ACCESS_TOKEN='test-access-token',
            WHATSAPP_PHONE_NUMBER_ID='123',
            WHATSAPP_BUSINESS_NUMBER=BUSINESS_NUMBER,
            RESEND_API_KEY='re_test',
            EMAIL_FROM='Test <no-reply@example.test>',
        )

    def make_user(self, *, username='owner', password='OwnerPass123', role=Role.FARMER, phone=None,
                  email=None, phone_verified=False, email_verified=False, tenant=None, is_active=True):
        tenant = tenant or self.tenant
        user = User(
            tenant_id=tenant.id,
            identifier=f'{username}_id',
            username=username,
            name=username.title(),
            email=email,
            phone_number=phone,
            phone_verified=phone_verified,
            email_verified=email_verified,
            role=role,
            is_active=is_active,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user

    def login(self, login, password, *, client=None, ip='10.0.0.1'):
        client = client or self.client
        return client.post('/api/auth/login', json={'login': login, 'password': password},
                           environ_base={'REMOTE_ADDR': ip})

    def bearer(self, login, password, **kwargs):
        response = self.login(login, password, **kwargs)
        self.assertEqual(response.status_code, 200, response.get_json())
        return {'Authorization': f"Bearer {response.get_json()['access_token']}"}

    def post_whatsapp(self, sender_wa_id: str, text: str, message_id: str = 'wamid-1'):
        body = whatsapp_text_payload(sender_wa_id, text, message_id)
        signature = 'sha256=' + hmac.new(WHATSAPP_SECRET.encode(), body, hashlib.sha256).hexdigest()
        # Meta calls the webhook without any user cookies.
        return self.app.test_client().post('/api/whatsapp/webhook', data=body, headers={
            'X-Hub-Signature-256': signature, 'Content-Type': 'application/json',
        })
