import io
import json
from datetime import date

from app import db
from app.models.livestock import AnimalTimelineEvent, BreedingLog, Cow, HeatObservation, SemenInventory
from app.models.supply import MilkLog, MilkSession
from app.models.user import Role
from tests.base import BaseTestCase


class BreedingTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.farmer = self.create_user(username='farmer', password='password', role=Role.FARMER)
        self.cow = Cow(tag_number='COWBR001', date_of_birth=date(2022, 1, 1))
        db.session.add(self.cow)
        db.session.commit()

    def _login(self):
        return self.client.post(
            '/api/auth/login',
            data=json.dumps(dict(username='farmer', password='password')),
            content_type='application/json'
        )

    def test_record_heat_observation_calculates_next_window_and_timeline(self):
        self._login()

        with self.client:
            response = self.client.post(
                '/api/v1/breeding/heat-observations',
                json={
                    'cow_id': self.cow.id,
                    'observed_at': '2026-08-28T06:30:00+03:00',
                    'intensity': 'high',
                    'signs': ['standing heat', 'clear mucus'],
                    'notes': 'Observed during morning check.',
                },
            )

        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        self.assertEqual(payload['next_window_start'], '2026-09-15')
        self.assertEqual(payload['next_window_end'], '2026-09-21')
        self.assertEqual(payload['intensity'], 'HIGH')

        observation = db.session.get(HeatObservation, payload['id'])
        self.assertEqual(observation.tenant_id, self.tenant.id)
        self.assertEqual(observation.signs, ['standing heat', 'clear mucus'])
        timeline = AnimalTimelineEvent.query.filter_by(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            event_type='heat_observation',
        ).first()
        self.assertIsNotNone(timeline)

    def test_list_heat_observations_is_tenant_and_cow_scoped(self):
        other_cow = Cow(
            tenant_id=self.tenant.id,
            tag_number='COWBR002',
            date_of_birth=date(2022, 2, 2),
        )
        other_tenant = self.create_tenant(name='Other Tenant')
        other_tenant_cow = Cow(
            tenant_id=other_tenant.id,
            tag_number='OTHER001',
            date_of_birth=date(2022, 3, 3),
        )
        db.session.add_all([other_cow, other_tenant_cow])
        db.session.flush()
        db.session.add_all([
            HeatObservation(
                tenant_id=self.tenant.id,
                cow_id=self.cow.id,
                observed_at='2026-08-28T06:30:00+00:00',
                intensity='MEDIUM',
                signs=['restlessness'],
                next_window_start=date(2026, 9, 15),
                next_window_end=date(2026, 9, 21),
            ),
            HeatObservation(
                tenant_id=self.tenant.id,
                cow_id=other_cow.id,
                observed_at='2026-08-27T06:30:00+00:00',
                intensity='LOW',
                signs=[],
                next_window_start=date(2026, 9, 14),
                next_window_end=date(2026, 9, 20),
            ),
            HeatObservation(
                tenant_id=other_tenant.id,
                cow_id=other_tenant_cow.id,
                observed_at='2026-08-26T06:30:00+00:00',
                intensity='HIGH',
                signs=['standing heat'],
                next_window_start=date(2026, 9, 13),
                next_window_end=date(2026, 9, 19),
            ),
        ])
        db.session.commit()
        self._login()

        with self.client:
            response = self.client.get(
                f'/api/v1/breeding/heat-observations?cow_id={self.cow.id}'
            )

        self.assertEqual(response.status_code, 200)
        items = response.get_json()['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['cow_id'], self.cow.id)

    def test_insemination_links_matching_heat_observation(self):
        self._login()
        with self.client:
            heat_response = self.client.post(
                '/api/v1/breeding/heat-observations',
                json={
                    'cow_id': self.cow.id,
                    'observed_at': '2026-08-28T06:30:00Z',
                    'signs': ['standing heat'],
                },
            )
            heat_id = heat_response.get_json()['id']
            semen_response = self.client.post(
                '/api/operations/semen-inventory',
                json={
                    'bull_name': 'BULL-HEAT',
                    'straw_code': 'HEAT-001',
                    'breed': 'Friesian',
                    'stock_level': 1,
                },
            )
            insemination_response = self.client.post(
                '/api/operations/breeding-logs',
                json={
                    'cow_id': self.cow.id,
                    'semen_id': semen_response.get_json()['id'],
                    'insemination_date': '2026-08-28',
                    'heat_observation_id': heat_id,
                },
            )

        self.assertEqual(insemination_response.status_code, 201)
        self.assertEqual(insemination_response.get_json()['heat_observation_id'], heat_id)
        observation = db.session.get(HeatObservation, heat_id)
        self.assertEqual(observation.breeding_log_id, insemination_response.get_json()['breeding_log_id'])

    def test_create_inventory_and_log_insemination(self):
        self._login()

        with self.client:
            inv_response = self.client.post(
                '/api/operations/semen-inventory',
                data=json.dumps(
                    dict(
                        bull_name='BULL-A',
                        straw_code='AI-STR-001',
                        breed='Friesian',
                        stock_level=3,
                        traits_to_improve=['Volume'],
                    )
                ),
                content_type='application/json'
            )
            self.assertEqual(inv_response.status_code, 201)
            inv_data = json.loads(inv_response.data.decode())
            semen_id = inv_data['id']

            log_response = self.client.post(
                '/api/operations/breeding-logs',
                data=json.dumps(
                    dict(
                        cow_id=self.cow.id,
                        semen_id=semen_id,
                        insemination_date='2026-05-20',
                    )
                ),
                content_type='application/json'
            )
            self.assertEqual(log_response.status_code, 201)
            log_data = json.loads(log_response.data.decode())
            self.assertIn('expected_calving_date', log_data)
            self.assertEqual(log_data['semen_source_label'], 'Farm Inventory')

    def test_update_breeding_status(self):
        self._login()

        with self.client:
            inv_response = self.client.post(
                '/api/operations/semen-inventory',
                data=json.dumps(dict(bull_name='BULL-B', straw_code='AI-STR-002', breed='Ayrshire', stock_level=2)),
                content_type='application/json'
            )
            semen_id = json.loads(inv_response.data.decode())['id']

            log_response = self.client.post(
                '/api/operations/breeding-logs',
                data=json.dumps(dict(cow_id=self.cow.id, semen_id=semen_id, insemination_date='2026-05-21')),
                content_type='application/json'
            )
            log_id = json.loads(log_response.data.decode())['breeding_log_id']

            update_response = self.client.put(
                f'/api/operations/breeding-logs/{log_id}/status',
                data=json.dumps(dict(status='Pregnant')),
                content_type='application/json'
            )
            self.assertEqual(update_response.status_code, 200)
            update_data = json.loads(update_response.data.decode())
            self.assertEqual(update_data['status'], 'Pregnant')

    def test_upload_certificate_and_pregnancy_check_milestone(self):
        self._login()

        with self.client:
            inv_response = self.client.post(
                '/api/operations/semen-inventory',
                data=json.dumps(dict(bull_name='BULL-CERT', straw_code='AI-STR-010', breed='Friesian', stock_level=2)),
                content_type='application/json'
            )
            semen_id = json.loads(inv_response.data.decode())['id']

            log_response = self.client.post(
                '/api/operations/breeding-logs',
                data=json.dumps(dict(
                    cow_id=self.cow.id,
                    semen_id=semen_id,
                    insemination_date='2026-05-20',
                    certificate_number='AI-8117',
                    technician_name='J.M. Ngotho',
                    service_fee=2500,
                )),
                content_type='application/json'
            )
            self.assertEqual(log_response.status_code, 201)
            payload = json.loads(log_response.data.decode())
            self.assertIn('pregnancy_check_date', payload)
            self.assertEqual(payload['certificate_number'], 'AI-8117')

            certificate_response = self.client.post(
                f'/api/operations/breeding-logs/{payload["breeding_log_id"]}/certificate',
                data={'file': (io.BytesIO(b'\xff\xd8\xff\xe0\x00\x10JFIF\x00fake-image-bytes'), 'ai-certificate.jpg')},
                content_type='multipart/form-data',
            )
            self.assertEqual(certificate_response.status_code, 200)
            certificate_payload = json.loads(certificate_response.data.decode())
            self.assertIn('certificate_image_url', certificate_payload)

    def test_upload_certificate_rejects_mismatched_file_content(self):
        self._login()
        log = BreedingLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            insemination_date=date(2026, 8, 31),
        )
        db.session.add(log)
        db.session.commit()
        with self.client:
            response = self.client.post(
                f'/api/operations/breeding-logs/{log.id}/certificate',
                data={'file': (io.BytesIO(b'not-an-image'), 'certificate.jpg')},
                content_type='multipart/form-data',
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn('does not match', response.get_json()['error'])

    def test_log_insemination_accepts_tag_and_straw_code_identifiers(self):
        self._login()

        with self.client:
            inv_response = self.client.post(
                '/api/operations/semen-inventory',
                data=json.dumps(
                    dict(
                        bull_name='BULL-D',
                        straw_code='FR-789',
                        breed='Friesian',
                        stock_level=2,
                    )
                ),
                content_type='application/json'
            )
            self.assertEqual(inv_response.status_code, 201)

            log_response = self.client.post(
                '/api/operations/breeding-logs',
                data=json.dumps(
                    dict(
                        cowId='COWBR001',
                        semen_id='FR-789',
                        inseminationDate='2026-05-25',
                    )
                ),
                content_type='application/json'
            )

            self.assertEqual(log_response.status_code, 201)
            log_data = json.loads(log_response.data.decode())
            self.assertIn('breeding_log_id', log_data)

    def test_log_insemination_falls_back_to_straw_code_when_numeric_like(self):
        self._login()

        with self.client:
            inv_response = self.client.post(
                '/api/operations/semen-inventory',
                data=json.dumps(
                    dict(
                        bull_name='BULL-E',
                        straw_code='56423',
                        breed='Friesian',
                        stock_level=1,
                    )
                ),
                content_type='application/json'
            )
            self.assertEqual(inv_response.status_code, 201)

            log_response = self.client.post(
                '/api/operations/breeding-logs',
                data=json.dumps(
                    dict(
                        cow_id='COWBR001',
                        semen_id='56423',
                        insemination_date='2026-05-26',
                    )
                ),
                content_type='application/json'
            )

            self.assertEqual(log_response.status_code, 201)
            log_data = json.loads(log_response.data.decode())
            self.assertIn('breeding_log_id', log_data)

    def test_log_insemination_accepts_cow_name_and_bull_name(self):
        self._login()

        with self.client:
            named_cow = Cow(tag_number='COWBR009', name='Bella', date_of_birth=date(2022, 2, 2))
            db.session.add(named_cow)
            db.session.commit()

            inv_response = self.client.post(
                '/api/operations/semen-inventory',
                data=json.dumps(
                    dict(
                        bull_name='Falcon Prime',
                        straw_code='AI-STR-999',
                        breed='Friesian',
                        stock_level=1,
                    )
                ),
                content_type='application/json'
            )
            self.assertEqual(inv_response.status_code, 201)

            log_response = self.client.post(
                '/api/operations/breeding-logs',
                data=json.dumps(
                    dict(
                        cow_id='Bella',
                        semen_id='Falcon Prime',
                        insemination_date='2026-05-27',
                    )
                ),
                content_type='application/json'
            )

            self.assertEqual(log_response.status_code, 201)
            log_data = json.loads(log_response.data.decode())
            self.assertIn('breeding_log_id', log_data)

    def test_log_insemination_allows_zero_stock(self):
        self._login()

        with self.client:
            inv_response = self.client.post(
                '/api/operations/semen-inventory',
                data=json.dumps(
                    dict(
                        bull_name='BULL-ZERO',
                        straw_code='AI-STR-000',
                        breed='Friesian',
                        stock_level=0,
                    )
                ),
                content_type='application/json'
            )
            self.assertEqual(inv_response.status_code, 201)
            semen_id = json.loads(inv_response.data.decode())['id']

            log_response = self.client.post(
                '/api/operations/breeding-logs',
                data=json.dumps(
                    dict(
                        cow_id=self.cow.id,
                        semen_id=semen_id,
                        insemination_date='2026-05-28',
                    )
                ),
                content_type='application/json'
            )

            self.assertEqual(log_response.status_code, 201)
            log_data = json.loads(log_response.data.decode())
            self.assertIn('breeding_log_id', log_data)
            self.assertEqual(log_data['stock_level_remaining'], 0)

    def test_log_insemination_allows_vet_provided_external_sire_code(self):
        self._login()

        with self.client:
            log_response = self.client.post(
                '/api/operations/breeding-logs',
                data=json.dumps(
                    dict(
                        cow_id=self.cow.id,
                        provided_by='VET',
                        external_sire_code='FR-234',
                        sire_pta_scores={'milk_volume': 28.5},
                        insemination_date='2026-05-29',
                    )
                ),
                content_type='application/json'
            )

            self.assertEqual(log_response.status_code, 201)
            payload = json.loads(log_response.data.decode())
            self.assertEqual(payload['provided_by'], 'VET')
            self.assertEqual(payload['semen_source_label'], 'Vet Provided')
            self.assertEqual(payload['external_sire_code'], 'FR-234')
            self.assertEqual(payload['sire_pta_scores'], {'milk_volume': 28.5})
            self.assertIsNone(payload['inventory_semen_id'])

            saved_log = db.session.get(BreedingLog, payload['breeding_log_id'])
            self.assertIsNotNone(saved_log)
            self.assertEqual(saved_log.provided_by, 'VET')
            self.assertEqual(saved_log.external_sire_code, 'FR-234')
            self.assertEqual(saved_log.sire_pta_scores, {'milk_volume': 28.5})
            self.assertIsNone(saved_log.inventory_semen_id)

            list_response = self.client.get('/api/operations/breeding-logs')
            self.assertEqual(list_response.status_code, 200)
            listed_log = next(item for item in list_response.get_json()['items'] if item['id'] == saved_log.id)
            self.assertEqual(listed_log['sire_pta_scores'], {'milk_volume': 28.5})

    def test_log_insemination_snapshots_farm_semen_pta_scores(self):
        semen = SemenInventory(
            tenant_id=self.tenant.id,
            bull_name='PTA BULL',
            straw_code='PTA-001',
            breed='Holstein',
            stock_level=1,
            traits_to_improve={'milk_volume': 32.0},
        )
        db.session.add(semen)
        db.session.commit()
        self._login()

        response = self.client.post('/api/operations/breeding-logs', json={
            'cow_id': self.cow.id,
            'provided_by': 'FARM',
            'semen_id': semen.id,
            'insemination_date': '2026-05-29',
        })

        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        self.assertEqual(payload['sire_pta_scores'], {'milk_volume': 32.0})
        saved_log = db.session.get(BreedingLog, payload['breeding_log_id'])
        self.assertEqual(saved_log.sire_pta_scores, {'milk_volume': 32.0})

    def test_log_insemination_accepts_frontend_vet_alias_payload(self):
        self._login()

        with self.client:
            log_response = self.client.post(
                '/api/operations/breeding-logs',
                data=json.dumps(
                    dict(
                        cow_id=self.cow.tag_number,
                        cowId=self.cow.tag_number,
                        semen_id='JY-4536',
                        semen_source='vet_provided',
                        semenSource='vet_provided',
                        sireCode='JY-4536',
                        aiDate='2026-06-02',
                    )
                ),
                content_type='application/json'
            )

            self.assertEqual(log_response.status_code, 201)
            payload = json.loads(log_response.data.decode())
            self.assertEqual(payload['provided_by'], 'VET')
            self.assertEqual(payload['external_sire_code'], 'JY-4536')
            self.assertIsNone(payload['inventory_semen_id'])

    def test_exact_patch_outcome_route_updates_livestock_status(self):
        self._login()

        with self.client:
            inv_response = self.client.post(
                '/api/operations/semen-inventory',
                data=json.dumps(dict(bull_name='BULL-C', straw_code='AI-STR-004', breed='Holstein', stock_level=1)),
                content_type='application/json'
            )
            semen_id = json.loads(inv_response.data.decode())['id']

            log_response = self.client.post(
                '/api/operations/breeding-logs',
                data=json.dumps(dict(cow_id=self.cow.id, semen_id=semen_id, insemination_date='2026-05-23')),
                content_type='application/json'
            )
            log_id = json.loads(log_response.data.decode())['breeding_log_id']

            outcome_response = self.client.patch(
                f'/api/v1/breeding/insemination/{log_id}/outcome',
                data=json.dumps(dict(status='Pregnant')),
                content_type='application/json'
            )
            self.assertEqual(outcome_response.status_code, 200)
            outcome_data = json.loads(outcome_response.data.decode())
            self.assertEqual(outcome_data['message'], 'Insemination marked as Pregnant')

            refreshed_cow = db.session.get(Cow, self.cow.id)
            self.assertEqual(refreshed_cow.current_status, 'Pregnant')

    def test_bull_performance_includes_butterfat(self):
        self._login()

        with self.client:
            inv_response = self.client.post(
                '/api/operations/semen-inventory',
                data=json.dumps(dict(bull_name='BULL-FAT', straw_code='AI-STR-003', breed='Jersey', stock_level=2)),
                content_type='application/json'
            )
            semen_id = json.loads(inv_response.data.decode())['id']

            log_response = self.client.post(
                '/api/operations/breeding-logs',
                data=json.dumps(dict(cow_id=self.cow.id, semen_id=semen_id, insemination_date='2026-05-22')),
                content_type='application/json'
            )
            log_id = json.loads(log_response.data.decode())['breeding_log_id']

            update_response = self.client.put(
                f'/api/operations/breeding-logs/{log_id}/status',
                data=json.dumps(dict(status='Pregnant')),
                content_type='application/json'
            )
            self.assertEqual(update_response.status_code, 200)

            milk_log = MilkLog(
                tenant_id=self.tenant.id,
                cow_id=self.cow.id,
                amount_liters=18.0,
                session=MilkSession.MORNING,
                recorded_by=self.farmer.id,
                butterfat_pct=4.8,
                is_saleable=True,
                anomaly_flag=False,
            )
            db.session.add(milk_log)
            db.session.commit()

            perf_response = self.client.get('/api/operations/breeding/performance')
            self.assertEqual(perf_response.status_code, 200)
            perf_data = json.loads(perf_response.data.decode())
            summary = perf_data['summary']
            self.assertTrue(any(item['avg_butterfat_pct_for_pregnant_progeny'] is not None for item in summary))
