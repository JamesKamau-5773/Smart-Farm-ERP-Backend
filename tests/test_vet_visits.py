import json
from datetime import date

from app import db
from app.models.livestock import Cow
from app.models.user import Role
from tests.base import BaseTestCase


class VetVisitTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.vet = self.create_user(username='vet', password='password', role=Role.VET)
        self.farmer = self.create_user(username='farmer', password='password', role=Role.FARMER)
        self.cow = Cow(tag_number='COW-VET-001', date_of_birth=date(2022, 1, 1))
        db.session.add(self.cow)
        db.session.commit()

    def _login(self, username):
        return self.client.post(
            '/api/auth/login',
            data=json.dumps(dict(username=username, password='password')),
            content_type='application/json'
        )

    def test_log_vet_visit_and_schedule_follow_up(self):
        self._login('vet')

        with self.client:
            visit_response = self.client.post(
                '/api/clinical/vet-visits',
                data=json.dumps(
                    dict(
                        animal_id=self.cow.id,
                        visit_date='2026-05-26',
                        reason_for_visit='Lameness check',
                        diagnosis='Minor hoof inflammation',
                        medications=['Anti-inflammatory'],
                        recommendations='Rest for 3 days',
                        remarks='Monitor gait',
                        observations='Mild swelling',
                        follow_up_required=True,
                        follow_up_date='2026-05-31',
                    )
                ),
                content_type='application/json'
            )
            self.assertEqual(visit_response.status_code, 201)
            visit_data = json.loads(visit_response.data.decode())
            visit_id = visit_data['visit']['id']
            self.assertEqual(visit_data['visit']['follow_up_status'], 'Scheduled')

            pending_response = self.client.get('/api/clinical/vet-visits/follow-ups/pending')
            self.assertEqual(pending_response.status_code, 200)
            pending_data = json.loads(pending_response.data.decode())
            self.assertTrue(any(item['id'] == visit_id for item in pending_data))

    def test_complete_follow_up(self):
        self._login('vet')

        with self.client:
            visit_response = self.client.post(
                '/api/clinical/vet-visits',
                data=json.dumps(
                    dict(
                        animal_id=self.cow.id,
                        visit_date='2026-05-26',
                        reason_for_visit='Vaccination review',
                        diagnosis='Healthy',
                        follow_up_required=True,
                        follow_up_date='2026-06-02',
                    )
                ),
                content_type='application/json'
            )
            visit_id = json.loads(visit_response.data.decode())['visit']['id']

            complete_response = self.client.put(
                f'/api/clinical/vet-visits/{visit_id}/follow-up/complete',
                data=json.dumps(dict(follow_up_required=False)),
                content_type='application/json'
            )
            self.assertEqual(complete_response.status_code, 200)
            complete_data = json.loads(complete_response.data.decode())
            self.assertEqual(complete_data['visit']['follow_up_status'], 'Completed')
            self.assertIsNotNone(complete_data['visit']['follow_up_completed_at'])

    def test_update_medical_record_alias(self):
        self._login('vet')

        with self.client:
            create_response = self.client.post(
                '/api/medical/records',
                data=json.dumps(
                    {
                        'date': '2026-07-09',
                        'cow': self.cow.tag_number,
                        'reason': 'Routine check',
                        'diagnosis': 'initial',
                        'meds': ['vitamin'],
                    }
                ),
                content_type='application/json'
            )
            self.assertEqual(create_response.status_code, 201)
            visit_id = json.loads(create_response.data.decode())['visit']['id']

            update_response = self.client.put(
                f'/api/medical/records/{visit_id}',
                data=json.dumps(
                    {
                        'date': '2026-07-09',
                        'cow': '',
                        'reason': '',
                        'diagnosis': 'mastitis',
                        'meds': ['antibiotic'],
                        'recommendations': 'seclude milk for 3 days',
                        'status': 'Closed',
                        'severity': 'Medium',
                        'vet': '',
                        'followUp': '2026-07-13',
                        'updatedBy': '',
                    }
                ),
                content_type='application/json'
            )

            self.assertEqual(update_response.status_code, 200)
            payload = json.loads(update_response.data.decode())
            self.assertEqual(payload['visit']['diagnosis'], 'mastitis')
            self.assertEqual(payload['visit']['medications'], ['antibiotic'])
            self.assertEqual(payload['visit']['follow_up_date'], '2026-07-13')
            self.assertEqual(payload['visit']['reason_for_visit'], 'Routine check')
