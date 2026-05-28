import json
from tests.base import BaseTestCase
from app.models.user import Role
from app.models.livestock import Cow
from app.models.audit import AuditLog
from app import db
from datetime import date

class AuditTrailTestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.farmer = self.create_user(username='farmer', password='password', role=Role.FARMER)

        self.cow = Cow(tag_number='COW001', date_of_birth=date(2022, 1, 1))
        db.session.add(self.cow)
        db.session.commit()

    def _login(self, username, password):
        return self.client.post(
            '/api/auth/login',
            data=json.dumps(dict(username=username, password=password)),
            content_type='application/json'
        )

    def test_audit_log_for_hardlock(self):
        """Test if toggling hardlock creates an audit log entry."""
        self._login('farmer', 'password')
        with self.client:
            # Toggle hardlock
            self.client.put(
                f'/api/clinical/cows/{self.cow.id}/hardlock',
                data=json.dumps(dict(is_locked=True)),
                content_type='application/json'
            )

            # Check for audit log entry
            audit_log = AuditLog.query.filter_by(action='TOGGLE_HARDLOCK').first()
            self.assertIsNotNone(audit_log)
            self.assertEqual(audit_log.user_id, self.farmer.id)
            # the audit service records the domain as 'Livestock' for compatibility
            self.assertEqual(audit_log.entity_type, 'Livestock')
            self.assertEqual(audit_log.entity_id, self.cow.id)
            self.assertEqual(audit_log.old_value, 'False')
            self.assertEqual(audit_log.new_value, 'True')
