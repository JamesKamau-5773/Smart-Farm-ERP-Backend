from __future__ import annotations

import json
from datetime import date, datetime, timezone

from app import db
from app.models.enums import CowStatus
from app.models.genetics import GeneticProfile, GeneticTraitDefinition, GeneticTraitScore
from app.models.livestock import AnimalTimelineEvent, BreedingLog, Cow, LactationCycle, SemenInventory
from app.models.user import Role
from tests.base import BaseTestCase


class CalvingTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.farmer = self.create_user(username='calving_farmer', password='password', role=Role.FARMER)
        self.cow = Cow(
            tenant_id=self.tenant.id,
            tag_number='MOTHER001',
            name='Daisy',
            date_of_birth=date(2021, 1, 1),
            status=CowStatus.HEIFER,
            pregnancy_status='Pregnant',
            due_date=date(2026, 9, 15),
        )
        db.session.add(self.cow)
        db.session.commit()

    def _login(self):
        return self.client.post(
            '/api/auth/login',
            data=json.dumps(dict(username='calving_farmer', password='password')),
            content_type='application/json',
        )

    def test_record_calving_updates_mother_lactation_and_timeline(self):
        self._login()

        with self.client:
            response = self.client.post(
                f'/api/animals/{self.cow.id}/calving',
                json={
                    'calving_date': '2026-09-12',
                    'calf_sex': 'Female',
                    'calf_tag': 'CALF001',
                    'calf_name': 'Bella',
                    'birth_weight': 36.5,
                    'delivery_outcome': 'Live Birth',
                    'calving_ease': 'Unassisted',
                    'notes': 'Healthy delivery in morning.',
                },
            )

        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        self.assertIn('mother', payload)
        self.assertEqual(payload['mother']['status'], 'Lactating')
        self.assertEqual(payload['mother']['current_status'], 'Lactating')
        self.assertEqual(payload['mother']['last_calving_date'], '2026-09-12')
        self.assertEqual(payload['mother']['last_calved'], '2026-09-12')
        self.assertEqual(payload['mother']['pregnancy_status'], 'Open')
        self.assertIsNone(payload['mother']['due_date'])

        # Check mother in DB
        db.session.refresh(self.cow)
        self.assertEqual(self.cow.status, 'Lactating')
        self.assertEqual(self.cow.last_calving_date, date(2026, 9, 12))
        self.assertEqual(self.cow.pregnancy_status, 'Open')
        self.assertIsNone(self.cow.due_date)

        # Check LactationCycle created
        cycle = LactationCycle.query.filter_by(cow_id=self.cow.id, is_active=True).first()
        self.assertIsNotNone(cycle)
        self.assertEqual(cycle.actual_calving_date, date(2026, 9, 12))
        self.assertEqual(cycle.cycle_number, 1)

        # Check Calf created in herd
        calf = Cow.query.filter_by(tenant_id=self.tenant.id, tag_number='CALF001').first()
        self.assertIsNotNone(calf)
        self.assertEqual(calf.name, 'Bella')
        self.assertEqual(calf.dam_id, self.cow.id)
        self.assertEqual(calf.date_of_birth, date(2026, 9, 12))
        self.assertEqual(calf.status, 'Calf')
        self.assertEqual(float(calf.birth_weight_kg), 36.5)
        self.assertEqual(payload['calf']['birth_weight_kg'], 36.5)

        # Check Mother timeline event
        mother_events = AnimalTimelineEvent.query.filter_by(
            tenant_id=self.tenant.id, cow_id=self.cow.id, event_type='calving'
        ).all()
        self.assertEqual(len(mother_events), 1)
        self.assertEqual(mother_events[0].event_data.get('calf_tag'), 'CALF001')
        self.assertEqual(mother_events[0].event_data.get('birth_weight_kg'), 36.5)

        # Check Calf timeline birth event
        calf_events = AnimalTimelineEvent.query.filter_by(
            tenant_id=self.tenant.id, cow_id=calf.id, event_type='birth'
        ).all()
        self.assertEqual(len(calf_events), 1)
        self.assertEqual(calf_events[0].event_data.get('dam_id'), self.cow.id)

    def test_record_calving_updates_pregnant_breeding_log_to_calved(self):
        # Create Semen and BreedingLog for the cow
        semen = SemenInventory(
            tenant_id=self.tenant.id,
            bull_name='SUPER-SIRE',
            straw_code='STR-999',
            breed='Holstein',
            stock_level=5,
            traits_to_improve={'milk_volume': 400.0},
        )
        db.session.add(semen)
        db.session.flush()

        breeding_log = BreedingLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            inventory_semen_id=semen.id,
            provided_by='FARM',
            insemination_date=date(2025, 12, 1),
            expected_calving_date=date(2026, 9, 10),
            status='Pregnant',
        )
        db.session.add(breeding_log)
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.post(
                f'/api/animals/{self.cow.id}/calving',
                json={
                    'calving_date': '2026-09-10',
                    'calf_sex': 'Male',
                    'calf_tag': 'BULLCALF01',
                    'delivery_outcome': 'Live Birth',
                    'calving_ease': 'Normal',
                },
            )

        self.assertEqual(response.status_code, 201)
        db.session.refresh(breeding_log)
        self.assertEqual(breeding_log.status, 'Calved')

        # Check calf sire_name assigned from semen inventory bull name
        calf = Cow.query.filter_by(tenant_id=self.tenant.id, tag_number='BULLCALF01').first()
        self.assertIsNotNone(calf)
        self.assertEqual(calf.sire_name, 'SUPER-SIRE')

    def test_vet_semen_snapshot_projects_calf_traits_at_calving(self):
        trait = GeneticTraitDefinition(
            name='milk_volume',
            display_name='Milk Volume',
            category='Production',
            unit='liters/day',
        )
        dam_profile = GeneticProfile(
            cow_id=self.cow.id,
            tenant_id=self.tenant.id,
            source=GeneticProfile.SOURCE_MANUAL,
        )
        db.session.add_all([trait, dam_profile])
        db.session.flush()
        db.session.add(GeneticTraitScore(
            profile_id=dam_profile.id,
            trait_definition_id=trait.id,
            value=20.0,
            reliability=50,
        ))
        db.session.add(BreedingLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            provided_by='VET',
            external_sire_code='VET-PTA-01',
            sire_pta_scores={'milk_volume': 30.0},
            insemination_date=date(2025, 12, 1),
            expected_calving_date=date(2026, 9, 10),
            status='Pregnant',
        ))
        db.session.commit()

        self._login()
        response = self.client.post(f'/api/animals/{self.cow.id}/calving', json={
            'calving_date': '2026-09-10',
            'calf_tag': 'VETCALF01',
            'calf_sex': 'Female',
            'delivery_outcome': 'Live Birth',
        })

        self.assertEqual(response.status_code, 201)
        calf = Cow.query.filter_by(tenant_id=self.tenant.id, tag_number='VETCALF01').one()
        calf_profile = GeneticProfile.query.filter_by(cow_id=calf.id).one()
        milk_score = GeneticTraitScore.query.filter_by(
            profile_id=calf_profile.id,
            trait_definition_id=trait.id,
        ).one()
        self.assertEqual(float(milk_score.value), 25.0)
        self.assertEqual(milk_score.scored_source, GeneticTraitScore.SCORED_SOURCE_SYSTEM)

    def test_record_calving_stillborn_does_not_create_active_calf(self):
        self._login()

        with self.client:
            response = self.client.post(
                f'/api/animals/{self.cow.id}/calving',
                json={
                    'calving_date': '2026-09-12',
                    'delivery_outcome': 'Stillborn',
                    'calving_ease': 'Difficult',
                    'notes': 'Calf was stillborn.',
                },
            )

        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        self.assertIsNone(payload['calf'])
        self.assertEqual(payload['mother']['status'], 'Lactating')

        # Mother still transitioned to lactating and event logged
        db.session.refresh(self.cow)
        self.assertEqual(self.cow.status, 'Lactating')
        self.assertEqual(self.cow.pregnancy_status, 'Open')

    def test_record_calving_rejects_duplicate_tag(self):
        # Create existing active cow with tag CALF-DUPE
        existing = Cow(
            tenant_id=self.tenant.id,
            tag_number='CALF-DUPE',
            date_of_birth=date(2025, 1, 1),
            is_active=True,
        )
        db.session.add(existing)
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.post(
                f'/api/animals/{self.cow.id}/calving',
                json={
                    'calving_date': '2026-09-12',
                    'calf_tag': 'CALF-DUPE',
                    'delivery_outcome': 'Live Birth',
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn('already exists', response.get_json()['error'])

    def test_timeline_event_calving_applies_full_workflow(self):
        self._login()

        with self.client:
            response = self.client.post(
                f'/api/animals/{self.cow.id}/events',
                json={
                    'event_type': 'calving',
                    'event_date': '2026-09-12T08:30:00Z',
                    'title': 'Calved Heifer',
                    'description': 'Normal calving',
                    'event_data': {
                        'calf_sex': 'Female',
                        'calf_tag': 'CALF-TL-01',
                        'birth_weight_kg': 38.0,
                        'delivery_outcome': 'Live Birth',
                    },
                },
            )

        self.assertEqual(response.status_code, 201)

        db.session.refresh(self.cow)
        self.assertEqual(self.cow.status, 'Lactating')
        self.assertEqual(self.cow.last_calving_date, date(2026, 9, 12))

        calf = Cow.query.filter_by(tenant_id=self.tenant.id, tag_number='CALF-TL-01').first()
        self.assertIsNotNone(calf)
        self.assertEqual(calf.dam_id, self.cow.id)

    def test_insemination_outcome_patch_allows_calved(self):
        breeding_log = BreedingLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            provided_by='VET',
            external_sire_code='EXT-BULL-1',
            insemination_date=date(2025, 12, 1),
            expected_calving_date=date(2026, 9, 10),
            status='Pregnant',
        )
        db.session.add(breeding_log)
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.patch(
                f'/api/v1/breeding/insemination/{breeding_log.id}/outcome',
                json={'status': 'Calved'},
            )

        self.assertEqual(response.status_code, 200)
        db.session.refresh(breeding_log)
        self.assertEqual(breeding_log.status, 'Calved')
        db.session.refresh(self.cow)
        self.assertEqual(self.cow.status, 'Lactating')
        self.assertEqual(self.cow.pregnancy_status, 'Open')

    def test_insemination_outcome_maps_open_alias_to_failed(self):
        breeding_log = BreedingLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            provided_by='VET',
            external_sire_code='EXT-BULL-2',
            insemination_date=date(2025, 12, 1),
            expected_calving_date=date(2026, 9, 10),
            status='Pending',
        )
        db.session.add(breeding_log)
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.patch(
                f'/api/v1/breeding/insemination/{breeding_log.id}/outcome',
                json={'status': 'Open'},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['status'], 'Failed')

        db.session.refresh(breeding_log)
        self.assertEqual(breeding_log.status, 'Failed')
        db.session.refresh(self.cow)
        self.assertEqual(self.cow.pregnancy_status, 'Open')
        self.assertIsNone(self.cow.due_date)

    def test_legacy_breeding_status_endpoint_maps_open_alias_to_failed(self):
        breeding_log = BreedingLog(
            tenant_id=self.tenant.id,
            cow_id=self.cow.id,
            provided_by='VET',
            external_sire_code='EXT-BULL-3',
            insemination_date=date(2025, 12, 1),
            expected_calving_date=date(2026, 9, 10),
            status='Pending',
        )
        db.session.add(breeding_log)
        db.session.commit()

        self._login()
        with self.client:
            response = self.client.put(
                f'/api/operations/breeding-logs/{breeding_log.id}/status',
                json={'status': 'open'},
            )

        self.assertEqual(response.status_code, 200)
        db.session.refresh(breeding_log)
        self.assertEqual(breeding_log.status, 'Failed')

    def _record_live_calf(self, calf_tag='CALF-EDIT-01'):
        with self.client:
            response = self.client.post(
                f'/api/animals/{self.cow.id}/calving',
                json={
                    'calving_date': '2026-09-12',
                    'calf_sex': 'Female',
                    'calf_tag': calf_tag,
                    'calf_name': 'Original Name',
                    'delivery_outcome': 'Live Birth',
                },
            )
        self.assertEqual(response.status_code, 201)
        return Cow.query.filter_by(tenant_id=self.tenant.id, tag_number=calf_tag).first()

    def test_edit_calf_details_updates_only_the_calf_record(self):
        self._login()
        calf = self._record_live_calf()

        cycle = LactationCycle.query.filter_by(cow_id=self.cow.id, is_active=True).first()
        mother_last_calved_before = self.cow.last_calving_date

        with self.client:
            response = self.client.patch(
                f'/api/animals/{calf.id}',
                json={
                    'tag_number': 'CALF-EDIT-RENAMED',
                    'name': 'Renamed Calf',
                    'breed_status': 'Pedigree',
                    'date_of_birth': '2026-09-11',
                    'sire_name': 'Updated Sire',
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['tag_number'], 'CALF-EDIT-RENAMED')
        self.assertEqual(payload['name'], 'Renamed Calf')
        self.assertEqual(payload['breed_status'], 'Pedigree')
        self.assertEqual(payload['date_of_birth'], '2026-09-11')
        self.assertEqual(payload['sire_name'], 'Updated Sire')

        db.session.refresh(calf)
        self.assertEqual(calf.tag_number, 'CALF-EDIT-RENAMED')
        self.assertEqual(calf.name, 'Renamed Calf')
        self.assertEqual(calf.breed_status, 'Pedigree')
        self.assertEqual(calf.date_of_birth, date(2026, 9, 11))

        # The mother's calving-derived state must be untouched by editing the calf.
        db.session.refresh(self.cow)
        self.assertEqual(self.cow.last_calving_date, mother_last_calved_before)
        self.assertEqual(self.cow.status, 'Lactating')
        db.session.refresh(cycle)
        self.assertTrue(cycle.is_active)

    def test_edit_calf_rejects_duplicate_active_tag(self):
        self._login()
        calf = self._record_live_calf()

        other = Cow(tenant_id=self.tenant.id, tag_number='TAKEN-TAG', date_of_birth=date(2025, 1, 1), is_active=True)
        db.session.add(other)
        db.session.commit()

        with self.client:
            response = self.client.patch(
                f'/api/animals/{calf.id}',
                json={'tag_number': 'TAKEN-TAG'},
            )

        self.assertEqual(response.status_code, 409)

    def test_edit_calf_birth_weight_after_calving(self):
        self._login()
        calf = self._record_live_calf()

        with self.client:
            response = self.client.patch(
                f'/api/animals/{calf.id}',
                json={'birth_weight_kg': 33.4},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['birth_weight_kg'], 33.4)

        db.session.refresh(calf)
        self.assertEqual(float(calf.birth_weight_kg), 33.4)

        with self.client:
            get_response = self.client.get(f'/api/animals/{calf.id}')
        self.assertEqual(get_response.get_json()['birth_weight_kg'], 33.4)

    def test_edit_calf_birth_weight_rejects_non_numeric(self):
        self._login()
        calf = self._record_live_calf()

        with self.client:
            response = self.client.patch(
                f'/api/animals/{calf.id}',
                json={'birth_weight_kg': 'not-a-number'},
            )

        self.assertEqual(response.status_code, 400)

    def test_edit_calf_birth_weight_can_be_cleared(self):
        self._login()
        calf = self._record_live_calf()

        with self.client:
            response = self.client.patch(
                f'/api/animals/{calf.id}',
                json={'birth_weight_kg': ''},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json()['birth_weight_kg'])
        db.session.refresh(calf)
        self.assertIsNone(calf.birth_weight_kg)

    def test_delete_calf_archives_record_without_touching_mother(self):
        self._login()
        calf = self._record_live_calf()

        cycle = LactationCycle.query.filter_by(cow_id=self.cow.id, is_active=True).first()
        mother_events_before = AnimalTimelineEvent.query.filter_by(
            tenant_id=self.tenant.id, cow_id=self.cow.id
        ).count()

        with self.client:
            response = self.client.delete(f'/api/animals/{calf.id}')

        self.assertEqual(response.status_code, 200)

        db.session.refresh(calf)
        self.assertFalse(calf.is_active)
        self.assertIn('_archived_', calf.tag_number)

        # Mother's lactation cycle, status, and timeline are unaffected by the calf's deletion.
        db.session.refresh(self.cow)
        self.assertEqual(self.cow.status, 'Lactating')
        db.session.refresh(cycle)
        self.assertTrue(cycle.is_active)
        mother_events_after = AnimalTimelineEvent.query.filter_by(
            tenant_id=self.tenant.id, cow_id=self.cow.id
        ).count()
        self.assertEqual(mother_events_before, mother_events_after)

    def test_get_animal_expands_dam_id_into_authoritative_dam_object(self):
        self._login()
        calf = self._record_live_calf()

        with self.client:
            response = self.client.get(f'/api/animals/{calf.id}')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['dam_id'], self.cow.id)
        self.assertEqual(payload['dam'], {
            'id': self.cow.id,
            'tag_number': self.cow.tag_number,
            'name': self.cow.name,
        })

    def test_patch_animal_expands_dam_id_into_authoritative_dam_object(self):
        self._login()
        calf = self._record_live_calf()

        with self.client:
            response = self.client.patch(
                f'/api/animals/{calf.id}',
                json={'name': 'Renamed via patch'},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload['dam_id'], self.cow.id)
        self.assertEqual(payload['dam'], {
            'id': self.cow.id,
            'tag_number': self.cow.tag_number,
            'name': self.cow.name,
        })

    def test_animal_without_dam_returns_null_dam_object(self):
        self._login()

        with self.client:
            response = self.client.get(f'/api/animals/{self.cow.id}')

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsNone(payload['dam_id'])
        self.assertIsNone(payload['dam'])
