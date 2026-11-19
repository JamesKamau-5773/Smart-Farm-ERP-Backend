"""Period totals API: classification, local-day bucketing, reconciliation, tenancy, validation."""
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from app import db
from app.models.finance import Customer, Transaction, TransactionCategory, TransactionStatus, TransactionType
from app.models.livestock import Cow
from app.models.supply import MilkDisposition, MilkDispositionType, MilkLog
from app.models.user import Role
from tests.base import BaseTestCase

UTC = timezone.utc
TODAY = date(2026, 11, 20)


def utc(*args):
    return datetime(*args, tzinfo=UTC)


class PeriodTotalsTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.farmer = self.create_user(username='farmer_a', password='password', role=Role.FARMER)
        self.headers = self._login('farmer_a')

        self.other_tenant = self.create_tenant(name='Other Tenant')
        self.other_farm = self.create_farm(tenant=self.other_tenant, name='Other Farm')
        db.session.commit()
        self.other_farmer = self.create_user(
            username='farmer_b', password='password', role=Role.FARMER, tenant=self.other_tenant,
        )
        self.other_headers = self._login('farmer_b')

        self.customer = Customer(tenant_id=self.tenant.id, name='Mama Njeri', phone_number='254700000001')
        db.session.add(self.customer)
        db.session.flush()
        self._seed_ledger()
        self._seed_milk()
        db.session.commit()

        today_patch = patch('app.api.period_totals.farm_today', return_value=TODAY)
        service_today_patch = patch('app.services.period_totals_service.farm_today', return_value=TODAY)
        today_patch.start()
        service_today_patch.start()
        self.addCleanup(today_patch.stop)
        self.addCleanup(service_today_patch.stop)

    def _login(self, username):
        # A fresh client per user: login also sets JWT cookies, which would leak between users.
        client = self.app.test_client()
        response = client.post('/api/auth/login', json={'username': username, 'password': 'password'})
        self.assertEqual(response.status_code, 200, response.get_json())
        return {'Authorization': f"Bearer {response.get_json()['access_token']}"}

    def _tx(self, transaction_type, amount, timestamp, *, tenant=None, farm=None, status=TransactionStatus.POSTED,
            category=None, **extra):
        tenant = tenant or self.tenant
        farm = farm or self.farm
        default_category = {
            TransactionType.REVENUE: TransactionCategory.MILK_SALE,
            TransactionType.EXPENSE: TransactionCategory.FEED_PURCHASE,
            TransactionType.PAYMENT: TransactionCategory.PAYMENT,
            TransactionType.DEBIT: TransactionCategory.MILK_SALE,
            TransactionType.CREDIT: TransactionCategory.MILK_SALE,
        }[transaction_type]
        db.session.add(Transaction(
            tenant_id=tenant.id, farm_id=farm.id, transaction_type=transaction_type,
            category=category or default_category, amount=Decimal(str(amount)), timestamp=timestamp,
            status=status.value, **extra,
        ))

    def _seed_ledger(self):
        T = TransactionType
        # November 2026 (farm-local), farm A
        self._tx(T.REVENUE, '1000.00', utc(2026, 11, 2, 9))
        self._tx(T.PAYMENT, '500.00', utc(2026, 11, 3, 9), customer_id=self.customer.id)
        self._tx(T.EXPENSE, '300.00', utc(2026, 11, 3, 10))
        self._tx(T.EXPENSE, '-200.00', utc(2026, 11, 10, 10))      # legacy negative-sign expense
        self._tx(T.DEBIT, '400.00', utc(2026, 11, 4, 9), customer_id=self.customer.id)  # unpaid
        self._tx(T.CREDIT, '50.00', utc(2026, 11, 4, 10), customer_id=self.customer.id)
        self._tx(T.REVENUE, '9999.00', utc(2026, 11, 5, 9), status=TransactionStatus.VOIDED)
        self._tx(T.REVENUE, '70.00', utc(2026, 11, 30, 20, 30))    # 23:30 EAT on 30 Nov
        self._tx(T.REVENUE, '25.00', utc(2026, 10, 31, 21, 30))    # 00:30 EAT on 1 Nov
        # October 2026
        self._tx(T.REVENUE, '800.00', utc(2026, 10, 20, 9))
        self._tx(T.EXPENSE, '100.00', utc(2026, 10, 21, 9))
        # Another tenant's farm: must never be visible to farm A
        self._tx(T.REVENUE, '5000.00', utc(2026, 11, 2, 9), tenant=self.other_tenant, farm=self.other_farm)

    def _cow(self, tenant, tag):
        cow = Cow(tenant_id=tenant.id, tag_number=tag, date_of_birth=date(2021, 1, 1))
        db.session.add(cow)
        db.session.flush()
        return cow

    def _milk(self, cow, litres, timestamp, session, tenant=None, recorded_by=None):
        db.session.add(MilkLog(
            tenant_id=(tenant or self.tenant).id, cow_id=cow.id, amount_liters=Decimal(litres),
            session=session, timestamp=timestamp, recorded_by=recorded_by or self.farmer.id,
        ))

    def _seed_milk(self):
        cow1, cow2 = self._cow(self.tenant, 'A1'), self._cow(self.tenant, 'A2')
        self._milk(cow1, '12.00', utc(2026, 11, 6, 5), 'Morning')
        self._milk(cow1, '10.50', utc(2026, 11, 6, 20, 30), 'Evening')   # 23:30 EAT, still 6 Nov
        self._milk(cow2, '8.00', utc(2026, 11, 6, 5, 10), 'Morning')
        self._milk(cow1, '5.00', utc(2026, 11, 7, 21, 30), 'Midday')     # 00:30 EAT on 8 Nov
        self._milk(cow1, '20.00', utc(2026, 10, 10, 5), 'Morning')
        other_cow = self._cow(self.other_tenant, 'B1')
        self._milk(other_cow, '99.00', utc(2026, 11, 6, 5), 'Morning', tenant=self.other_tenant,
                   recorded_by=self.other_farmer.id)

    def _get(self, url, headers=None):
        response = self.app.test_client().get(url, headers=headers or self.headers)
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    # --- ledger -----------------------------------------------------------------

    def test_ledger_month_summary_separates_income_expenses_unpaid_and_credit(self):
        body = self._get('/api/ledger/summary?period=month&anchor=2026-11-15')
        self.assertEqual((body['period'], body['key'], body['label']), ('month', '2026-11', 'Nov 2026'))
        self.assertEqual(body['range'], {'from': '2026-11-01', 'to': '2026-11-30'})
        self.assertFalse(body['has_next'])
        self.assertEqual(body['current'], {
            'income': '159500',      # 1000 revenue + 500 payment + 70 + 25; voided 9999 excluded
            'expenses': '50000',     # 300 + |-200|
            'net': '109500',
            'unpaid': '40000',       # debit, never inside income
            'credit': '5000',
            'count': 9,
        })
        self.assertEqual(body['previous'], {
            'key': '2026-10', 'label': 'Oct 2026',
            'income': '80000', 'expenses': '10000', 'net': '70000', 'unpaid': '0', 'credit': '0', 'count': 2,
        })
        self.assertEqual(body['change'], {'net_abs': '39500', 'net_pct': '56.4'})
        self.assertEqual([item['key'] for item in body['breakdown']],
                         ['2026-W44', '2026-W45', '2026-W46', '2026-W47', '2026-W48', '2026-W49'])
        self.assertEqual(body['breakdown'][0], {
            'key': '2026-W44', 'label': '26 Oct – 1 Nov', 'income': '2500', 'expenses': '0', 'net': '2500',
        })

    def test_ledger_entry_at_local_midnight_boundaries_lands_on_local_day(self):
        groups = self._get('/api/ledger/group-totals?levels=day&date_from=2026-10-31&date_to=2026-11-30')['groups']
        by_key = {group['key']: group for group in groups}
        self.assertNotIn('2026-10-31', by_key)
        self.assertEqual(by_key['2026-11-01']['income'], '2500')
        self.assertEqual(by_key['2026-11-30']['income'], '7000')
        self.assertEqual(by_key['2026-11-30']['label'], 'Nov 30, 2026')

        items = self._get('/api/finance/ledger?per_page=100')['items']
        late = next(item for item in items if item['amount'] == 70.0)
        self.assertEqual(late['bucket'], {'year': '2026', 'month': '2026-11', 'week': '2026-W49', 'day': '2026-11-30'})
        early = next(item for item in items if item['amount'] == 25.0)
        self.assertEqual(early['bucket']['day'], '2026-11-01')

    def test_reconciliation_summary_equals_day_groups_equals_kpi_cards(self):
        summary = self._get('/api/ledger/summary?period=month&anchor=2026-11-01')['current']
        days = [
            group for group in self._get(
                '/api/ledger/group-totals?levels=month,day&date_from=2026-11-01&date_to=2026-11-30'
            )['groups'] if group['level'] == 'day'
        ]
        for field in ('income', 'expenses', 'net', 'unpaid', 'credit'):
            self.assertEqual(sum(int(day[field]) for day in days), int(summary[field]), field)
        self.assertEqual(sum(day['count'] for day in days), summary['count'])

        kpi = self._get('/api/finance/ledger?date_from=2026-11-01&date_to=2026-11-30')['summary']
        self.assertEqual(round(kpi['recognized_sales'] * 100), int(summary['income']))
        self.assertEqual(round(kpi['posted_costs'] * 100), int(summary['expenses']))
        self.assertEqual(round(kpi['net_profit'] * 100), int(summary['net']))
        self.assertEqual(kpi['ledger_records'], summary['count'])

    def test_kpi_cards_send_profit_margin_as_one_dp_string(self):
        # November: income 1,595, expenses 500, net 1,095 -> 68.652...% -> "68.7"
        kpi = self._get('/api/finance/ledger?date_from=2026-11-01&date_to=2026-11-30')['summary']
        self.assertEqual(kpi['profit_margin_pct'], '68.7')

        # Expenses only (21 Oct): no sales, so no margin
        kpi = self._get('/api/finance/ledger?date_from=2026-10-21&date_to=2026-10-21')['summary']
        self.assertEqual(kpi['recognized_sales'], 0)
        self.assertIsNone(kpi['profit_margin_pct'])

        # No sales at all: null, never a division by zero
        kpi = self._get('/api/finance/ledger?date_from=2026-01-01&date_to=2026-01-31')['summary']
        self.assertIsNone(kpi['profit_margin_pct'])

    def test_group_totals_hierarchy_splits_weeks_across_months(self):
        groups = self._get('/api/ledger/group-totals?levels=year,month,week,day')['groups']
        self.assertEqual(groups[0], {
            'level': 'year', 'key': '2026', 'label': '2026', 'count': 11,
            'income': '239500', 'expenses': '60000', 'net': '179500', 'unpaid': '40000', 'credit': '5000',
        })
        months = [group for group in groups if group['level'] == 'month']
        self.assertEqual([(m['key'], m['parent'], m['label']) for m in months],
                         [('2026-11', '2026', 'November'), ('2026-10', '2026', 'October')])
        w44 = [group for group in groups if group['level'] == 'week' and group['key'] == '2026-W44']
        self.assertEqual([(w['parent'], w['income']) for w in w44], [('2026-11', '2500')])
        day = next(group for group in groups if group['key'] == '2026-11-03')
        self.assertEqual(day['parent'], '2026-W45')
        self.assertEqual((day['income'], day['expenses'], day['count']), ('50000', '30000', 2))

    def test_ledger_filters_apply_to_totals(self):
        expense_only = self._get('/api/ledger/summary?period=month&anchor=2026-11-01&type=expense')['current']
        self.assertEqual((expense_only['income'], expense_only['expenses'], expense_only['count']), ('0', '50000', 2))
        by_customer = self._get('/api/ledger/summary?period=month&anchor=2026-11-01&search=Njeri')['current']
        self.assertEqual((by_customer['income'], by_customer['unpaid'], by_customer['credit']), ('50000', '40000', '5000'))
        clipped = self._get('/api/ledger/summary?period=month&anchor=2026-11-01&date_to=2026-11-02')['current']
        self.assertEqual(clipped['income'], '102500')

    def test_ledger_tenancy_farm_a_never_sees_farm_b(self):
        mine = self._get('/api/ledger/summary?period=month&anchor=2026-11-01')['current']
        theirs = self._get('/api/ledger/summary?period=month&anchor=2026-11-01', self.other_headers)['current']
        self.assertEqual(theirs['income'], '500000')
        self.assertEqual(theirs['count'], 1)
        self.assertEqual(mine['income'], '159500')
        their_groups = self._get('/api/ledger/group-totals?levels=year', self.other_headers)['groups']
        self.assertEqual([(g['key'], g['income']) for g in their_groups], [('2026', '500000')])

    # --- production -----------------------------------------------------------------

    def test_production_month_summary(self):
        body = self._get('/api/production/summary?period=month&anchor=2026-11-20')
        self.assertEqual((body['key'], body['label']), ('2026-11', 'Nov 2026'))
        self.assertEqual(body['current'], {
            'litres': '35.5', 'entries': 4, 'milking_days': 2,
            'avg_litres_per_day': '17.8', 'avg_litres_per_cow_day': '11.8',
            'fed_to_calves_litres': '0.0', 'available_litres': '35.5', 'last_entry_date': '2026-11-08',
        })
        self.assertEqual(body['previous']['litres'], '20.0')
        self.assertEqual(body['change'], {
            'litres_abs': '15.5', 'litres_pct': '77.5', 'avg_litres_per_day_pct': '-11.3',
            'entries_pct': '300.0', 'fed_to_calves_pct': None, 'available_pct': '77.5',
        })
        breakdown = {item['key']: item for item in body['breakdown']}
        self.assertEqual(len(breakdown), 30)
        self.assertEqual(breakdown['2026-11-06'], {'key': '2026-11-06', 'label': 'Fri 6', 'litres': '30.5'})
        self.assertEqual(breakdown['2026-11-07']['litres'], '0.0')
        self.assertEqual(breakdown['2026-11-08']['litres'], '5.0')

    def test_production_summary_reports_calf_feeding_and_last_entry(self):
        calf = self._cow(self.tenant, 'CALF1')
        for day, litres in ((date(2026, 11, 6), '3.00'), (date(2026, 10, 10), '2.00')):
            db.session.add(MilkDisposition(
                tenant_id=self.tenant.id, disposition_type=MilkDispositionType.CALF_FEED, disposition_date=day,
                liters=Decimal(litres), calf_id=calf.id, recorded_by=self.farmer.id,
            ))
        db.session.commit()

        body = self._get('/api/production/summary?period=month&anchor=2026-11-20')
        current, previous, change = body['current'], body['previous'], body['change']
        self.assertEqual((current['fed_to_calves_litres'], current['available_litres']), ('3.0', '32.5'))
        self.assertEqual((previous['fed_to_calves_litres'], previous['available_litres']), ('2.0', '18.0'))
        self.assertNotIn('last_entry_date', previous)
        self.assertEqual((change['fed_to_calves_pct'], change['available_pct']), ('50.0', '80.6'))

        # Calf feedings can't be matched to one session, so they are left out rather than misreported.
        morning = self._get('/api/production/summary?period=month&anchor=2026-11-20&session=Morning')
        self.assertEqual((morning['current']['fed_to_calves_litres'], morning['current']['available_litres'],
                          morning['change']['available_pct']), (None, None, None))

        empty_week = self._get('/api/production/summary?period=week&anchor=2026-10-20')
        self.assertEqual((empty_week['current']['entries'], empty_week['current']['last_entry_date']), (0, '2026-11-08'))

    def test_evening_milking_at_2330_local_lands_on_same_local_day(self):
        groups = self._get('/api/production/group-totals?levels=day')['groups']
        by_key = {group['key']: group for group in groups}
        self.assertEqual(by_key['2026-11-06'], {
            'level': 'day', 'key': '2026-11-06', 'label': 'Nov 06, 2026',
            'litres': '30.5', 'entries': 3, 'avg_litres_per_day': '30.5',
        })
        self.assertNotIn('2026-11-07', by_key)
        rows = self._get('/api/production/yield?per_page=100')['items']
        evening = next(row for row in rows if row['session'] == 'Evening')
        self.assertEqual(evening['milkingDate'], '2026-11-06')
        self.assertEqual(evening['bucket']['day'], '2026-11-06')

    def test_production_tenancy_and_legacy_summary(self):
        theirs = self._get('/api/production/summary?period=month&anchor=2026-11-01', self.other_headers)['current']
        self.assertEqual((theirs['litres'], theirs['entries']), ('99.0', 1))
        legacy = self._get('/api/production/summary')
        self.assertIn('production_total_liters', legacy)

    # --- validation -----------------------------------------------------------------

    def test_invalid_period_or_anchor_returns_422(self):
        for url in (
            '/api/ledger/summary?period=decade',
            '/api/ledger/summary?period=month&anchor=2026-13-01',
            '/api/production/summary?period=fortnight',
            '/api/production/summary?period=week&anchor=not-a-date',
            '/api/ledger/group-totals?levels=century',
            '/api/production/group-totals?levels=day,hour',
        ):
            response = self.app.test_client().get(url, headers=self.headers)
            self.assertEqual(response.status_code, 422, url)
            self.assertIn(response.get_json()['code'], ('INVALID_PERIOD', 'INVALID_ANCHOR', 'INVALID_LEVELS'))
            self.assertIn('error', response.get_json())

    def test_requires_authentication(self):
        self.assertEqual(self.app.test_client().get('/api/ledger/summary').status_code, 401)
