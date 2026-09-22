import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from tests.base import BaseTestCase
from app.models.user import Role
from app.models.genetics import GeneticProfile, GeneticTraitDefinition, GeneticTraitScore
from app.models.livestock import Cow, BreedingLog, SemenInventory, MedicalRecord, LactationCycle
from app.models.supply import MilkDropAlert, MilkLog
from app import db
from flask_jwt_extended import create_access_token

class OperationsTestCase(BaseTestCase):

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

    def test_record_milk_production(self):
        """Test recording milk production."""
        self._login('farmer', 'password')
        with self.client:
            response = self.client.post(
                f'/api/operations/cows/{self.cow.id}/milk',
                data=json.dumps(dict(
                    amount=20.5,
                    session='Morning'
                )),
                content_type='application/json'
            )
            self.assertEqual(response.status_code, 201)
            data = json.loads(response.data.decode())
            self.assertEqual(data['message'], 'Milk logged successfully.')
            self.assertEqual(data['cow_id'], self.cow.id)
            self.assertEqual(data['amount'], 20.5)
            self.assertEqual(data['session'], 'Morning')
            self.assertIn('milkingDate', data)
            self.assertIn('status', data)

    def test_record_milk_production_accepts_cow_tag(self):
        self._login('farmer', 'password')

        with self.client:
            response = self.client.post(
                '/api/production/yield',
                data=json.dumps({
                    'cow_id': self.cow.tag_number,
                    'amount': 6.6,
                    'session': 'morning',
                    'milking_date': '2026-08-26',
                }),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['cow_id'], self.cow.id)
        self.assertEqual(payload['amount'], 6.6)
        self.assertEqual(payload['milkingDate'], '2026-08-26')

    def test_replays_idempotent_milk_write_without_duplicate(self):
        self._login('farmer', 'password')
        headers = {
            'Content-Type': 'application/json',
            'Idempotency-Key': 'offline:test-milk-write',
        }
        payload = {
            'cow_id': self.cow.tag_number,
            'amount': 6.6,
            'session': 'morning',
            'milking_date': '2026-08-26',
        }

        first = self.client.post('/api/production/yield', json=payload, headers=headers)
        replay = self.client.post('/api/production/yield', json=payload, headers=headers)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay.headers.get('Idempotency-Replayed'), 'true')
        self.assertEqual(first.get_json(), replay.get_json())
        self.assertEqual(MilkLog.query.count(), 1)

    def test_canonical_herd_alias_route(self):
        """Canonical frontend path should work without /api/operations/api duplication."""
        self._login('farmer', 'password')
        with self.client:
            response = self.client.get('/api/herd')
            self.assertEqual(response.status_code, 200)
            payload = json.loads(response.data.decode())
            self.assertIn('items', payload)
            self.assertIn('meta', payload)

    def test_genetic_progress_compares_daughter_and_dam_milk_volume_traits(self):
        trait = GeneticTraitDefinition(
            name='milk_volume',
            display_name='Milk Volume',
            category='Production',
            unit='liters/day',
        )
        dam = Cow(
            tenant_id=self.tenant.id,
            tag_number='DAM001',
            date_of_birth=date(2020, 1, 1),
            genetic_score=99,
        )
        db.session.add_all([trait, dam])
        db.session.flush()

        daughters = [
            Cow(
                tenant_id=self.tenant.id,
                tag_number='DAU001',
                date_of_birth=date(2025, 2, 1),
                dam_id=dam.id,
                genetic_score=1,
            ),
            Cow(
                tenant_id=self.tenant.id,
                tag_number='DAU002',
                date_of_birth=date(2025, 8, 1),
                dam_id=dam.id,
                genetic_score=2,
            ),
        ]
        db.session.add_all(daughters)
        db.session.flush()

        profiles = [
            GeneticProfile(cow_id=dam.id, tenant_id=self.tenant.id, source='MANUAL'),
            GeneticProfile(cow_id=daughters[0].id, tenant_id=self.tenant.id, source='PROJECTED'),
            GeneticProfile(cow_id=daughters[1].id, tenant_id=self.tenant.id, source='PROJECTED'),
        ]
        db.session.add_all(profiles)
        db.session.flush()
        db.session.add_all([
            GeneticTraitScore(profile_id=profiles[0].id, trait_definition_id=trait.id, value=20),
            GeneticTraitScore(profile_id=profiles[1].id, trait_definition_id=trait.id, value=24),
            GeneticTraitScore(profile_id=profiles[2].id, trait_definition_id=trait.id, value=26),
        ])
        db.session.commit()

        self._login('farmer', 'password')
        response = self.client.get('/api/herd/genetic-progress')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['items'], [{
            'year': 2025,
            'daughters_yield': 25.0,
            'mothers_yield': 20.0,
            'sample_size': 2,
        }])
        self.assertEqual(payload['meta']['trait'], 'milk_volume')
        self.assertEqual(payload['meta']['pair_count'], 2)

    def test_milk_drop_alert_includes_cow_identity_and_can_be_resolved(self):
        self.cow.name = 'Malaika'
        alert = MilkDropAlert(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            alert_date=date(2026, 9, 14),
            missing_milk_liters=Decimal('3.00'),
            status='INVESTIGATING',
            reason='Yield below target',
        )
        db.session.add(alert)
        db.session.commit()
        self._login('farmer', 'password')

        with self.client:
            list_response = self.client.get('/api/production/milk-drop-alerts')
            self.assertEqual(list_response.status_code, 200)
            listed_alert = list_response.get_json()['items'][0]
            self.assertEqual(listed_alert['cow_name'], 'Malaika')
            self.assertEqual(listed_alert['cow_tag'], 'COW001')

            close_response = self.client.post(
                f'/api/production/milk-drop-alerts/{alert.id}/investigate',
                json={
                    'status': 'RESOLVED',
                    'selected_reasons': ['Not enough feed given'],
                    'notes': 'Feed ration corrected.',
                },
            )

        self.assertEqual(close_response.status_code, 200)
        self.assertEqual(close_response.get_json()['status'], 'RESOLVED')
        db.session.refresh(alert)
        self.assertEqual(alert.status, 'RESOLVED')
        self.assertEqual(alert.investigation_notes, 'Feed ration corrected.')
        self.assertEqual(alert.selected_reasons, ['Not enough feed given'])

    def test_herd_list_includes_persisted_timestamps(self):
        self._login('farmer', 'password')

        with self.client:
            response = self.client.get('/api/herd')
            self.assertEqual(response.status_code, 200)
            payload = json.loads(response.data.decode())
            self.assertGreaterEqual(len(payload['items']), 1)
            animal = payload['items'][0]
            self.assertIn('createdAt', animal)
            self.assertIn('updatedAt', animal)
            self.assertIsNotNone(animal['createdAt'])
            self.assertIsNotNone(animal['updatedAt'])

    def test_create_herd_member_accepts_frontend_aliases(self):
        """Frontend payloads using id/dob should still create a herd member."""
        self._login('farmer', 'password')

        with self.client:
            response = self.client.post(
                '/api/herd',
                data=json.dumps({
                    'id': 'C-001',
                    'name': 'Ruby',
                    'breed': 'Freshian',
                    'dob': '2026-06-17',
                    'hasCalved': False,
                }),
                content_type='application/json',
            )

            self.assertEqual(response.status_code, 201)
            payload = json.loads(response.data.decode())
            self.assertEqual(payload['tag_number'], 'C-001')
            self.assertEqual(payload['date_of_birth'], '2026-06-17')
            self.assertEqual(payload['tag'], 'C-001')

    def test_animal_milk_history_returns_animal_scoped_shape(self):
        self._login('farmer', 'password')
        db.session.add_all([
            MilkLog(
                tenant_id=self.tenant.id,
                cow_id=self.cow.id,
                amount_liters=14.0,
                session='Morning',
                recorded_by=self.farmer.id,
            ),
            MilkLog(
                tenant_id=self.tenant.id,
                cow_id=self.cow.id,
                amount_liters=6.0,
                session='Evening',
                recorded_by=self.farmer.id,
            ),
        ])
        db.session.commit()

        with self.client:
            response = self.client.get(f'/api/animals/{self.cow.id}/milk-history')
            self.assertEqual(response.status_code, 200)
            payload = json.loads(response.data.decode())
            self.assertIn('animal', payload)
            self.assertIn('sessions', payload)
            self.assertEqual(payload['animal']['id'], self.cow.id)
            self.assertEqual(len(payload['sessions']), 2)
            self.assertIn('amount', payload['sessions'][0])
            self.assertIn('milkingDate', payload['sessions'][0])
            self.assertIn('status', payload['sessions'][0])
            self.assertIn('summary', payload)
            self.assertEqual(payload['summary']['session_count'], 2)
            self.assertAlmostEqual(payload['summary']['total_logged'], 20.0)
            self.assertAlmostEqual(payload['summary']['average_yield'], 20.0)
            self.assertAlmostEqual(payload['summary']['peak_yield'], 20.0)

    def test_animal_summary_includes_recent_daily_yield_metrics(self):
        today = date.today()
        db.session.add_all([
            MilkLog(
                tenant_id=self.tenant.id,
                cow_id=self.cow.id,
                amount_liters=Decimal('6.50'),
                session='Morning',
                recorded_by=self.farmer.id,
                timestamp=datetime.combine(today - timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc),
            ),
            MilkLog(
                tenant_id=self.tenant.id,
                cow_id=self.cow.id,
                amount_liters=Decimal('5.00'),
                session='Evening',
                recorded_by=self.farmer.id,
                timestamp=datetime.combine(today - timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=15),
            ),
            MilkLog(
                tenant_id=self.tenant.id,
                cow_id=self.cow.id,
                amount_liters=Decimal('7.00'),
                session='Morning',
                recorded_by=self.farmer.id,
                timestamp=datetime.combine(today - timedelta(days=2), datetime.min.time(), tzinfo=timezone.utc),
            ),
        ])
        db.session.commit()

        self._login('farmer', 'password')
        with self.client:
            response = self.client.get(f'/api/animals/{self.cow.id}')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['yesterday_yield_liters'], 11.5)
        self.assertAlmostEqual(payload['seven_day_average_liters'], 18.5 / 7, places=2)

    def test_animal_summary_uses_lactation_cycle_for_days_in_milk(self):
        self.cow.status = 'Lactating'
        db.session.add(LactationCycle(
            cow_id=self.cow.id,
            cycle_number=1,
            actual_calving_date=date.today() - timedelta(days=42),
            is_active=True,
        ))
        db.session.commit()

        self._login('farmer', 'password')
        with self.client:
            response = self.client.get(f'/api/animals/{self.cow.id}')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['current_status'], 'Lactating')
        self.assertEqual(payload['days_in_milk'], 42)

    def test_animal_milk_history_end_date_includes_whole_day(self):
        self._login('farmer', 'password')

        db.session.add_all([
            MilkLog(
                tenant_id=self.tenant.id,
                cow_id=self.cow.id,
                amount_liters=8.0,
                session='Morning',
                recorded_by=self.farmer.id,
                timestamp=datetime(2026, 7, 2, 6, 0, tzinfo=timezone.utc),
            ),
            MilkLog(
                tenant_id=self.tenant.id,
                cow_id=self.cow.id,
                amount_liters=7.0,
                session='Evening',
                recorded_by=self.farmer.id,
                timestamp=datetime(2026, 7, 2, 18, 0, tzinfo=timezone.utc),
            ),
        ])
        db.session.commit()

        with self.client:
            response = self.client.get(
                f'/api/animals/{self.cow.id}/milk-history?end_date=2026-07-02'
            )
            self.assertEqual(response.status_code, 200)
            payload = json.loads(response.data.decode())
            self.assertEqual(payload['summary']['session_count'], 2)
            self.assertAlmostEqual(payload['summary']['total_logged'], 15.0)
            self.assertAlmostEqual(payload['summary']['average_yield'], 15.0)
            self.assertAlmostEqual(payload['summary']['peak_yield'], 15.0)

    def test_patch_production_yield_updates_amount_and_session(self):
        self._login('farmer', 'password')
        with self.client:
            create_resp = self.client.post(
                '/api/production/yield',
                data=json.dumps({
                    'cow_id': self.cow.id,
                    'amount': 12.0,
                    'session': 'Morning',
                }),
                content_type='application/json',
            )
            self.assertEqual(create_resp.status_code, 201)
            created_payload = json.loads(create_resp.data.decode())
            log_id = created_payload['id']

            patch_resp = self.client.patch(
                f'/api/production/yield/{log_id}',
                data=json.dumps({
                    'amount': 16.5,
                    'session': 'Evening',
                }),
                content_type='application/json',
            )
            self.assertEqual(patch_resp.status_code, 200)
            patched = json.loads(patch_resp.data.decode())
            self.assertEqual(patched['id'], log_id)
            self.assertEqual(patched['amount'], 16.5)
            self.assertEqual(patched['session'], 'Evening')

    def test_delete_production_yield_is_idempotent(self):
        self._login('farmer', 'password')
        log = MilkLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            amount_liters=12.0,
            session='Morning',
            recorded_by=self.farmer.id,
        )
        db.session.add(log)
        db.session.commit()
        log_id = log.id

        with self.client:
            first_response = self.client.delete(f'/api/production/yield/{log_id}')
            second_response = self.client.delete(f'/api/production/yield/{log_id}')

        self.assertEqual(first_response.status_code, 200)
        self.assertFalse(json.loads(first_response.data.decode())['already_deleted'])
        self.assertEqual(second_response.status_code, 200)
        self.assertTrue(json.loads(second_response.data.decode())['already_deleted'])
        self.assertIsNone(MilkLog.query.filter_by(id=log_id).first())

    def test_production_history_route_alias_returns_animal_scoped_payload(self):
        self._login('farmer', 'password')
        with self.client:
            response = self.client.get(f'/api/production/history/{self.cow.id}')
            self.assertEqual(response.status_code, 200)
            payload = json.loads(response.data.decode())
            self.assertIn('animal', payload)
            self.assertIn('sessions', payload)

    def test_production_yield_list_returns_summary(self):
        self._login('farmer', 'password')
        db.session.add_all([
            MilkLog(
                tenant_id=self.tenant.id,
                cow_id=self.cow.id,
                amount_liters=10.0,
                session='Morning',
                recorded_by=self.farmer.id,
                is_saleable=True,
                anomaly_flag=False,
            ),
            MilkLog(
                tenant_id=self.tenant.id,
                cow_id=self.cow.id,
                amount_liters=4.0,
                session='Evening',
                recorded_by=self.farmer.id,
                is_saleable=False,
                anomaly_flag=True,
            ),
        ])
        db.session.commit()

        with self.client:
            response = self.client.get('/api/production/yield')
            self.assertEqual(response.status_code, 200)
            payload = json.loads(response.data.decode())
            self.assertIn('summary', payload)
            self.assertEqual(payload['summary']['total_records'], 2)
            self.assertEqual(payload['summary']['recorded_count'], 1)
            self.assertEqual(payload['summary']['isolated_count'], 0)
            self.assertEqual(payload['summary']['flagged_count'], 1)
            self.assertAlmostEqual(payload['summary']['total_volume'], 14.0)
            self.assertEqual(payload['summary']['verified_count'], 1)
            self.assertEqual(payload['summary']['pending_count'], 0)
            self.assertEqual(payload['summary']['verifiedEntries'], 1)
            self.assertEqual(payload['summary']['pendingEntries'], 0)
            self.assertEqual(payload['summary']['flaggedEntries'], 1)
            self.assertAlmostEqual(payload['summary']['totalVolume'], 14.0)

    def test_admin_can_verify_production_yield(self):
        admin = self.create_user(username='admin', password='password', role=Role.ADMIN)
        log = MilkLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            amount_liters=11.0,
            session='Morning',
            recorded_by=self.farmer.id,
            status=MilkLog.STATUS_RECORDED,
            is_saleable=True,
            anomaly_flag=False,
        )
        db.session.add(log)
        db.session.commit()

        token = create_access_token(
            identity=str(admin.id),
            additional_claims={'role': Role.ADMIN, 'tenant_id': self.tenant.id, 'farm_id': self.farm.id},
        )

        response = self.client.patch(
            f'/api/production/yield/{log.id}/verify',
            headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['id'], log.id)
        self.assertEqual(payload['log_id'], log.id)
        self.assertEqual(payload['status'], 'VERIFIED')
        self.assertEqual(payload['verified_by'], admin.id)
        self.assertIsNotNone(payload['verified_at'])

        db.session.refresh(log)
        self.assertEqual(log.status, MilkLog.STATUS_VERIFIED)
        self.assertEqual(log.verified_by, admin.id)
        self.assertIsNotNone(log.verified_at)

    def test_farm_manager_can_verify_production_yield(self):
        manager = self.create_user(username='manager', password='password', role=Role.FARM_MANAGER)
        log = MilkLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            amount_liters=8.0,
            session='Morning',
            recorded_by=self.farmer.id,
            status=MilkLog.STATUS_RECORDED,
            is_saleable=True,
            anomaly_flag=False,
        )
        db.session.add(log)
        db.session.commit()

        token = create_access_token(
            identity=str(manager.id),
            additional_claims={'role': Role.FARM_MANAGER, 'tenant_id': self.tenant.id, 'farm_id': self.farm.id},
        )

        response = self.client.patch(
            f'/api/production/yield/{log.id}/verify',
            headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['status'], MilkLog.STATUS_VERIFIED)
        self.assertEqual(payload['verified_by'], manager.id)

    def test_verify_production_yield_is_idempotent(self):
        admin = self.create_user(username='admin2', password='password', role=Role.ADMIN)
        verified_at = datetime(2026, 7, 9, 8, 30, tzinfo=timezone.utc)
        log = MilkLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            amount_liters=9.5,
            session='Evening',
            recorded_by=self.farmer.id,
            status=MilkLog.STATUS_VERIFIED,
            is_saleable=True,
            anomaly_flag=False,
            verified_by=admin.id,
            verified_at=verified_at,
        )
        db.session.add(log)
        db.session.commit()

        token = create_access_token(
            identity=str(admin.id),
            additional_claims={'role': Role.ADMIN, 'tenant_id': self.tenant.id, 'farm_id': self.farm.id},
        )

        response = self.client.patch(
            f'/api/production/yield/{log.id}/verify',
            headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data.decode())
        self.assertEqual(payload['status'], 'VERIFIED')
        self.assertEqual(payload['verified_by'], admin.id)
        self.assertEqual(
            datetime.fromisoformat(payload['verified_at']).astimezone(timezone.utc),
            verified_at,
        )

    def test_farmer_can_verify_production_yield(self):
        self._login('farmer', 'password')
        log = MilkLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            amount_liters=13.0,
            session='Morning',
            recorded_by=self.farmer.id,
            status=MilkLog.STATUS_RECORDED,
            is_saleable=True,
            anomaly_flag=False,
        )
        db.session.add(log)
        db.session.commit()

        with self.client:
            response = self.client.patch(f'/api/production/yield/{log.id}/verify')
            self.assertEqual(response.status_code, 200)
            payload = json.loads(response.data.decode())
            self.assertEqual(payload['status'], MilkLog.STATUS_VERIFIED)
            self.assertEqual(payload['verified_by'], self.farmer.id)

            db.session.refresh(log)
            self.assertEqual(log.status, MilkLog.STATUS_VERIFIED)
            self.assertEqual(log.verified_by, self.farmer.id)

    def test_verify_production_yield_respects_tenant_scope(self):
        other_tenant = self.create_tenant(name='Other Tenant')
        other_farm = self.create_farm(tenant=other_tenant, name='Other Farm')
        other_admin = self.create_user(username='otheradmin', password='password', role=Role.ADMIN, tenant=other_tenant)

        log = MilkLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            amount_liters=7.0,
            session='Morning',
            recorded_by=self.farmer.id,
            status=MilkLog.STATUS_RECORDED,
            is_saleable=True,
            anomaly_flag=False,
        )
        db.session.add(log)
        db.session.commit()

        token = create_access_token(
            identity=str(other_admin.id),
            additional_claims={'role': Role.ADMIN, 'tenant_id': other_tenant.id, 'farm_id': other_farm.id},
        )

        response = self.client.patch(
            f'/api/production/yield/{log.id}/verify',
            headers={'Authorization': f'Bearer {token}'},
        )
        self.assertEqual(response.status_code, 404)

    def test_log_daily_yield_persists_flagged_status(self):
        self._login('farmer', 'password')
        existing = MilkLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            amount_liters=20.0,
            session='Morning',
            recorded_by=self.farmer.id,
            status=MilkLog.STATUS_RECORDED,
            is_saleable=True,
            anomaly_flag=False,
        )
        db.session.add(existing)
        db.session.commit()

        with self.client:
            response = self.client.post(
                f'/api/operations/cows/{self.cow.id}/milk',
                data=json.dumps({'amount': 10.0, 'session': 'Evening'}),
                content_type='application/json',
            )
            self.assertEqual(response.status_code, 201)
            payload = json.loads(response.data.decode())
            self.assertEqual(payload['status'], MilkLog.STATUS_FLAGGED)

        created = MilkLog.query.order_by(MilkLog.id.desc()).first()
        self.assertEqual(created.status, MilkLog.STATUS_FLAGGED)

    def test_herd_list_returns_summary(self):
        self._login('farmer', 'password')

        self.cow.current_status = 'Lactating'
        second_cow = Cow(
            tenant_id=self.tenant.id,
            tag_number='COW002',
            date_of_birth=date(2021, 1, 1),
            current_status='Dry',
        )
        db.session.add(second_cow)
        db.session.flush()

        cycle = LactationCycle(
            cow_id=self.cow.id,
            cycle_number=1,
            actual_calving_date=date(2026, 1, 15),
            is_active=True,
        )
        db.session.add(cycle)
        db.session.commit()

        with self.client:
            response = self.client.get('/api/herd')
            self.assertEqual(response.status_code, 200)
            payload = json.loads(response.data.decode())
            self.assertIn('summary', payload)
            self.assertEqual(payload['summary']['total_count'], 2)
            self.assertEqual(payload['summary']['milking_count'], 1)
            self.assertEqual(payload['summary']['dry_count'], 1)
            self.assertEqual(payload['summary']['latest_calved'], '2026-01-15')

    def test_herd_list_exposes_backend_days_open(self):
        self._login('farmer', 'password')

        cycle = LactationCycle(
            cow_id=self.cow.id,
            cycle_number=1,
            actual_calving_date=date(2026, 1, 15),
            is_active=True,
        )
        db.session.add(cycle)
        db.session.add(BreedingLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            insemination_date=date(2026, 2, 15),
            status='Pregnant',
        ))
        db.session.commit()

        with self.client:
            response = self.client.get('/api/herd')
            self.assertEqual(response.status_code, 200)
            payload = json.loads(response.data.decode())
            animal = payload['items'][0]
            self.assertIn('days_open', animal)
            self.assertEqual(animal['days_open'], 31)

    def test_midday_session_is_accepted_for_milk_logging(self):
        self._login('farmer', 'password')

        with self.client:
            response = self.client.post(
                f'/api/operations/cows/{self.cow.id}/milk',
                data=json.dumps(dict(amount=12.5, session='Midday')),
                content_type='application/json',
            )
            self.assertEqual(response.status_code, 201)
            payload = json.loads(response.data.decode())
            self.assertEqual(payload['session'], 'Midday')

    def test_animal_timeline_events_can_be_saved_and_listed(self):
        self._login('farmer', 'password')

        with self.client:
            create_resp = self.client.post(
                f'/api/operations/api/animals/{self.cow.id}/events',
                data=json.dumps({
                    'event_type': 'vaccination',
                    'title': 'Vaccination administered',
                    'description': 'Annual FMD vaccine given.',
                    'event_date': '2026-07-02T08:30:00+00:00',
                    'event_data': {'product': 'FMD', 'batch': 'B-100'},
                }),
                content_type='application/json',
            )
            self.assertEqual(create_resp.status_code, 201)
            created = json.loads(create_resp.data.decode())
            self.assertEqual(created['cow_id'], self.cow.id)
            self.assertEqual(created['event_type'], 'vaccination')
            self.assertEqual(created['title'], 'Vaccination administered')

            list_resp = self.client.get(f'/api/operations/api/animals/{self.cow.id}/events')
            self.assertEqual(list_resp.status_code, 200)
            payload = json.loads(list_resp.data.decode())
            self.assertIn('items', payload)
            self.assertEqual(len(payload['items']), 1)
            self.assertEqual(payload['items'][0]['title'], 'Vaccination administered')

    def test_export_animal_passport_pdf(self):
        """Test exporting a cow passport as a PDF."""
        vet = self.create_user(username='vet', password='password', role=Role.VET)

        semen = SemenInventory(
            tenant_id=self.tenant.id,
            bull_name='Jivu Prime',
            straw_code='STRAW-001',
            breed='Friesian',
            provider='Farm Genetics',
            stock_level=3,
        )
        db.session.add(semen)
        db.session.flush()

        db.session.add_all([
            MilkLog(
                tenant_id=self.tenant.id,
                cow_id=self.cow.id,
                amount_liters=18.25,
                session='Morning',
                recorded_by=self.farmer.id,
                timestamp=datetime(2026, 5, 20, 6, 30, 0),
            ),
            MedicalRecord(
                cow_id=self.cow.id,
                vet_id=vet.id,
                visit_date=datetime(2026, 5, 18, 10, 15, 0),
                diagnosis='Mild mastitis',
                medication='Oxytetracycline',
                withdrawal_days_recommended=3,
                remarks='Improving after treatment.',
            ),
            BreedingLog(
                tenant_id=self.tenant.id,
                cow_id=self.cow.id,
                inventory_semen_id=semen.id,
                insemination_date=date(2026, 5, 1),
                expected_calving_date=date(2027, 2, 5),
                status='Pregnant',
            ),
        ])
        db.session.commit()

        self._login('farmer', 'password')
        with self.client:
            response = self.client.get(f'/api/v1/export/animal/{self.cow.id}/pdf')

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'application/pdf')
            self.assertIn('attachment', response.headers.get('Content-Disposition', ''))
            self.assertTrue(response.data.startswith(b'%PDF'))
