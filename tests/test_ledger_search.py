from datetime import datetime, timezone

from app import db
from app.models.finance import Customer, Transaction, TransactionCategory, TransactionStatus, TransactionType
from app.models.user import Role
from app.utils.fuzzy_search import compact_text, edit_distance, match_names
from tests.base import BaseTestCase


class FuzzyMatchTestCase(BaseTestCase):

    def test_helpers(self):
        self.assertEqual(compact_text('Mama-Njeri '), 'mamanjeri')
        self.assertEqual(edit_distance('njeri', 'njeru'), 1)

    def test_exact_matches_win_and_are_not_reported_as_typos(self):
        rows = [(1, 'Mama Njeri Hotel'), (2, 'Kisii Dairy')]
        self.assertEqual(match_names(rows, 'njeri'), ([1], False))
        self.assertEqual(match_names(rows, 'mama-njeri'), ([1], False))

    def test_falls_back_to_close_names_only_when_nothing_matches(self):
        rows = [(1, 'Mama Njeri Hotel'), (2, 'Kisii Dairy'), (3, 'Njoro Cooperative')]
        self.assertEqual(match_names(rows, 'Njeru'), ([1], True))
        self.assertEqual(match_names(rows, 'Kisi'), ([2], False))  # substring of "Kisii"
        self.assertEqual(match_names(rows, 'Eldoret'), ([], False))


class LedgerTypoSearchTestCase(BaseTestCase):

    def setUp(self):
        super().setUp()
        self.create_user(username='ledgerfarmer', password='password', role=Role.FARMER)
        self.customer = Customer(tenant_id=self.tenant.id, name='Mama Njeri Hotel', phone_number='0700000009', status='Active')
        db.session.add(self.customer)
        db.session.commit()
        db.session.add(Transaction(
            tenant_id=self.tenant.id,
            farm_id=self.farm.id,
            customer_id=self.customer.id,
            transaction_type=TransactionType.REVENUE,
            category=TransactionCategory.MILK_SALE,
            amount=1500,
            status=TransactionStatus.POSTED.value,
            timestamp=datetime(2026, 10, 30, 7, 0, tzinfo=timezone.utc),
        ))
        db.session.commit()
        self.client.post('/api/auth/login', json={'username': 'ledgerfarmer', 'password': 'password'})

    def test_misspelt_customer_still_finds_their_transactions_and_says_so(self):
        response = self.client.get('/api/finance/ledger?search=Njeru')

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(len(body['items']), 1)
        self.assertTrue(body['summary_scope']['typo_matched'])
        self.assertEqual(body['summary_scope']['matched_names'], ['Mama Njeri Hotel'])

    def test_exact_search_is_not_flagged_as_a_typo_match(self):
        body = self.client.get('/api/finance/ledger?search=njeri').get_json()
        self.assertEqual(len(body['items']), 1)
        self.assertFalse(body['summary_scope']['typo_matched'])

    def test_unrelated_search_finds_nothing(self):
        body = self.client.get('/api/finance/ledger?search=Eldoret').get_json()
        self.assertEqual(body['items'], [])
