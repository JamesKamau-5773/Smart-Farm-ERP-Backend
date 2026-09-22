from __future__ import annotations

import hashlib
import hmac
import json
import unittest.mock as mock

from app import db
from app.models.user import Role
from tests.base import BaseTestCase


def _whatsapp_payload(phone: str, message_id: str = 'm-1', text: str = 'menu') -> bytes:
    return json.dumps({
        'entry': [{
            'changes': [{
                'value': {
                    'messages': [{
                        'id': message_id,
                        'from': phone,
                        'type': 'text',
                        'text': {'body': text},
                    }],
                },
            }],
        }],
    }).encode()


class WhatsAppWebhookTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.app.config['WHATSAPP_APP_SECRET'] = 'test-app-secret'
        self.app.config['WHATSAPP_VERIFY_TOKEN'] = 'test-verify-token'

        self.phone = '254712345678'
        self.user = self.create_user(
            username='farmhand', password='pass', role=Role.FARM_HAND,
        )
        self.user.phone_number = self.phone
        db.session.commit()

    def _signed_headers(self, body: bytes) -> dict:
        sig = 'sha256=' + hmac.new(
            self.app.config['WHATSAPP_APP_SECRET'].encode(), body, hashlib.sha256
        ).hexdigest()
        return {'X-Hub-Signature-256': sig, 'Content-Type': 'application/json'}

    @mock.patch('app.services.whatsapp_message_service.send_message')
    def test_registered_user_gets_menu_reply(self, mock_send):
        body = _whatsapp_payload(self.phone)
        response = self.client.post(
            '/api/whatsapp/webhook', data=body, headers=self._signed_headers(body),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), 'OK')

        # The farmhand must receive exactly one outbound message, addressed to them,
        # and it must be the interactive main menu (not a plain-text error).
        mock_send.assert_called_once()
        to_number, message = mock_send.call_args.args
        self.assertEqual(to_number, self.phone)
        self.assertEqual(message.get('type'), 'interactive')

    @mock.patch('app.services.whatsapp_message_service.send_message')
    def test_unregistered_number_gets_no_reply(self, mock_send):
        body = _whatsapp_payload('254799999999')
        response = self.client.post(
            '/api/whatsapp/webhook', data=body, headers=self._signed_headers(body),
        )
        self.assertEqual(response.status_code, 200)
        mock_send.assert_not_called()

    def test_missing_signature_is_rejected(self):
        body = _whatsapp_payload(self.phone)
        response = self.client.post(
            '/api/whatsapp/webhook', data=body, content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)

    def test_invalid_signature_is_rejected(self):
        body = _whatsapp_payload(self.phone)
        response = self.client.post(
            '/api/whatsapp/webhook', data=body,
            headers={'X-Hub-Signature-256': 'sha256=bad', 'Content-Type': 'application/json'},
        )
        self.assertEqual(response.status_code, 403)

    def test_verification_handshake(self):
        response = self.client.get(
            '/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=test-verify-token&hub.challenge=xyz',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), 'xyz')

    @mock.patch('app.utils.db_init.ensure_super_admin_account', side_effect=RuntimeError('db unavailable'))
    def test_verification_handshake_skips_bootstrap_db_errors(self, _mock_bootstrap):
        response = self.client.get(
            '/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=test-verify-token&hub.challenge=xyz',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), 'xyz')
