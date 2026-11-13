from unittest import mock

from app import db
from app.models.auth import AccountDataIssue, VerificationChallenge
from app.models.user import User
from tests.auth_helpers import AuthFlowMixin
from tests.base import BaseTestCase


@mock.patch('app.services.whatsapp_message_service.send_message')
class PhoneVerificationTestCase(AuthFlowMixin, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.configure_channels()
        self.user = self.make_user(username='jane', phone='+254712345678')
        self.headers = self.bearer('jane', 'OwnerPass123')

    def _start(self, **body):
        return self.client.post('/api/auth/phone/verification', json=body, headers=self.headers)

    def _status(self, verification_id):
        return self.client.get(f'/api/auth/phone/verification/{verification_id}', headers=self.headers).get_json()

    def test_full_reverse_otp_flow(self, send_message):
        start = self._start()
        self.assertEqual(start.status_code, 201)
        data = start.get_json()
        self.assertRegex(data['message_text'], r'^VERIFY-\d{6}$')
        self.assertEqual(data['whatsapp_number'], '+254700000000')
        self.assertEqual(data['wa_link'], f"https://wa.me/254700000000?text={data['message_text']}")
        self.assertEqual(data['expires_in_seconds'], 600)
        self.assertEqual(self._status(data['verification_id'])['status'], 'pending')

        self.assertEqual(self.post_whatsapp('254712345678', data['message_text']).status_code, 200)

        self.assertEqual(self._status(data['verification_id'])['status'], 'verified')
        self.assertTrue(db.session.get(User, self.user.id).phone_verified)
        to_number, message = send_message.call_args.args
        self.assertEqual(to_number, '254712345678')
        self.assertIn('verified', message['text']['body'])

    def test_codes_are_stored_only_as_hashes(self, _send):
        code = self._start().get_json()['message_text'].split('-')[1]
        challenge = VerificationChallenge.query.one()
        self.assertNotIn(code, challenge.secret_hash)
        self.assertEqual(len(challenge.secret_hash), 64)

    def test_code_from_a_different_number_does_not_verify(self, _send):
        data = self._start().get_json()
        self.post_whatsapp('254799999999', data['message_text'])
        self.assertEqual(self._status(data['verification_id'])['status'], 'pending')
        self.assertFalse(db.session.get(User, self.user.id).phone_verified)

    def test_five_wrong_codes_lock_the_challenge(self, send_message):
        data = self._start().get_json()
        code = int(data['message_text'].split('-')[1])
        wrong_code = f'VERIFY-{(code + 1) % 1_000_000:06d}'
        for attempt in range(5):
            self.post_whatsapp('254712345678', wrong_code, message_id=f'wrong-{attempt}')
        self.post_whatsapp('254712345678', data['message_text'], message_id='right')
        status = self._status(data['verification_id'])
        self.assertEqual(status['status'], 'locked')
        self.assertEqual(status['attempts_remaining'], 0)
        self.assertFalse(db.session.get(User, self.user.id).phone_verified)
        self.assertIn('invalid', send_message.call_args.args[1]['text']['body'])

    def test_expired_code_is_rejected(self, _send):
        data = self._start().get_json()
        challenge = VerificationChallenge.query.one()
        challenge.expires_at = challenge.expires_at.replace(year=2000)
        db.session.commit()
        self.post_whatsapp('254712345678', data['message_text'])
        self.assertEqual(self._status(data['verification_id'])['status'], 'expired')

    def test_redelivered_webhook_is_ignored(self, send_message):
        data = self._start().get_json()
        self.post_whatsapp('254712345678', data['message_text'], message_id='dup')
        self.post_whatsapp('254712345678', data['message_text'], message_id='dup')
        self.assertEqual(send_message.call_count, 1)

    def test_new_number_is_applied_only_after_verification(self, _send):
        data = self._start(phone_number='0722000111').get_json()
        self.assertEqual(data['phone_number'], '+254722000111')
        self.assertEqual(db.session.get(User, self.user.id).phone_number, '+254712345678')
        self.post_whatsapp('254722000111', data['message_text'])
        user = db.session.get(User, self.user.id)
        self.assertEqual((user.phone_number, user.phone_verified), ('+254722000111', True))

    def test_verified_possession_reclaims_an_unverified_number(self, _send):
        squatter = self.make_user(username='squatter', phone='+254733000222')
        data = self._start(phone_number='0733000222').get_json()
        self.post_whatsapp('254733000222', data['message_text'])
        self.assertIsNone(db.session.get(User, squatter.id).phone_number)
        self.assertEqual(db.session.get(User, self.user.id).phone_number, '+254733000222')
        issue = AccountDataIssue.query.filter_by(user_id=squatter.id).one()
        self.assertEqual((issue.issue_type, issue.conflicting_user_id), ('PHONE_RECLAIMED', self.user.id))

    def test_cannot_start_for_a_number_verified_elsewhere(self, _send):
        self.make_user(username='owner2', phone='+254733000222', phone_verified=True)
        response = self._start(phone_number='0733000222')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['code'], 'PHONE_IN_USE')

    def test_already_verified_phone_is_rejected(self, _send):
        self.user.phone_verified = True
        db.session.commit()
        self.assertEqual(self._start().get_json()['code'], 'PHONE_ALREADY_VERIFIED')

    def test_restart_cancels_previous_challenge(self, _send):
        first = self._start().get_json()
        self._start()
        self.assertEqual(self._status(first['verification_id'])['status'], 'cancelled')

    def test_status_of_another_users_challenge_is_not_found(self, _send):
        data = self._start().get_json()
        self.make_user(username='other', password='OtherPass123')
        other_headers = self.bearer('other', 'OtherPass123', ip='10.0.0.9')
        response = self.client.get(f"/api/auth/phone/verification/{data['verification_id']}", headers=other_headers)
        self.assertEqual(response.status_code, 404)

    def test_regular_bot_messages_still_reach_the_command_router(self, send_message):
        self.post_whatsapp('254712345678', 'menu')
        self.assertEqual(send_message.call_args.args[1]['type'], 'interactive')


class PhoneVerificationUnavailableTestCase(AuthFlowMixin, BaseTestCase):
    def test_start_is_refused_when_no_business_number_is_configured(self):
        self.configure_channels()
        self.app.config['WHATSAPP_BUSINESS_NUMBER'] = None
        self.make_user(username='jane', phone='+254712345678')
        headers = self.bearer('jane', 'OwnerPass123')
        response = self.client.post('/api/auth/phone/verification', json={}, headers=headers)
        self.assertEqual((response.status_code, response.get_json()['code']), (503, 'CHANNEL_DISABLED'))
        self.assertEqual(VerificationChallenge.query.count(), 0)
