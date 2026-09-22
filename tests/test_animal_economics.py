import json
from datetime import date, datetime, timedelta, timezone

from app import db
from app.models.finance import AnimalCostAllocation, Buyer, SalesLedger, Transaction
from app.models.livestock import Cow, LactationCycle
from app.models.supply import MilkLog
from app.models.user import Role
from tests.base import BaseTestCase


class AnimalEconomicsAPITestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.auth_headers = self.get_auth_headers(role=Role.FARMER)
        self.user_id = self.create_user(username='milk_recorder', password='password', role=Role.FARM_HAND).id
        self.cow = Cow(tenant_id=self.tenant.id, tag_number='HF-001', name='Aster', date_of_birth=date.today() - timedelta(days=900))
        db.session.add(self.cow)
        db.session.flush()

    def test_ledger_expense_creates_direct_animal_cost_allocation(self):
        response = self.client.post('/api/finance/ledger', headers=self.auth_headers, json={
            'transaction_type': 'Expense',
            'category': 'Vet Fees',
            'amount': 1200,
            'paid_to': 'Farm Vet',
            'item_name': 'Vaccination',
            'quantity': 1,
            'animal_id': self.cow.id,
            'animal_cost_type': 'VETERINARY',
        })

        self.assertEqual(response.status_code, 201)
        allocation = AnimalCostAllocation.query.one()
        self.assertEqual(allocation.cow_id, self.cow.id)
        self.assertEqual(allocation.cost_type.value, 'VETERINARY')
        self.assertEqual(float(allocation.amount), 1200.0)
        self.assertEqual(Transaction.query.count(), 1)

    def test_report_separates_rearing_cost_and_allocates_milk_revenue(self):
        first_calving = date.today() - timedelta(days=10)
        buyer = Buyer(tenant_id=self.tenant.id, name='Dairy Buyer')
        db.session.add(buyer)
        db.session.add(LactationCycle(cow_id=self.cow.id, cycle_number=1, actual_calving_date=first_calving))
        db.session.add_all([
            Transaction(
                tenant_id=self.tenant.id,
                transaction_type='Expense', category='Feed Purchase', amount=800,
                timestamp=datetime.combine(first_calving - timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc),
                status='POSTED',
            ),
            Transaction(
                tenant_id=self.tenant.id,
                transaction_type='Expense', category='Vet Fees', amount=200,
                timestamp=datetime.combine(first_calving + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc),
                status='POSTED',
            ),
        ])
        db.session.flush()
        transactions = Transaction.query.order_by(Transaction.id).all()
        db.session.add_all([
            AnimalCostAllocation(tenant_id=self.tenant.id, cow_id=self.cow.id, transaction_id=transactions[0].id, cost_type='HEIFER_FEED', amount=800, occurred_on=first_calving - timedelta(days=1)),
            AnimalCostAllocation(tenant_id=self.tenant.id, cow_id=self.cow.id, transaction_id=transactions[1].id, cost_type='VETERINARY', amount=200, occurred_on=first_calving + timedelta(days=1)),
            MilkLog(tenant_id=self.tenant.id, cow_id=self.cow.id, amount_liters=20, session='Morning', timestamp=datetime.combine(first_calving + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc), recorded_by=self.user_id),
            MilkLog(tenant_id=self.tenant.id, cow_id=self.cow.id, amount_liters=20, session='Evening', timestamp=datetime.combine(first_calving + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc), recorded_by=self.user_id),
            SalesLedger(tenant_id=self.tenant.id, buyer_id=buyer.id, date=first_calving + timedelta(days=1), liters_sold=40, price_per_liter=50, total_amount=2000),
        ])
        db.session.commit()

        response = self.client.get(f'/api/reports/animal-economics/{self.cow.id}', headers=self.auth_headers)

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.data)
        self.assertEqual(payload['animal']['first_calving_date'], first_calving.isoformat())
        self.assertEqual(payload['rearing_cost']['amount_kes'], 800.0)
        self.assertEqual(payload['lifetime_milk_contribution']['allocated_milk_revenue_kes'], 2000.0)
        self.assertEqual(payload['lifetime_milk_contribution']['amount_kes'], 1800.0)
        self.assertEqual(payload['lifetime_net_contribution_kes'], 1000.0)
        self.assertEqual(payload['data_quality']['attribution_quality'], 'ALLOCATED')
