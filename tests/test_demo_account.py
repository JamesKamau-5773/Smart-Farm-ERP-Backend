"""Public demo account: login, read-only enforcement, isolation, rate limits, seed."""
from datetime import timedelta
from decimal import Decimal
from itertools import count

from flask_jwt_extended import decode_token
from sqlalchemy import func

from app import db
from app.models.finance import Buyer, Customer, SalesLedger, Transaction
from app.models.hr import Employee
from app.models.livestock import BreedingLog, Cow, HeatObservation
from app.models.supply import FeedRecipe, InventoryItem, MilkLog
from app.models.tenant import Tenant
from app.models.user import Role, User
from app.services.demo_access_policy import denial_for
from app.services.demo_account import DemoAccount
from app.services.demo_seed_service import DemoDataPurger, DemoSeedService
from app.utils.farm_time import farm_timezone, farm_today
from tests.base import BaseTestCase

_ips = count(1)


def _fresh_ip():
    # The limiter's memory storage outlives a single test; a new IP per test keeps them independent.
    n = next(_ips)
    return f'10.77.{n // 250}.{n % 250 + 1}'


class DemoTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        # Sessions are identified by their bearer header only; a shared cookie jar
        # would make every request use the most recent session's cookie.
        self.client = self.app.test_client(use_cookies=False)
        self.app.config['DEMO_ENABLED'] = True
        self.app.config['DEMO_SESSION_MINUTES'] = 45
        DemoSeedService.seed()
        self.demo_tenant = DemoAccount.tenant()

    def start_demo(self, ip=None):
        return self.client.post('/api/auth/demo', environ_base={'REMOTE_ADDR': ip or _fresh_ip()})

    def demo_headers(self):
        response = self.start_demo()
        self.assertEqual(response.status_code, 200, response.get_json())
        return {'Authorization': f"Bearer {response.get_json()['access_token']}"}

    def demo_cow(self, tag='SF-001'):
        return Cow.query.filter_by(tenant_id=self.demo_tenant.id, tag_number=tag).one()


class DemoLoginTests(DemoTestCase):
    def test_demo_login_starts_a_flagged_read_only_session(self):
        response = self.start_demo()

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body['is_demo'])
        self.assertTrue(body['read_only'])
        self.assertEqual(body['tenant_name'], 'Silato Farm')
        self.assertEqual(body['farm_name'], 'Silato Farm')
        self.assertIn('session_expires_at', body)
        # Same session machinery as a normal login: the httpOnly access cookie.
        cookies = response.headers.getlist('Set-Cookie')
        self.assertTrue(any(c.startswith('access_token_cookie=') for c in cookies), cookies)

        me = self.client.get('/api/auth/me', headers={'Authorization': f"Bearer {body['access_token']}"})
        self.assertEqual(me.status_code, 200)
        me_body = me.get_json()
        self.assertTrue(me_body['is_demo'])
        self.assertTrue(me_body['read_only'])
        self.assertEqual(me_body['session_expires_at'], body['session_expires_at'])
        self.assertNotIn('member_admin', me_body['page_access'])

    def test_demo_session_is_short_lived(self):
        token = self.start_demo().get_json()['access_token']
        claims = decode_token(token)
        self.assertEqual(claims['exp'] - claims['iat'], 45 * 60)
        self.assertEqual(claims['amr'], 'demo')

    def test_normal_users_are_not_flagged(self):
        headers = self.get_auth_headers(Role.FARMER)
        body = self.client.get('/api/auth/me', headers=headers).get_json()
        self.assertFalse(body['is_demo'])
        self.assertFalse(body['read_only'])

    def test_demo_user_cannot_log_in_through_the_normal_route(self):
        response = self.client.post('/api/auth/login', json={
            'username': DemoAccount.OWNER_USERNAME, 'password': 'anything-at-all',
        }, environ_base={'REMOTE_ADDR': _fresh_ip()})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()['code'], 'INVALID_CREDENTIALS')

    def test_demo_user_cannot_log_in_even_with_a_known_password(self):
        owner = DemoAccount.owner()
        self.assertFalse(owner.has_password)
        owner.set_password('LeakedPass123')  # simulate a leaked or mistakenly set password
        db.session.commit()

        response = self.client.post('/api/auth/login', json={
            'username': DemoAccount.OWNER_USERNAME, 'password': 'LeakedPass123',
        }, environ_base={'REMOTE_ADDR': _fresh_ip()})
        self.assertEqual(response.status_code, 401)

    def test_endpoint_returns_404_when_demo_is_disabled(self):
        self.app.config['DEMO_ENABLED'] = False
        response = self.start_demo()
        self.assertEqual(response.status_code, 404)

    def test_endpoint_returns_503_when_demo_is_not_seeded(self):
        DemoAccount.owner().is_demo = False  # owner lookup requires the flag
        db.session.commit()
        response = self.start_demo()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()['code'], 'DEMO_UNAVAILABLE')

    def test_demo_login_is_rate_limited_per_ip(self):
        ip = _fresh_ip()
        statuses = [self.start_demo(ip).status_code for _ in range(6)]
        self.assertEqual(statuses, [200] * 5 + [429])
        self.assertEqual(self.start_demo(ip).get_json()['code'], 'RATE_LIMITED')
        # Another visitor is unaffected.
        self.assertEqual(self.start_demo(_fresh_ip()).status_code, 200)

    def test_logout_ends_only_this_demo_session(self):
        first = self.demo_headers()
        second = self.demo_headers()

        self.assertEqual(self.client.post('/api/auth/logout', headers=first).status_code, 200)

        self.assertEqual(self.client.get('/api/auth/me', headers=first).status_code, 401)
        self.assertEqual(self.client.get('/api/auth/me', headers=second).status_code, 200)


class DemoReadOnlyTests(DemoTestCase):
    def _write_requests(self):
        cow = self.demo_cow()
        customer = Customer.query.filter_by(tenant_id=self.demo_tenant.id).first()
        buyer = Buyer.query.filter_by(tenant_id=self.demo_tenant.id).first()
        item = InventoryItem.query.filter_by(tenant_id=self.demo_tenant.id).first()
        employee = Employee.query.filter_by(tenant_id=self.demo_tenant.id).first()
        breeding = BreedingLog.query.filter_by(tenant_id=self.demo_tenant.id).first()
        return [
            # account and workspace
            ('PATCH', '/api/auth/me', {'name': 'Hacked'}),
            ('POST', '/api/auth/change-password', {'new_password': 'NewPass12345'}),
            ('POST', '/api/auth/switch-farm', {'farm_id': 'farm_1'}),
            ('POST', '/api/auth/phone/verification', {'phone_number': '+254700000000'}),
            ('DELETE', '/api/auth/social/google', None),
            ('POST', '/api/tenant/members/invite', {'phone_number': '+254700000001'}),
            ('POST', '/api/tenant/cooperatives', {'name': 'Coop'}),
            ('POST', '/api/onboarding/invite', {}),
            ('POST', f'/api/hr/staff/{employee.id}/account-invite', {}),
            ('PATCH', f'/api/hr/staff/{employee.id}/page-access', {'page_access': ['herd']}),
            # farm data
            ('POST', '/api/v1/breeding/heat-observations', {'cow_id': cow.id}),
            ('PATCH', f'/api/v1/breeding/insemination/{breeding.id}/outcome', {'status': 'Failed'}),
            ('PUT', f'/api/clinical/cows/{cow.id}/hardlock', {'is_hardlocked': True}),
            ('POST', '/api/safety/milk-tests', {'cow_id': cow.id}),
            ('POST', '/api/production/milk-dispositions', {'liters': 2}),
            ('POST', f'/api/finance/customers/{customer.id}/payments', {'amount': 100}),
            ('POST', f'/api/finance/buyers/{buyer.id}/payments', {'amount': 100}),
            ('PATCH', f'/api/finance/customers/{customer.id}', {'name': 'X'}),
            ('POST', '/api/finance/ledger', {'amount': 10}),
            ('POST', '/api/inventory/items', {'name': 'Salt'}),
            ('PATCH', f'/api/inventory/items/{item.id}', {'name': 'Renamed'}),
            ('DELETE', f'/api/inventory/items/{item.id}', None),
            ('POST', '/api/hr/staff', {'full_name': 'New Hire'}),
            ('POST', '/api/hr/payroll', {}),
            # verbs a route does not even define are refused the same way
            ('PUT', f'/api/herd/{cow.id}', {'name': 'X'}),
            ('DELETE', f'/api/herd/{cow.id}', None),
            ('PATCH', '/api/does-not-exist', {}),
        ]

    def _snapshot(self):
        t = self.demo_tenant.id
        return {
            model.__tablename__: model.query.filter_by(tenant_id=t).count()
            for model in (Cow, Customer, Buyer, Transaction, InventoryItem, Employee, BreedingLog, HeatObservation, MilkLog)
        } | {'users': User.query.count(), 'owner_name': DemoAccount.owner().name}

    def test_every_write_verb_is_rejected_for_a_demo_session(self):
        headers = self.demo_headers()
        before = self._snapshot()

        for method, path, body in self._write_requests():
            with self.subTest(method=method, path=path):
                response = self.client.open(path, method=method, json=body, headers=headers)
                self.assertEqual(response.status_code, 403, response.get_data(as_text=True))
                payload = response.get_json()
                self.assertEqual(payload['code'], 'DEMO_READ_ONLY')
                self.assertTrue(payload['demo'])

        db.session.expire_all()
        self.assertEqual(self._snapshot(), before)

    def test_the_same_writes_are_not_blocked_by_the_guard_for_normal_users(self):
        headers = self.get_auth_headers(Role.FARMER)
        response = self.client.post('/api/inventory/items', json={
            'name': 'Salt lick', 'category': 'Supplement', 'unit': 'kg', 'minimum_threshold': 1,
        }, headers=headers)
        self.assertNotEqual(response.get_json().get('code'), 'DEMO_READ_ONLY')

    def test_exports_and_account_linking_are_unavailable(self):
        headers = self.demo_headers()
        cow = self.demo_cow()
        for path in (
            f'/api/v1/export/animal/{cow.id}/pdf',
            '/api/finance/receipts/1/pdf',
            '/api/hr/payroll/runs/1/payslips/1.pdf',
            '/api/auth/google/start?intent=link',
        ):
            with self.subTest(path=path):
                response = self.client.get(path, headers=headers)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.get_json()['code'], 'DEMO_FEATURE_UNAVAILABLE')

    def test_demo_session_can_read_every_module(self):
        headers = self.demo_headers()
        cow = self.demo_cow()
        for path in (
            '/api/auth/me',
            '/api/herd',
            f'/api/herd/{cow.id}',
            f'/api/animals/{cow.id}/milk-history',
            '/api/production/yield',
            '/api/production/summary',
            '/api/v1/dashboard/summary',
            '/api/breeding',
            '/api/operations/breeding/performance',
            '/api/operations/semen-inventory',
            '/api/medical/records',
            '/api/safety/dashboard',
            '/api/finance/buyers',
            '/api/finance/customers',
            '/api/finance/ledger',
            '/api/inventory/items',
            '/api/inventory/stock',
            '/api/ledger/summary',
            '/api/production/milk-dispositions',
            '/api/v1/nutrition/herd/feeding-plan/by-group',
            '/api/reports/dairy-unit-economics',
            '/api/v1/nutrition/recipes',
            '/api/v1/nutrition/feeding-groups/profiles',
            '/api/v1/herd/yield-targets',
            '/api/routine/plans',
            '/api/hr/staff',
            '/api/hr/payroll-records',
            '/api/tenant/profile',
        ):
            with self.subTest(path=path):
                response = self.client.get(path, headers=headers)
                self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:300])


class DemoIsolationTests(DemoTestCase):
    def setUp(self):
        super().setUp()
        other = self.create_tenant(name='Private Farm')
        self.create_farm(tenant=other, name='Private Farm')
        self.other_cow = Cow(tenant_id=other.id, tag_number='PRIV-1', name='Secret',
                             date_of_birth=farm_today() - timedelta(days=900))
        self.other_buyer = Buyer(tenant_id=other.id, name='Private Buyer', agreed_rate_per_liter=Decimal('50'))
        db.session.add_all([self.other_cow, self.other_buyer])
        db.session.commit()

    def test_demo_session_cannot_read_another_farm(self):
        headers = self.demo_headers()

        detail = self.client.get(f'/api/herd/{self.other_cow.id}', headers=headers)
        self.assertIn(detail.status_code, (403, 404))

        herd = self.client.get('/api/herd', headers=headers).get_data(as_text=True)
        self.assertNotIn('PRIV-1', herd)
        self.assertIn('SF-001', herd)

        buyers = self.client.get('/api/finance/buyers', headers=headers).get_data(as_text=True)
        self.assertNotIn('Private Buyer', buyers)

    def test_demo_session_cannot_switch_workspace(self):
        headers = self.demo_headers()
        response = self.client.post('/api/auth/switch-farm', json={'farm_id': 'farm_1'}, headers=headers)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()['code'], 'DEMO_READ_ONLY')


class DemoSeedTests(DemoTestCase):
    def _counts(self):
        t = self.demo_tenant.id
        return {
            model.__tablename__: model.query.filter_by(tenant_id=t).count()
            for model in (Cow, MilkLog, BreedingLog, HeatObservation, FeedRecipe, InventoryItem,
                          Buyer, Customer, SalesLedger, Transaction, Employee)
        } | {'users': User.query.filter_by(tenant_id=t).count(), 'tenants': Tenant.query.filter_by(is_demo=True).count()}

    def test_seed_can_run_twice_without_duplicating_data(self):
        first = self._counts()
        DemoSeedService.seed()
        db.session.expire_all()
        self.assertEqual(self._counts(), first)
        self.assertEqual(first['cows'], 15)
        self.assertEqual(first['tenants'], 1)

    def test_seed_never_touches_other_tenants(self):
        other = self.create_tenant(name='Neighbour')
        db.session.add(Cow(tenant_id=other.id, tag_number='N-1', date_of_birth=farm_today() - timedelta(days=800)))
        db.session.commit()

        DemoSeedService.seed()

        self.assertEqual(Cow.query.filter_by(tenant_id=other.id).count(), 1)

    def test_purge_refuses_a_real_tenant(self):
        with self.assertRaises(RuntimeError):
            DemoDataPurger.purge(self.tenant)

    def test_daily_milk_is_forty_to_fifty_litres(self):
        tz = farm_timezone()
        totals = {}
        for log in MilkLog.query.filter_by(tenant_id=self.demo_tenant.id).all():
            day = log.timestamp.astimezone(tz).date()
            totals[day] = totals.get(day, Decimal('0')) + log.amount_liters
        today = farm_today()
        full_days = {day: total for day, total in totals.items() if day < today}
        self.assertGreaterEqual(len(full_days), 60)
        self.assertGreaterEqual(min(full_days), today - timedelta(days=90))
        for day, total in full_days.items():
            self.assertTrue(36 <= total <= 54, f'{day}: {total} L')
        average = sum(full_days.values()) / len(full_days)
        self.assertTrue(40 <= average <= 50, average)

    def test_data_is_dated_relative_to_today(self):
        latest = db.session.query(func.max(MilkLog.timestamp)).filter_by(tenant_id=self.demo_tenant.id).scalar()
        self.assertEqual(latest.astimezone(farm_timezone()).date(), farm_today())
        self.assertFalse(DemoSeedService.is_stale(self.demo_tenant, farm_today()))

    def test_stale_data_is_regenerated_once(self):
        yesterday = farm_today() - timedelta(days=1)
        DemoSeedService.seed(today=yesterday)
        self.assertTrue(DemoSeedService.is_stale(DemoAccount.tenant(), farm_today()))

        self.assertTrue(DemoSeedService.refresh_if_stale())
        self.assertFalse(DemoSeedService.refresh_if_stale())

    def test_buyers_have_outstanding_balances(self):
        headers = self.demo_headers()
        buyers = self.client.get('/api/finance/buyers', headers=headers).get_json()
        self.assertTrue(buyers)
        self.assertTrue(any(b['current_balance'] > 0 for b in buyers), buyers)

    def test_demo_accounts_have_no_contact_details_or_password(self):
        for user in User.query.filter_by(tenant_id=self.demo_tenant.id).all():
            self.assertTrue(user.is_demo)
            self.assertIsNone(user.email)
            self.assertIsNone(user.phone_number)
            self.assertFalse(user.has_password)


class DemoCompletenessTests(DemoTestCase):
    """Every page and chart has something to show in the demo (one test: seeding is slow)."""

    def test_every_page_and_chart_has_data(self):
        headers = self.demo_headers()

        def get(path):
            response = self.client.get(f'/api/{path}', headers=headers)
            self.assertEqual(response.status_code, 200, (path, response.get_json()))
            return response.get_json()

        # Command Center: today's takings and feed cost are on the ledger.
        summary = get('production/summary')
        self.assertGreater(summary['revenue_total_kes'], 0)
        self.assertGreater(summary['feed_cost_total_kes'], 0)
        self.assertGreaterEqual(summary['anomaly_count'], 1)

        # Ledger: every payment and income has a receipt the preview can open.
        ledger = get('finance/ledger?per_page=200')['items']
        paid = [row for row in ledger if row['transaction_type'] in ('Payment', 'Revenue')]
        self.assertTrue(paid)
        self.assertTrue(all(row['receipt_available'] and row['receipt'] for row in paid), paid[:2])
        receipt = get(f"finance/receipts/{paid[0]['receipt']['id']}")
        self.assertTrue(receipt['receipt_number'].startswith('RCPT-'))
        self.assertTrue(any(row['animal_cost_allocations'] for row in ledger))

        # Breeding: genetic progress over several birth years.
        progress = get('herd/genetic-progress')['items']
        self.assertGreaterEqual(len(progress), 3)
        self.assertTrue(all(point['daughters_yield'] > point['mothers_yield'] for point in progress), progress)

        # Cow details: timeline and charged costs.
        cow = self.demo_cow('SF-005')
        self.assertGreater(get(f'animals/{cow.id}/events')['meta']['total'], 2)
        self.assertTrue(get(f'reports/animal-economics/{cow.id}')['costs_by_type_kes'])

        # Payroll, feed batches, milk drop alerts, unit helpers.
        runs = get('hr/payroll/runs/summary')['runs']
        self.assertEqual(len(runs), 3)
        self.assertEqual(len(get('v1/nutrition/feeding/today')['active_batches']), 2)
        self.assertTrue(get('v1/nutrition/analytics/feed-cost-efficiency')['rows'])
        self.assertTrue(get('v1/nutrition/analytics/active-batch-roi-trend-weekly')['rows'])
        self.assertEqual(len(get('production/milk-drop-alerts')['items']), 2)
        self.assertTrue(get('units/conversions'))
        self.assertTrue(get('tenant/profile')['registration_number'])

    def test_receipt_pdfs_stay_unavailable_in_the_demo(self):
        headers = self.demo_headers()
        ledger = self.client.get('/api/finance/ledger?per_page=50', headers=headers).get_json()['items']
        receipt_id = next(row['receipt']['id'] for row in ledger if row['receipt'])
        response = self.client.get(f'/api/finance/receipts/{receipt_id}/pdf', headers=headers)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()['code'], 'DEMO_FEATURE_UNAVAILABLE')

class DemoAccessPolicyTests(BaseTestCase):
    """The pure decision function, independent of HTTP."""

    def test_writes_are_refused_except_session_and_anonymous_routes(self):
        for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            with self.subTest(method=method):
                denial = denial_for(method=method, endpoint='herd.update', path='/api/herd/1')
                self.assertEqual(denial.code, 'DEMO_READ_ONLY')
        for endpoint in ('auth.logout', 'auth.login', 'auth_demo.start_demo_session', 'auth_recovery.forgot_password'):
            with self.subTest(endpoint=endpoint):
                self.assertIsNone(denial_for(method='POST', endpoint=endpoint, path='/api/auth/x'))

    def test_reads_are_allowed_except_exports_and_admin(self):
        self.assertIsNone(denial_for(method='GET', endpoint='herd.list', path='/api/herd'))
        self.assertIsNone(denial_for(method='OPTIONS', endpoint=None, path='/api/v1/export/animal/1/pdf'))
        for path in ('/api/v1/export/animal/1/pdf', '/api/finance/receipts/3/pdf', '/api/tenant/members',
                     '/api/onboarding/provision'):
            with self.subTest(path=path):
                self.assertEqual(denial_for(method='GET', endpoint='x', path=path).code, 'DEMO_FEATURE_UNAVAILABLE')
        self.assertIsNone(denial_for(method='GET', endpoint='tenant.profile', path='/api/tenant/profile'))
