"""Builds the demo workspace ("Silato Farm") and fills it with believable data.

``DemoSeedService.seed()`` is idempotent: it creates the demo tenant, farm and
accounts if missing, deletes every row the demo tenant owns, and regenerates
the farm with dates relative to today. Running it twice leaves the same data,
never twice the data. It all happens in one transaction, so visitors keep
seeing the previous data until the new data is committed.

Every name, phone and figure here is invented. Nothing is read from real
farms or the SQL dumps in this repository.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional

from flask import current_app
from sqlalchemy import or_, select

from app import db
from app.models.farm import Farm
from app.models.finance import (
    AnimalCostAllocation,
    AnimalCostType,
    Buyer,
    CostClass,
    Customer,
    Delivery,
    PaymentStatus,
    SalesLedger,
    Transaction,
    TransactionCategory,
    TransactionStatus,
    TransactionType,
)
from app.models.genetics import GeneticProfile, GeneticTraitDefinition, GeneticTraitScore
from app.models.hr import Employee, Payroll, PayrollRun, PayrollRunStatus, PayrollStatus
from app.models.livestock import (
    AnimalTimelineEvent,
    AnimalYieldTarget,
    BreedStatus,
    BreedingLog,
    Cow,
    CowStatus,
    DailyTaskLog,
    HeatObservation,
    HerdsmanRoutineTemplate,
    LactationCycle,
    MedicalRecord,
    MilkTest,
    MilkTestResult,
    SemenInventory,
    VetVisit,
)
from app.models.supply import (
    BatchIngredient,
    FarmMeasurementUnit,
    FeedBatch,
    FeedBatchConsumptionEvent,
    FeedingGroupProfile,
    FeedRecipe,
    Ingredient,
    InventoryItem,
    InventoryTransaction,
    ItemCategory,
    MilkDisposition,
    MilkDispositionType,
    MilkDropAlert,
    MilkLog,
    MilkSession,
    RecipeIngredient,
)
from app.models.tenant import Tenant
from app.models.user import Role, User
from app.services.demo_account import DemoAccount
from app.services.feed_mixer_policy_service import FeedMixerPolicyService
from app.services.page_access import PAGE_ACCESS
from app.services.payroll_run_builder import PayrollRunBuilder
from app.services.receipt_service import ReceiptService
from app.utils.farm_time import farm_timezone, farm_today

HISTORY_DAYS = 75
# Postgres advisory-lock key so concurrent refreshes never seed at the same time.
_SEED_LOCK_KEY = 0x5117A70  # "SILATO"
# Fixed seed: every run produces the same farm, shifted to the current date.
_RANDOM_SEED = 20261113

# The demo owner sees every page except member administration.
DEMO_PAGE_ACCESS = sorted(key for key in PAGE_ACCESS if key != 'member_admin')


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


@dataclass
class DemoAccounts:
    tenant: Tenant
    farm: Farm
    owner: User
    vet: User
    herdsman: User


@dataclass
class DemoSeedSummary:
    tenant_id: int
    counts: Dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

class DemoAccountProvisioner:
    """Get-or-create the demo tenant, its farm and its (password-less) accounts."""

    VET_USERNAME = 'demo.silato.vet'
    HERDSMAN_USERNAME = 'demo.silato.herdsman'

    @staticmethod
    def ensure() -> DemoAccounts:
        tenant = DemoAccount.tenant()
        if tenant is None:
            tenant = Tenant(name=DemoAccount.TENANT_NAME, tenant_type='single', region=DemoAccount.FARM_LOCATION,
                            is_active=True, is_demo=True)
            db.session.add(tenant)
            db.session.flush()

        if not tenant.registration_number:
            tenant.registration_number = DemoAccount.REGISTRATION_NUMBER
        farm = DemoAccount.farm(tenant)
        if farm is None:
            farm = Farm(tenant_id=tenant.id, name=DemoAccount.FARM_NAME, is_active=True)
            db.session.add(farm)
            db.session.flush()

        owner = DemoAccountProvisioner._ensure_user(tenant, DemoAccount.OWNER_USERNAME, DemoAccount.OWNER_NAME, Role.FARMER)
        owner.page_access = DEMO_PAGE_ACCESS
        vet = DemoAccountProvisioner._ensure_user(tenant, DemoAccountProvisioner.VET_USERNAME, 'Dr. Wanjiku Mutua', Role.VET)
        herdsman = DemoAccountProvisioner._ensure_user(tenant, DemoAccountProvisioner.HERDSMAN_USERNAME, 'Kiprop Langat', Role.FARM_HAND)
        db.session.flush()
        return DemoAccounts(tenant=tenant, farm=farm, owner=owner, vet=vet, herdsman=herdsman)

    @staticmethod
    def _ensure_user(tenant: Tenant, username: str, name: str, role: str) -> User:
        user = User.query.filter_by(username=username).first()
        if user is not None and (user.tenant_id != tenant.id or not user.is_demo):
            raise RuntimeError(f'Username {username!r} is taken by a non-demo account; refusing to seed.')
        if user is None:
            user = DemoAccount.new_user(tenant=tenant, username=username, name=name, role=role)
            db.session.add(user)
        else:
            # Keep the account unusable for password login even if someone changed it.
            user.set_unusable_password()
            user.is_active = True
            user.requires_password_reset = False
        return user


# ---------------------------------------------------------------------------
# Purge
# ---------------------------------------------------------------------------

class DemoDataPurger:
    """Deletes every row owned by the demo tenant, keeping the tenant, farms and users.

    Walks all mapped tables, children first. A table with ``tenant_id`` is
    filtered on it; a table without one is filtered through its foreign keys to
    tenant-owned tables (e.g. inventory transactions through their item).
    Refuses to run against a tenant that is not flagged as the demo.
    """

    KEEP_TABLES = frozenset({'tenants', 'farms', 'users'})

    @staticmethod
    def purge(tenant: Tenant) -> None:
        if not tenant.is_demo:
            raise RuntimeError('Refusing to purge a tenant that is not the demo workspace.')

        tables = db.metadata.sorted_tables
        tenant_owned = {table.name for table in tables if 'tenant_id' in table.c}
        for table in reversed(tables):
            if table.name in DemoDataPurger.KEEP_TABLES:
                continue
            condition = DemoDataPurger._ownership_condition(table, tenant.id, tenant_owned)
            if condition is not None:
                db.session.execute(table.delete().where(condition))

    @staticmethod
    def _ownership_condition(table, tenant_id: int, tenant_owned: set):
        if 'tenant_id' in table.c:
            return table.c.tenant_id == tenant_id
        clauses = []
        for fk in table.foreign_keys:
            parent = fk.column.table
            if parent.name in tenant_owned and parent.name not in DemoDataPurger.KEEP_TABLES:
                owned_ids = select(fk.column).where(parent.c.tenant_id == tenant_id)
                clauses.append(fk.parent.in_(owned_ids))
        return or_(*clauses) if clauses else None


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _CowSpec:
    tag: str
    name: str
    breed: str
    age_days: int
    stage: str                       # lactating | dry | heifer | calf
    calved_days_ago: Optional[int] = None
    peak_litres: float = 0.0         # daily yield at peak of lactation
    lactation_number: int = 0
    breeding: Optional[str] = None   # pregnant | pending | failed | heat
    bred_days_ago: Optional[int] = None
    dam_tag: Optional[str] = None


_HERD: List[_CowSpec] = [
    _CowSpec('SF-001', 'Malkia', BreedStatus.PEDIGREE, 2350, 'lactating', 80, 7.6, 4, 'pending', 14),
    _CowSpec('SF-002', 'Neema', BreedStatus.APPENDIX, 1900, 'lactating', 118, 7.0, 3, 'pregnant', 52),
    _CowSpec('SF-003', 'Baraka', BreedStatus.INTERMEDIATE, 1650, 'lactating', 35, 6.4, 2, 'heat', dam_tag='SF-004'),
    _CowSpec('SF-004', 'Zawadi', BreedStatus.PEDIGREE, 2700, 'lactating', 190, 6.8, 5, 'pregnant', 105),
    _CowSpec('SF-005', 'Faraja', BreedStatus.APPENDIX, 1500, 'lactating', 88, 5.9, 2, 'failed', 40, dam_tag='SF-010'),
    _CowSpec('SF-006', 'Imani', BreedStatus.INTERMEDIATE, 2100, 'lactating', 150, 6.2, 3, 'pregnant', 70),
    _CowSpec('SF-007', 'Rehema', BreedStatus.FOUNDATION, 1800, 'lactating', 230, 5.4, 3, 'pregnant', 140),
    _CowSpec('SF-008', 'Tumaini', BreedStatus.APPENDIX, 1010, 'lactating', 20, 6.0, 1, dam_tag='SF-001'),
    _CowSpec('SF-009', 'Upendo', BreedStatus.INTERMEDIATE, 2500, 'lactating', 260, 5.0, 4, 'pregnant', 180),
    _CowSpec('SF-010', 'Amani', BreedStatus.PEDIGREE, 2900, 'dry', 330, 7.0, 5, 'pregnant', 245),
    _CowSpec('SF-011', 'Furaha', BreedStatus.APPENDIX, 2000, 'dry', 345, 6.5, 3, 'pregnant', 255),
    _CowSpec('SF-012', 'Nuru', BreedStatus.INTERMEDIATE, 610, 'heifer', breeding='pending', bred_days_ago=9, dam_tag='SF-002'),
    _CowSpec('SF-013', 'Pendo', BreedStatus.APPENDIX, 560, 'heifer', breeding='heat', dam_tag='SF-006'),
    _CowSpec('SF-014', 'Tamu', BreedStatus.PEDIGREE, 80, 'calf', dam_tag='SF-001'),
    _CowSpec('SF-015', 'Shiru', BreedStatus.INTERMEDIATE, 150, 'calf', dam_tag='SF-006'),
]

# Dry cows were milked until this many days after calving.
_DRY_OFF_AFTER_DAYS = 290

# Cow on a mastitis treatment whose milk is withheld (shows on the safety board).
_TREATED_TAG = 'SF-005'
_TREATED_DAYS_AGO = 2
_WITHDRAWAL_DAYS = 4

# Projected milk-volume breeding values (litres/day above the breed base). Daughters of the
# farm's AI sires score above their dams, which is what the genetic progress chart shows.
_MILK_VOLUME_PTA = {
    'SF-001': 1.10, 'SF-002': 0.80, 'SF-003': 1.30, 'SF-004': 0.90, 'SF-005': 1.00, 'SF-006': 0.70,
    'SF-007': 0.40, 'SF-008': 1.60, 'SF-009': 0.50, 'SF-010': 0.60, 'SF-011': 0.70, 'SF-012': 1.50,
    'SF-013': 1.40, 'SF-014': 1.90, 'SF-015': 1.60,
}

# Yield drops the farm was alerted to: (tag, days ago) -> share of the usual morning yield, status,
# notes. Faraja's drop is how her mastitis was found; Upendo's is this morning's, not yet checked.
_MILK_DROPS = {
    (_TREATED_TAG, _TREATED_DAYS_AGO): (0.60, 'INVESTIGATING', 'Hard, warm front-left quarter. Vet called; mastitis treatment started.'),
    ('SF-009', 0): (0.78, 'OPEN', None),
}

_SIRES = [
    ('Ridgeview Titan', 'RVT-2291', 'Friesian'),
    ('Highland Sable', 'HLS-0874', 'Ayrshire'),
]


class DemoFarmGenerator:
    """Writes the demo farm's records for the HISTORY_DAYS up to ``today``."""

    def __init__(self, accounts: DemoAccounts, today: date):
        self.a = accounts
        self.t = accounts.tenant.id
        self.today = today
        self.tz = farm_timezone()
        self.rng = random.Random(_RANDOM_SEED)
        self.cows: Dict[str, Cow] = {}
        self.daily_saleable: Dict[date, Decimal] = {}
        self.counts: Dict[str, int] = {}
        self.items: Dict[str, InventoryItem] = {}
        self.recipes: Dict[str, FeedRecipe] = {}

    # -- helpers ----------------------------------------------------------
    def _day(self, days_ago: int) -> date:
        return self.today - timedelta(days=days_ago)

    def _at(self, day: date, hour: int, minute: int = 0) -> datetime:
        return datetime.combine(day, time(hour, minute), tzinfo=self.tz)

    def _add(self, *rows) -> None:
        for row in rows:
            db.session.add(row)
            key = type(row).__tablename__
            self.counts[key] = self.counts.get(key, 0) + 1

    def _event(self, cow: Cow, event_type: str, title: str, when, *, description: Optional[str] = None,
               data: Optional[dict] = None, by: Optional[int] = None) -> None:
        """One entry on a cow's timeline, shaped like the ones the services write."""
        stamp = when if isinstance(when, datetime) else self._at(when, 9, 0)
        self._add(AnimalTimelineEvent(tenant_id=self.t, cow_id=cow.id, event_type=event_type, title=title,
                                      description=description, event_date=stamp, event_data=data or {},
                                      created_by=by or self.a.owner.id))

    def _history(self):
        for offset in range(HISTORY_DAYS - 1, -1, -1):
            yield self._day(offset)

    # -- run ----------------------------------------------------------------
    def generate(self) -> Dict[str, int]:
        self._herd()
        self._genetics()
        self._breeding()
        self._health()
        self._milk()
        self._milk_usage_and_sales()
        self._inventory_and_feed()
        self._feed_batches()
        self._staff_and_tasks()
        self._expenses_and_income()
        self._receipts()
        return self.counts

    # -- herd ----------------------------------------------------------------
    def _herd(self) -> None:
        for spec in _HERD:
            status = {
                'lactating': CowStatus.LACTATING, 'dry': CowStatus.DRY,
                'heifer': CowStatus.HEIFER, 'calf': CowStatus.CALF,
            }[spec.stage]
            cow = Cow(
                tenant_id=self.t,
                tag_number=spec.tag,
                name=spec.name,
                breed_status=spec.breed,
                date_of_birth=self._day(spec.age_days),
                status=status,
                last_calving_date=self._day(spec.calved_days_ago) if spec.calved_days_ago is not None else None,
                pregnancy_status='Open',
                birth_weight_kg=_money(self.rng.uniform(32, 42)),
                genetic_score=self.rng.randint(55, 88),
                sire_name=self.rng.choice(_SIRES)[0],
                is_active=True,
            )
            self._add(cow)
            self.cows[spec.tag] = cow
        db.session.flush()

        for spec in _HERD:
            cow = self.cows[spec.tag]
            if spec.dam_tag:
                dam = self.cows[spec.dam_tag]
                cow.dam_id = dam.id
                self._event(cow, 'birth', 'Born / Registered', self._at(cow.date_of_birth, 5, 40),
                            description=f'Born to dam {dam.tag_number} ({dam.name}). Delivery: Live birth.',
                            data={'dam_id': dam.id, 'dam_tag': dam.tag_number, 'dam_name': dam.name},
                            by=self.a.herdsman.id)
            if spec.calved_days_ago is None:
                continue
            calved = self._day(spec.calved_days_ago)
            calf = next((self.cows[c.tag] for c in _HERD
                         if c.dam_tag == spec.tag and c.age_days == spec.calved_days_ago), None)
            self._event(cow, 'calving', f'Calved - {"Female" if calf else "Calf"} (lactation {spec.lactation_number})',
                        self._at(calved, 5, 40), description='Delivery outcome: Live birth. Calving ease: Unassisted.',
                        data={'calf_id': calf.id if calf else None, 'calf_tag': calf.tag_number if calf else None,
                              'calf_name': calf.name if calf else None, 'lactation_number': spec.lactation_number},
                        by=self.a.herdsman.id)
            dry = spec.stage == 'dry'
            self._add(LactationCycle(
                cow_id=cow.id,
                cycle_number=spec.lactation_number,
                actual_calving_date=calved,
                drying_date=self._day(spec.calved_days_ago - _DRY_OFF_AFTER_DAYS) if dry else None,
                is_active=not dry,
            ))

    # -- genetics --------------------------------------------------------------
    def _genetics(self) -> None:
        """A projected milk-volume score per cow (Breeding: herd genetic progress)."""
        trait = GeneticTraitDefinition.query.filter_by(name='milk_volume').first()
        if trait is None:  # a shared lookup row, the same one real farms score against
            trait = GeneticTraitDefinition(name='milk_volume', display_name='Milk Volume', category='Production',
                                           unit='liters/day')
            db.session.add(trait)
            db.session.flush()
        for spec in _HERD:
            profile = GeneticProfile(cow_id=self.cows[spec.tag].id, tenant_id=self.t,
                                     source=GeneticProfile.SOURCE_PROJECTED)
            self._add(profile)
            db.session.flush()
            self._add(GeneticTraitScore(profile_id=profile.id, trait_definition_id=trait.id,
                                        value=Decimal(str(_MILK_VOLUME_PTA[spec.tag])),
                                        reliability=70 if spec.stage in ('lactating', 'dry') else 45,
                                        scored_source=GeneticTraitScore.SCORED_SOURCE_SYSTEM))

    # -- breeding --------------------------------------------------------------
    def _breeding(self) -> None:
        semen = []
        for bull, code, breed in _SIRES:
            straw = SemenInventory(tenant_id=self.t, bull_name=bull, straw_code=code, breed=breed,
                                   provider='Rift Valley Genetics', cost=_money(1800 if breed == 'Friesian' else 1500),
                                   stock_level=self.rng.randint(4, 9))
            self._add(straw)
            semen.append(straw)
        db.session.flush()

        for spec in _HERD:
            cow = self.cows[spec.tag]
            if spec.breeding in ('pregnant', 'pending', 'failed'):
                served = self._day(spec.bred_days_ago)
                straw = semen[0] if spec.breed != BreedStatus.FOUNDATION else semen[1]
                status = {'pregnant': 'Pregnant', 'pending': 'Pending', 'failed': 'Failed'}[spec.breeding]
                log = BreedingLog(
                    tenant_id=self.t, cow_id=cow.id, inventory_semen_id=straw.id, provided_by='FARM',
                    insemination_date=served, insemination_time=time(9, 30),
                    technician_name='County AI Service', service_fee=_money(1500),
                    expected_calving_date=served + timedelta(days=283), status=status,
                    farm_location=DemoAccount.FARM_LOCATION,
                )
                self._add(log)
                db.session.flush()
                observed = self._at(served - timedelta(days=1), 17, 15)
                self._heat(cow, HeatObservation(
                    tenant_id=self.t, cow_id=cow.id, observed_at=observed, intensity='HIGH',
                    signs=['standing to be mounted', 'clear mucus', 'restless'],
                    next_window_start=served + timedelta(days=18), next_window_end=served + timedelta(days=24),
                    breeding_log_id=log.id, created_by=self.a.herdsman.id,
                ))
                calving_due = served + timedelta(days=283)
                self._event(cow, 'breeding', f'Inseminated with {straw.bull_name}', self._at(served, 9, 30),
                            description=f'Status: {status} | Expected calving: {calving_due.isoformat()}',
                            data={'breeding_log_id': log.id, 'provided_by': 'FARM', 'status': status,
                                  'expected_calving_date': calving_due.isoformat(),
                                  'pregnancy_check_date': (served + timedelta(days=35)).isoformat()})
                if spec.breeding == 'pregnant':
                    cow.pregnancy_status = 'Pregnant'
                    cow.due_date = calving_due
                    if spec.bred_days_ago >= 35:
                        self._event(cow, 'breeding_status_update', 'Breeding status changed to Pregnant',
                                    self._at(served + timedelta(days=35), 10, 0),
                                    data={'breeding_log_id': log.id, 'status': 'Pregnant'}, by=self.a.vet.id)
                elif spec.breeding == 'failed':
                    self._event(cow, 'breeding_status_update', 'Insemination unsuccessful',
                                self._at(self._day(2), 6, 45), description='Returned to heat after the service.',
                                data={'breeding_log_id': log.id, 'status': 'Failed'}, by=self.a.herdsman.id)
                    # Returned to heat after the failed service; due for a repeat.
                    self._heat(cow, HeatObservation(
                        tenant_id=self.t, cow_id=cow.id, observed_at=self._at(self._day(2), 6, 40),
                        intensity='MEDIUM', signs=['mounting others', 'bellowing'],
                        next_window_start=self._day(2 - 18), next_window_end=self._day(2 - 24),
                        created_by=self.a.herdsman.id,
                    ))
            elif spec.breeding == 'heat':
                seen = self.rng.randint(0, 1)
                self._heat(cow, HeatObservation(
                    tenant_id=self.t, cow_id=cow.id, observed_at=self._at(self._day(seen), 6, 15),
                    intensity=self.rng.choice(['MEDIUM', 'HIGH']), signs=['standing heat', 'swollen vulva'],
                    notes='Serve within 12 hours.',
                    next_window_start=self._day(seen - 18), next_window_end=self._day(seen - 24),
                    created_by=self.a.herdsman.id,
                ))

    def _heat(self, cow: Cow, observation: HeatObservation) -> None:
        self._add(observation)
        db.session.flush()
        self._event(cow, 'heat_observation', f'Heat observed ({observation.intensity.lower()})',
                    observation.observed_at, description=observation.notes,
                    data={'heat_observation_id': observation.id, 'signs': observation.signs,
                          'next_window_start': observation.next_window_start.isoformat(),
                          'next_window_end': observation.next_window_end.isoformat()},
                    by=observation.created_by)

    # -- health --------------------------------------------------------------
    def _health(self) -> None:
        vet = self.a.vet.id
        visits = [
            ('SF-004', 40, 'Routine pregnancy diagnosis', 'Confirmed pregnant, about 9 weeks.', 'Low', []),
            ('SF-009', 26, 'Lameness, right hind', 'Sole ulcer. Hoof trimmed and blocked.', 'Medium',
             [{'name': 'Oxytetracycline spray', 'dose': 'topical'}]),
            ('SF-014', 12, 'Calf scours', 'Mild diarrhoea, responded to oral rehydration.', 'Low',
             [{'name': 'Oral rehydration salts', 'dose': '2 L twice daily'}]),
            (_TREATED_TAG, _TREATED_DAYS_AGO, 'Clinical mastitis, front left quarter',
             'Hard, warm quarter with clots in milk.', 'High',
             [{'name': 'Intramammary cloxacillin', 'dose': '1 tube per milking for 3 milkings'}]),
        ]
        for tag, days_ago, reason, diagnosis, severity, meds in visits:
            follow_up = tag == _TREATED_TAG
            self._event(self.cows[tag], 'medical', reason, self._at(self._day(days_ago), 10, 0), description=diagnosis,
                        data={'medications': meds or None, 'follow_up_required': follow_up,
                              'follow_up_date': self._day(-3).isoformat() if follow_up else None}, by=vet)
            self._add(VetVisit(
                tenant_id=self.t, animal_id=self.cows[tag].id, vet_id=vet, visit_date=self._day(days_ago),
                reason_for_visit=reason, diagnosis=diagnosis, medications=meds or None, severity=severity,
                recommendations='Keep milk out of the tank until withdrawal ends.' if follow_up else None,
                follow_up_required=follow_up, follow_up_date=self._day(-3) if follow_up else None,
                follow_up_status='Scheduled' if follow_up else 'Not Required',
            ))

        self._add(
            MedicalRecord(tenant_id=self.t, cow_id=self.cows[_TREATED_TAG].id, vet_id=vet,
                          visit_date=self._at(self._day(_TREATED_DAYS_AGO), 10, 0),
                          diagnosis='Clinical mastitis, front left quarter', medication='Intramammary cloxacillin',
                          withdrawal_days_recommended=_WITHDRAWAL_DAYS, remarks='Strip quarter at each milking.'),
            MedicalRecord(tenant_id=self.t, cow_id=self.cows['SF-009'].id, vet_id=vet,
                          visit_date=self._at(self._day(26), 11, 0), diagnosis='Sole ulcer, right hind',
                          medication='Oxytetracycline spray', withdrawal_days_recommended=0),
            MedicalRecord(tenant_id=self.t, cow_id=self.cows['SF-002'].id, vet_id=vet,
                          visit_date=self._at(self._day(60), 9, 0), diagnosis='Routine deworming',
                          medication='Albendazole 10%', withdrawal_days_recommended=3),
        )
        self._event(self.cows['SF-002'], 'medical', 'Routine deworming', self._at(self._day(60), 9, 0),
                    data={'medication': 'Albendazole 10%', 'withdrawal_days_recommended': 3}, by=vet)
        for days_ago, tag, result in [(1, _TREATED_TAG, MilkTestResult.FAIL), (9, 'SF-003', MilkTestResult.PASS),
                                      (9, 'SF-008', MilkTestResult.PASS), (16, 'SF-001', MilkTestResult.PASS)]:
            self._add(MilkTest(tenant_id=self.t, cow_id=self.cows[tag].id, tested_at=self._at(self._day(days_ago), 7, 0),
                               test_type='California Mastitis Test', result=result, recorded_by=self.a.herdsman.id))

        treated = self.cows[_TREATED_TAG]
        treated.is_hardlocked = True
        treated.hold_reason = 'Mastitis treatment withdrawal'
        treated.hold_until = self._at(self._day(_TREATED_DAYS_AGO - _WITHDRAWAL_DAYS), 10, 0)
        treated.hold_set_at = self._at(self._day(_TREATED_DAYS_AGO), 10, 5)
        treated.hold_set_by = vet

    # -- milk ------------------------------------------------------------------
    def _litres_on(self, spec: _CowSpec, day: date) -> float:
        """A simple lactation curve: rises to peak around day 50, then declines."""
        dim = (day - self._day(spec.calved_days_ago)).days
        if dim < 0 or (spec.stage == 'dry' and dim >= _DRY_OFF_AFTER_DAYS):
            return 0.0
        if dim <= 50:
            factor = 0.75 + 0.25 * dim / 50
        else:
            factor = max(0.45, 1 - 0.0022 * (dim - 50))
        return spec.peak_litres * factor * self.rng.uniform(0.92, 1.08)

    def _milk(self) -> None:
        treated_from = self._day(_TREATED_DAYS_AGO)
        treated_until = self._day(_TREATED_DAYS_AGO - _WITHDRAWAL_DAYS)
        for day in self._history():
            saleable = Decimal('0')
            for spec in _HERD:
                if spec.stage not in ('lactating', 'dry'):
                    continue
                total = self._litres_on(spec, day)
                if total <= 0:
                    continue
                withheld = spec.tag == _TREATED_TAG and treated_from <= day <= treated_until
                sessions = [(MilkSession.MORNING, 0.56, 6, 10), (MilkSession.EVENING, 0.44, 17, 20)]
                if day == self.today:
                    sessions = sessions[:1]  # today's evening milking hasn't happened yet
                for session, share, hour, minute in sessions:
                    usual = _money(total * share)
                    drop = _MILK_DROPS.get((spec.tag, (self.today - day).days)) if session == MilkSession.MORNING else None
                    litres = _money(usual * Decimal(str(drop[0]))) if drop else usual
                    status = MilkLog.STATUS_ISOLATED if withheld else (
                        MilkLog.STATUS_FLAGGED if drop else MilkLog.STATUS_VERIFIED)
                    self._add(MilkLog(
                        tenant_id=self.t, cow_id=self.cows[spec.tag].id, amount_liters=litres, session=session,
                        timestamp=self._at(day, hour, minute), recorded_by=self.a.herdsman.id,
                        butterfat_pct=_money(self.rng.uniform(3.4, 4.2)),
                        status=status, anomaly_flag=bool(drop),
                        is_saleable=not withheld,
                        verified_by=self.a.owner.id if status == MilkLog.STATUS_VERIFIED else None,
                        verified_at=self._at(day, hour + 1, 0) if status == MilkLog.STATUS_VERIFIED else None,
                    ))
                    if drop:
                        _share, alert_status, notes = drop
                        self._add(MilkDropAlert(
                            tenant_id=self.t, cow_id=self.cows[spec.tag].id, alert_date=day,
                            missing_milk_liters=usual - litres, status=alert_status,
                            reason=(f'Warning: Yield of {litres}L is >15% below her {usual:.1f}L average. '
                                    'Health check recommended.'),
                            investigation_notes=notes,
                            investigated_by=self.a.owner.id if notes else None,
                            investigated_at=self._at(day, 10, 30) if notes else None,
                        ))
                    if not withheld:
                        saleable += litres
            self.daily_saleable[day] = saleable

    # -- milk usage, buyers and customers ---------------------------------------
    def _milk_usage_and_sales(self) -> None:
        coop = Buyer(tenant_id=self.t, farm_id=self.a.farm.id, name='Kaptembwo Dairy Cooperative',
                     contact_person='Collection clerk', buyer_type='Cooperative', agreed_rate_per_liter=_money(60))
        hotel = Buyer(tenant_id=self.t, farm_id=self.a.farm.id, name='Menengai Hills Hotel',
                      contact_person='Kitchen manager', buyer_type='Business', agreed_rate_per_liter=_money(65))
        self._add(coop, hotel)
        households = [
            Customer(tenant_id=self.t, name='Mama Atieno (kiosk)', phone_number='DEMO-0001',
                     daily_contract_liters=_money(3), agreed_rate_per_liter=_money(70)),
            Customer(tenant_id=self.t, name='Bwana Kariuki', phone_number='DEMO-0002',
                     daily_contract_liters=_money(2), agreed_rate_per_liter=_money(70)),
            Customer(tenant_id=self.t, name='St. Monica Day School', phone_number='DEMO-0003',
                     daily_contract_liters=_money(4), agreed_rate_per_liter=_money(62)),
        ]
        self._add(*households)
        db.session.flush()

        calf = self.cows['SF-014']
        calf_born = self._day(80)
        customer_owed = {c.id: Decimal('0') for c in households}
        coop_unpaid_from = self._day(self.today.day - 1)  # this month's deliveries are unpaid
        for day in self._history():
            # Today only has the morning milking, which is what goes out this morning.
            available = self.daily_saleable.get(day, Decimal('0'))
            if day >= calf_born:
                calf_litres = _money(4 if (day - calf_born).days < 56 else 3)
                self._add(MilkDisposition(tenant_id=self.t, disposition_type=MilkDispositionType.CALF_FEED,
                                          disposition_date=day, liters=calf_litres, calf_id=calf.id,
                                          recorded_by=self.a.herdsman.id, notes='Bucket feeding'))
                available -= calf_litres

            for customer in households:
                if day.weekday() == 6 and customer.name.startswith('St.'):
                    continue  # school closed on Sundays
                litres = _money(customer.daily_contract_liters)
                total = litres * customer.agreed_rate_per_liter
                self._add(Delivery(tenant_id=self.t, customer_id=customer.id, date=day, liters_delivered=litres,
                                   personal_consumption_liters=Decimal('0'), billable_liters=litres,
                                   price_per_liter=customer.agreed_rate_per_liter, total_price=total))
                self._add(Transaction(
                    tenant_id=self.t, farm_id=self.a.farm.id, customer_id=customer.id,
                    transaction_type=TransactionType.DEBIT, category=TransactionCategory.MILK_SALE, amount=total,
                    description=f'Milk delivery on {day.isoformat()} ({litres}L delivered, {litres}L billed)',
                    timestamp=self._at(day, 7, 30), recorded_by=self.a.owner.id,
                    status=TransactionStatus.POSTED.value, posted_at=self._at(day, 7, 30), posted_by=self.a.owner.id,
                ))
                customer_owed[customer.id] += total
                available -= litres

            if day.weekday() in (2, 5):  # the hotel buys twice a week
                hotel_litres = _money(5)
                self._sale(hotel, day, hotel_litres, paid=day < self._day(14))
                available -= hotel_litres

            if available > 0:
                self._sale(coop, day, _money(available), paid=day < coop_unpaid_from)

            # Households settle on Saturdays (everything up to that day).
            if day.weekday() == 5:
                for customer in households:
                    owed = customer_owed[customer.id]
                    if owed > 0 and day < self._day(5):
                        self._payment(customer=customer, day=day, amount=owed, method='M-Pesa')
                        customer_owed[customer.id] = Decimal('0')

        # The kiosk settles this morning, so today's takings aren't empty on the dashboard.
        kiosk = households[0]
        if customer_owed[kiosk.id] > 0:
            self._payment(customer=kiosk, day=self.today, amount=customer_owed[kiosk.id], method='M-Pesa',
                          hour=7, minute=45)
            customer_owed[kiosk.id] = Decimal('0')

        for customer in households:
            customer.account_balance = customer_owed[customer.id]

        self._buyer_payments(coop, monthly=True)
        self._buyer_payments(hotel, monthly=False)

    def _sale(self, buyer: Buyer, day: date, litres: Decimal, *, paid: bool) -> None:
        amount = _money(litres * buyer.agreed_rate_per_liter)
        self._add(SalesLedger(
            tenant_id=self.t, buyer_id=buyer.id, date=day, liters_sold=litres,
            price_per_liter=buyer.agreed_rate_per_liter, total_amount=amount,
            # total_cost holds the amount still owed (see BuyerService.allocate_payment).
            total_cost=Decimal('0') if paid else amount, amount_paid=amount if paid else Decimal('0'),
            payment_status=PaymentStatus.PAID.value if paid else PaymentStatus.UNPAID.value,
            shift=MilkSession.EVENING,
        ))

    def _buyer_payments(self, buyer: Buyer, *, monthly: bool) -> None:
        """One payment transaction per settled period, matching the paid sales above."""
        db.session.flush()
        paid_rows = SalesLedger.query.filter_by(tenant_id=self.t, buyer_id=buyer.id,
                                                payment_status=PaymentStatus.PAID.value).all()
        periods: Dict[tuple, Decimal] = {}
        for row in paid_rows:
            key = (row.date.year, row.date.month) if monthly else row.date.isocalendar()[:2]
            periods[key] = periods.get(key, Decimal('0')) + Decimal(row.total_amount)
        for key, amount in sorted(periods.items()):
            if monthly:
                year, month = key
                pay_day = (date(year, month, 28) + timedelta(days=8)).replace(day=5)
            else:
                pay_day = date.fromisocalendar(key[0], key[1], 7)
            pay_day = min(pay_day, self._day(1))
            self._payment(buyer=buyer, day=pay_day, amount=amount, method='Bank transfer' if monthly else 'M-Pesa')

    def _payment(self, *, day: date, amount: Decimal, method: str, customer: Optional[Customer] = None,
                 buyer: Optional[Buyer] = None, hour: int = 18, minute: int = 30) -> None:
        stamp = self._at(day, hour, minute)
        self._add(Transaction(
            tenant_id=self.t, farm_id=self.a.farm.id,
            customer_id=customer.id if customer else None, buyer_id=buyer.id if buyer else None,
            transaction_type=TransactionType.PAYMENT,
            category=TransactionCategory.BUYER_PAYMENT if buyer else TransactionCategory.PAYMENT,
            income_category=None if buyer else TransactionCategory.MILK_SALE.value,
            amount=_money(amount), description=f'Payment from {(buyer or customer).name}',
            payment_method=method, timestamp=stamp, recorded_by=self.a.owner.id,
            payment_status=PaymentStatus.PAID.value, status=TransactionStatus.POSTED.value,
            posted_at=stamp, posted_by=self.a.owner.id,
        ))

    # -- inventory and feed -------------------------------------------------------
    _ITEMS = [
        # Smallholder rates: about 1 kg dairy meal per 4 L of milk on a napier-based ration grown on the farm.
        # name, category, unit, threshold, cost/unit, energy MJ, protein g, fibre g, weekly in, daily use, bought
        ('Dairy Meal (70 kg bag)', ItemCategory.FEED, 'kg', 60, 52, 11.5, 160, 90, 77, 11, True),
        ('Maize Germ', ItemCategory.FEED, 'kg', 30, 34, 12.8, 100, 60, 28, 4, True),
        ('Cotton Seed Cake', ItemCategory.FEED, 'kg', 15, 58, 11.0, 380, 220, 14, 2, True),
        ('Napier Grass (chopped)', ItemCategory.FEED, 'kg', 600, 4, 8.2, 80, 320, 1300, 190, False),
        ('Rhodes Grass Hay', ItemCategory.FEED, 'kg', 60, 18, 8.0, 70, 340, 35, 5, True),
        ('Dairy Mineral Premix', ItemCategory.SUPPLEMENT, 'kg', 5, 160, 0, 0, 0, 1.5, 0.2, True),
        ('Teat Dip (iodine)', ItemCategory.MEDICINE, 'litres', 3, 850, 0, 0, 0, 0.25, 0.035, True),
        ('Intramammary Cloxacillin', ItemCategory.MEDICINE, 'tubes', 6, 220, 0, 0, 0, 0, 0, False),
    ]

    def _inventory_and_feed(self) -> None:
        items: Dict[str, InventoryItem] = {}
        for name, category, unit, threshold, cost, energy, protein, fibre, _weekly, _daily, _bought in self._ITEMS:
            policy = FeedMixerPolicyService.infer_policy_from_item(name=name, category=category)
            item = InventoryItem(
                tenant_id=self.t, name=name, category=category, unit=unit, current_qty=Decimal('0'),
                minimum_threshold=_money(threshold), cost_per_kg=_money(cost), energy_mj_per_kg=_money(energy),
                protein_grams_per_kg=_money(protein), fiber_grams_per_kg=_money(fibre),
                allowed_mixers=','.join(policy['allowed_mixers']), mixer_role=policy['role'],
            )
            self._add(item)
            items[name] = item
        self.items = items
        db.session.flush()

        purchases: Dict[date, Decimal] = {}
        for name, category, unit, threshold, cost, *_rest, weekly_in, daily_use, bought in self._ITEMS:
            item = items[name]
            stock = Decimal(str(threshold)) * Decimal('1.5')
            self._stock(item, 'IN', stock, cost, self._day(HISTORY_DAYS), 'STANDARD', 'Opening stock')
            for day in self._history():
                # This week's dairy meal delivery is late, so its stock ends below the reorder level.
                late_delivery = name.startswith('Dairy Meal') and day > self._day(8)
                if weekly_in and day.weekday() == 0 and not late_delivery:
                    restock = Decimal(str(weekly_in))
                    if bought:
                        self._stock(item, 'IN', restock, cost, day, 'PURCHASE', 'Weekly delivery')
                        if day < self.today:
                            purchases[day] = purchases.get(day, Decimal('0')) + restock * Decimal(str(cost))
                    else:
                        self._stock(item, 'IN', restock, Decimal('0'), day, 'STANDARD', 'Harvested on farm')
                    stock += restock
                if daily_use and day.weekday() == 6:
                    used = _money(daily_use * 7 * self.rng.uniform(0.9, 1.05))
                    used = min(used, stock)
                    if used > 0:
                        self._stock(item, 'OUT', used, cost, day, 'CONSUMPTION', 'Weekly usage')
                        stock -= used
            if name == 'Maize Germ':
                # Topped up this morning while the dairy meal delivery is late.
                topup = Decimal('28')
                self._stock(item, 'IN', topup, cost, self.today, 'PURCHASE', 'Top-up purchase (dairy meal late)')
                stock += topup
                purchases[self.today] = purchases.get(self.today, Decimal('0')) + topup * Decimal(str(cost))
            if name == 'Intramammary Cloxacillin':
                self._stock(item, 'OUT', Decimal('3'), cost, self._day(_TREATED_DAYS_AGO), 'CONSUMPTION',
                            f'{_TREATED_TAG} mastitis')
                stock -= 3
            item.current_qty = _money(stock)

        # The ledger's feed and supplies purchases are the same deliveries as the stock above.
        for day, amount in sorted(purchases.items()):
            today = day == self.today
            self._expense(day, TransactionCategory.FEED_PURCHASE, amount,
                          'Maize germ top-up' if today else 'Weekly feed and supplies delivery',
                          counterparty='Nakuru Agrovet Supplies', method='M-Pesa', hour=8 if today else 12)

        # How the farm measures feed without a scale (Settings: unit helpers).
        for name, unit_name, kg in [('Dairy Meal (70 kg bag)', 'bag', 70), ('Dairy Meal (70 kg bag)', 'scoop', 2),
                                    ('Napier Grass (chopped)', 'wheelbarrow', 40), ('Rhodes Grass Hay', 'bale', 15)]:
            self._add(FarmMeasurementUnit(tenant_id=self.t, item_id=items[name].id, unit_name=unit_name,
                                          kg_equivalent=_money(kg)))

        profiles = [
            ('lactating', 520, 3.4, 16, 2), ('dry', 560, 2.0, 12, 2), ('heifer', 340, 2.5, 14, 2),
            ('calf_3_6m', 140, 3.0, 18, 3), ('calf_0_3m', 75, 3.0, 20, 3),
        ]
        for group, weight, dmi, protein, times in profiles:
            self._add(FeedingGroupProfile(tenant_id=self.t, feeding_group=group, avg_body_weight_kg=_money(weight),
                                          dmi_percent_bw=_money(dmi), target_protein_percent=_money(protein),
                                          feeding_times_per_day=times))

        dairy = FeedRecipe(tenant_id=self.t, recipe_name='Milking cow dairy meal', target_protein_percentage=_money(18),
                           recipe_type='dairy_meal', feeding_group='lactating', quantity_basis='concentrate',
                           concentrate_kg_per_head_day=Decimal('4.000'), scoop_weight_kg=Decimal('2.000'),
                           created_by=self.a.owner.id)
        main = FeedRecipe(tenant_id=self.t, recipe_name='Milking cow main ration', target_protein_percentage=_money(14),
                          recipe_type='main_meal', feeding_group='lactating', quantity_basis='total_ration',
                          created_by=self.a.owner.id)
        dry = FeedRecipe(tenant_id=self.t, recipe_name='Dry cow ration', target_protein_percentage=_money(12),
                         recipe_type='main_meal', feeding_group='dry', quantity_basis='total_ration',
                         created_by=self.a.owner.id)
        self._add(dairy, main, dry)
        self.recipes = {'dairy': dairy, 'main': main, 'dry': dry}
        db.session.flush()
        for recipe, mix in [
            (dairy, [('Dairy Meal (70 kg bag)', 60), ('Maize Germ', 25), ('Cotton Seed Cake', 13), ('Dairy Mineral Premix', 2)]),
            (main, [('Napier Grass (chopped)', 72), ('Rhodes Grass Hay', 18), ('Dairy Meal (70 kg bag)', 10)]),
            (dry, [('Napier Grass (chopped)', 65), ('Rhodes Grass Hay', 35)]),
        ]:
            for name, share in mix:
                self._add(RecipeIngredient(tenant_id=self.t, recipe_id=recipe.id, inventory_item_id=items[name].id,
                                           inclusion_percentage=_money(share)))

        for spec in _HERD:
            if spec.stage != 'lactating':
                continue
            target = round(spec.peak_litres * 1.15 * 2) / 2
            self._add(AnimalYieldTarget(tenant_id=self.t, animal_id=self.cows[spec.tag].id,
                                        target_liters=_money(target), times_to_feed_daily=2,
                                        base_herd_feed_kg=_money(2.0), milking_topup_kg=_money(target * 0.4)))

    # Concentrate eaten per day by the milking herd (the same rates as the weekly stock usage above).
    _CONCENTRATE_KG_PER_DAY = 17
    _DRY_RATION_KG_PER_DAY = 50

    def _feed_batches(self) -> None:
        """Mixed batches, as the Feed Mixing Planner records them: a dairy meal batch every Monday
        (past ones used up, this week's in use) and a fortnight's dry cow ration mixed last week."""
        ingredients: Dict[str, Ingredient] = {}
        for name, *_rest in self._ITEMS:
            item = self.items[name]
            if item.category == ItemCategory.MEDICINE:
                continue
            ingredient = Ingredient(tenant_id=self.t, name=name, current_cost_per_kg=item.cost_per_kg,
                                    stock_quantity=max(item.current_qty, Decimal('0')))
            self._add(ingredient)
            ingredients[name] = ingredient
        db.session.flush()

        def mix(recipe: FeedRecipe, name: str, mixed_on: date, days: int, kg_per_day: int,
                shares: List[tuple], active: bool) -> None:
            total = Decimal(kg_per_day * days)
            cost = sum((total * Decimal(share) / 100 * self.items[ing].cost_per_kg for ing, share in shares), Decimal('0'))
            batch = FeedBatch(tenant_id=self.t, recipe_id=recipe.id, batch_name=name, total_weight=total,
                              total_cost=cost.quantize(Decimal('0.0001')),
                              cost_per_kg=(cost / total).quantize(Decimal('0.0001')),
                              status='ACTIVE' if active else 'DEPLETED', mixed_on=mixed_on,
                              depleted_on=None if active else mixed_on + timedelta(days=days - 1),
                              created_by=self.a.herdsman.id, posted_at=self._at(mixed_on, 7, 45))
            self._add(batch)
            db.session.flush()
            for ing, share in shares:
                item = self.items[ing]
                self._add(BatchIngredient(tenant_id=self.t, batch_id=batch.id, ingredient_id=ingredients[ing].id,
                                          weight=(total * Decimal(share) / 100).quantize(Decimal('0.001')),
                                          percentage=_money(share), locked_cost_per_kg=item.cost_per_kg,
                                          locked_protein_grams_per_kg=item.protein_grams_per_kg))
            fed_days = min(days, (self.today - mixed_on).days + 1)
            for offset in range(fed_days):
                self._add(FeedBatchConsumptionEvent(
                    tenant_id=self.t, batch_id=batch.id, feeding_group=recipe.feeding_group,
                    consumed_weight=Decimal(kg_per_day), consumed_on=mixed_on + timedelta(days=offset),
                    created_by=self.a.herdsman.id,
                ))

        dairy_shares = [('Dairy Meal (70 kg bag)', 60), ('Maize Germ', 25), ('Cotton Seed Cake', 13),
                        ('Dairy Mineral Premix', 2)]
        this_monday = self.today - timedelta(days=self.today.weekday())
        for weeks_ago in range(6, -1, -1):
            monday = this_monday - timedelta(weeks=weeks_ago)
            mix(self.recipes['dairy'], f'Dairy meal mix, week of {monday:%d %b}', monday, 7,
                self._CONCENTRATE_KG_PER_DAY, dairy_shares, active=weeks_ago == 0)
        dry_mixed = this_monday - timedelta(days=4)
        mix(self.recipes['dry'], f'Dry cow ration, {dry_mixed:%d %b}', dry_mixed, 14, self._DRY_RATION_KG_PER_DAY,
            [('Napier Grass (chopped)', 65), ('Rhodes Grass Hay', 35)],
            active=(self.today - dry_mixed).days < 14)

    def _stock(self, item, kind, qty, cost, day, reason, notes) -> None:
        self._add(InventoryTransaction(item_id=item.id, transaction_type=kind, quantity=_money(qty),
                                       unit_cost=_money(cost), reason_code=reason, notes=notes,
                                       logged_by=self.a.owner.id, transaction_date=self._at(day, 9, 0)))

    # -- staff and daily routine ----------------------------------------------------
    _STAFF = [
        # name, role, monthly salary, hired days ago, linked user
        ('Kiprop Langat', 'Herdsman', 11000, 900, 'herdsman'),
        ('Wairimu Njoroge', 'Milker', 8500, 420, None),
        ('Ochieng Odera', 'Relief milker (part-time)', 4000, 150, None),
    ]

    def _staff_and_tasks(self) -> None:
        employees = []
        for index, (name, role, salary, hired, link) in enumerate(self._STAFF, start=1):
            employee = Employee(
                tenant_id=self.t, user_id=self.a.herdsman.id if link else None, full_name=name, role=role,
                id_number=f'DEMO-ID-{index:03d}', hire_date=self._day(hired), base_salary=_money(salary),
                status='ACTIVE', contract_type='Permanent' if hired > 365 else 'Fixed term',
                statutory_deductions_enabled=False,
                onboarding_status='ACTIVE' if link else 'NONE',
            )
            if index == 2:
                employee.loan_balance = _money(3000)
                employee.monthly_deduction = _money(1000)
            employees.append(employee)
            self._add(employee)
        db.session.flush()

        # Last two closed months, paid on the last day of each month.
        month_end = self.today.replace(day=1) - timedelta(days=1)
        for _ in range(2):
            for employee in employees:
                deduction = employee.monthly_deduction or Decimal('0')
                self._add(Payroll(
                    tenant_id=self.t, staff_id=employee.id, payroll_year=month_end.year,
                    payroll_month=month_end.month, base_salary=employee.base_salary, bonuses=Decimal('0'),
                    deductions=deduction, net_pay=employee.base_salary - deduction, payment_date=month_end,
                    status=PayrollStatus.PAID,
                ))
                self._expense(month_end, TransactionCategory.LABOR_WAGES, employee.base_salary,
                              f'Salary {month_end:%B %Y}: {employee.full_name}', method='M-Pesa')
            month_end = month_end.replace(day=1) - timedelta(days=1)

        # The same months as payroll runs (the Payroll page), plus this month's draft awaiting review.
        this_month = self.today.replace(day=1)
        last_month = this_month - timedelta(days=1)
        for month_start, status in [((last_month.replace(day=1) - timedelta(days=1)).replace(day=1), PayrollRunStatus.PAID),
                                    (last_month.replace(day=1), PayrollRunStatus.PAID),
                                    (this_month, PayrollRunStatus.DRAFT)]:
            builder = PayrollRunBuilder(month_start.year, month_start.month)
            lines = builder.build_line_items(builder.eligible(employees))
            totals = builder.totals(lines)
            paid = status == PayrollRunStatus.PAID
            closed = builder.period_end
            run = PayrollRun(tenant_id=self.t, farm_id=self.a.farm.id, payroll_year=month_start.year,
                             payroll_month=month_start.month, status=status, generated_by=self.a.owner.id,
                             generated_at=self._at(closed if paid else self.today, 8, 0),
                             finalized_by=self.a.owner.id if paid else None,
                             finalized_at=self._at(closed, 9, 0) if paid else None,
                             paid_by=self.a.owner.id if paid else None,
                             paid_at=self._at(closed, 16, 0) if paid else None,
                             total_gross_pay=totals.gross, total_net_pay=totals.net,
                             total_deductions=totals.deductions)
            run.line_items = lines
            self._add(run)

        routines = [
            (time(5, 0), time(7, 0), 'Morning milking', 'Milk all lactating cows; record litres per cow.',
             ['Wash and dry udders', 'Pre-dip and strip', 'Record yield', 'Post-dip teats']),
            (time(7, 30), time(8, 30), 'Morning feeding', 'Feed dairy meal by yield target and fill troughs.',
             ['Weigh dairy meal', 'Chop napier', 'Check water troughs']),
            (time(10, 0), time(11, 0), 'Shed cleaning', 'Scrape walkways and refresh bedding.',
             ['Scrape dung', 'Replace wet bedding', 'Check for lame cows']),
            (time(16, 0), time(18, 0), 'Evening milking', 'Milk all lactating cows; keep withheld milk separate.',
             ['Milk treated cows last', 'Record yield', 'Clean equipment']),
        ]
        templates = []
        for order, (start, end, title, description, checklist) in enumerate(routines, start=1):
            template = HerdsmanRoutineTemplate(tenant_id=self.t, start_time=start, end_time=end, task_title=title,
                                               task_description=description, checklist_items=checklist,
                                               display_order=order, is_active=True)
            templates.append(template)
            self._add(template)
        db.session.flush()

        for days_ago in range(7, 0, -1):
            day = self._day(days_ago)
            for template in templates:
                deviated = days_ago == 3 and template.task_title == 'Shed cleaning'
                self._add(DailyTaskLog(
                    tenant_id=self.t, routine_id=template.id, herdsman_id=self.a.herdsman.id,
                    issue_tag='Water pump fault' if deviated else 'None',
                    status='Deviated' if deviated else 'Completed',
                    completed_at=self._at(day, template.end_time.hour, template.end_time.minute),
                ))
        for template in templates[:1]:  # today's morning milking is done
            self._add(DailyTaskLog(tenant_id=self.t, routine_id=template.id, herdsman_id=self.a.herdsman.id,
                                   issue_tag='None', status='Completed', completed_at=self._at(self.today, 7, 0)))

    # -- money -------------------------------------------------------------------------
    def _expense(self, day: date, category: TransactionCategory, amount, description: str, *,
                 method: str = 'Cash', counterparty: Optional[str] = None, cost_class: Optional[CostClass] = None,
                 hour: int = 12, cow: Optional[Cow] = None, cost_type: Optional[AnimalCostType] = None) -> Transaction:
        """A posted expense; with ``cow``, also charged to that animal (its economics report)."""
        from app.services.ledger_category_policy import default_cost_class

        stamp = self._at(day, hour, 0)
        tx = Transaction(
            tenant_id=self.t, farm_id=self.a.farm.id, transaction_type=TransactionType.EXPENSE, category=category,
            amount=_money(amount), description=description, counterparty_name=counterparty, payment_method=method,
            cost_class=cost_class or default_cost_class(category), timestamp=stamp, recorded_by=self.a.owner.id,
            payment_status=PaymentStatus.PAID.value, status=TransactionStatus.POSTED.value,
            posted_at=stamp, posted_by=self.a.owner.id,
        )
        self._add(tx)
        if cow is not None:
            self._add(AnimalCostAllocation(tenant_id=self.t, cow_id=cow.id, transaction=tx, cost_type=cost_type,
                                           amount=tx.amount, occurred_on=day, attribution_method='DIRECT'))
        return tx

    def _expenses_and_income(self) -> None:
        for day in self._history():
            if day >= self.today:
                continue
            if day.day == 3:
                self._expense(day, TransactionCategory.UTILITIES, 3200, 'Electricity (milk cooler and lights)',
                              counterparty='Power utility', method='M-Pesa')
                self._expense(day, TransactionCategory.UTILITIES, 1200, 'Water bill', counterparty='Water company',
                              method='M-Pesa')
            if day.day == 20:
                self._expense(day, TransactionCategory.TRANSPORT, 1500, 'Fuel for farm motorbike')

        for spec in _HERD:
            if spec.breeding in ('pregnant', 'pending', 'failed') and spec.bred_days_ago < HISTORY_DAYS:
                self._expense(self._day(spec.bred_days_ago), TransactionCategory.AI_SERVICE, 1500 + 1800,
                              f'AI service and straw: {spec.tag} {spec.name}', counterparty='County AI Service',
                              method='M-Pesa', cow=self.cows[spec.tag], cost_type=AnimalCostType.BREEDING)
        for days_ago, amount, what, tag in [(40, 1500, 'Pregnancy diagnosis', 'SF-004'), (26, 3500, 'Hoof treatment', 'SF-009'),
                                            (12, 1200, 'Calf scours treatment', 'SF-014'),
                                            (_TREATED_DAYS_AGO, 4800, 'Mastitis treatment', _TREATED_TAG)]:
            self._expense(self._day(days_ago), TransactionCategory.VET_FEES, amount, f'{what}: {tag} {self.cows[tag].name}',
                          counterparty='Dr. Wanjiku Mutua', method='M-Pesa', cow=self.cows[tag],
                          cost_type=AnimalCostType.VETERINARY)
        self._expense(self._day(33), TransactionCategory.EQUIPMENT_MAINTENANCE, 6500, 'Milking machine service',
                      counterparty='Dairy equipment technician', method='M-Pesa')

        sold = self._day(41)
        self._add(Transaction(
            tenant_id=self.t, farm_id=self.a.farm.id, transaction_type=TransactionType.REVENUE,
            category=TransactionCategory.LIVESTOCK_SALE, amount=_money(18000),
            description='Sold bull calf (SF-016) at 3 weeks', counterparty_name='Neighbouring farmer',
            payment_method='Cash', timestamp=self._at(sold, 14, 0), recorded_by=self.a.owner.id,
            payment_status=PaymentStatus.PAID.value, status=TransactionStatus.POSTED.value,
            posted_at=self._at(sold, 14, 0), posted_by=self.a.owner.id,
        ))
        manure = self._day(19)
        self._add(Transaction(
            tenant_id=self.t, farm_id=self.a.farm.id, transaction_type=TransactionType.REVENUE,
            category=TransactionCategory.OTHER_INCOME, amount=_money(3500), description='Manure sale (2 trailer loads)',
            payment_method='Cash', timestamp=self._at(manure, 15, 0), recorded_by=self.a.owner.id,
            payment_status=PaymentStatus.PAID.value, status=TransactionStatus.POSTED.value,
            posted_at=self._at(manure, 15, 0), posted_by=self.a.owner.id,
        ))

    # -- receipts --------------------------------------------------------------------------
    def _receipts(self) -> None:
        """Every payment and income has its receipt, as when recorded in the app, dated when it was paid.
        No PDFs: the demo can't download them, and rendering would slow the daily refresh."""
        db.session.flush()
        eligible = (Transaction.query
                    .filter(Transaction.tenant_id == self.t,
                            Transaction.transaction_type.in_([TransactionType.PAYMENT, TransactionType.REVENUE]),
                            Transaction.status == TransactionStatus.POSTED.value, Transaction.amount > 0)
                    .order_by(Transaction.timestamp, Transaction.id).all())
        for tx in eligible:
            ReceiptService.issue(tx, issued_by=self.a.owner.id, farm_id=self.a.farm.id, issued_at=tx.timestamp,
                                 render_document=False)
            self.counts['receipts'] = self.counts.get('receipts', 0) + 1


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

class DemoSeedService:
    @staticmethod
    def seed(today: Optional[date] = None) -> DemoSeedSummary:
        """Create or rebuild the demo workspace. Commits on success, rolls back on failure."""
        try:
            summary = DemoSeedService._seed_in_transaction(today or farm_today())
            db.session.commit()
            return summary
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def refresh_if_stale(today: Optional[date] = None) -> bool:
        """Rebuild the demo data if it was generated before today. Returns whether it ran.

        Only one process rebuilds at a time; others skip and serve the existing data.
        """
        today = today or farm_today()
        tenant = DemoAccount.tenant()
        if tenant is None or not DemoSeedService.is_stale(tenant, today):
            return False
        if db.engine.dialect.name == 'postgresql':
            acquired = db.session.execute(
                select(db.func.pg_try_advisory_xact_lock(_SEED_LOCK_KEY))
            ).scalar()
            if not acquired:
                db.session.rollback()
                return False
        DemoSeedService.seed(today)
        current_app.logger.info('Demo data regenerated for %s.', today.isoformat())
        return True

    @staticmethod
    def is_stale(tenant: Tenant, today: date) -> bool:
        latest = db.session.query(db.func.max(MilkLog.timestamp)).filter(MilkLog.tenant_id == tenant.id).scalar()
        if latest is None:
            return True
        return latest.astimezone(farm_timezone()).date() < today

    @staticmethod
    def _seed_in_transaction(today: date) -> DemoSeedSummary:
        accounts = DemoAccountProvisioner.ensure()
        DemoDataPurger.purge(accounts.tenant)
        db.session.flush()
        counts = DemoFarmGenerator(accounts, today).generate()
        db.session.flush()
        return DemoSeedSummary(tenant_id=accounts.tenant.id, counts=counts)
