import json

from app import db
from app.models.livestock import DailyTaskLog
from app.models.user import Role


def _login(client, username, password='password'):
    response = client.post(
        '/api/auth/login',
        data=json.dumps({"username": username, "password": password}),
        content_type='application/json',
    )
    assert response.status_code == 200
    return json.loads(response.data.decode())['access_token']


def test_dashboard_summary_returns_data_for_tenant(client, tenant_factory, user_factory, inventory_item_factory, inventory_transaction_factory):
    tenant = tenant_factory(name='Farm A')
    _ = tenant_factory(name='Farm B')
    user = user_factory(tenant=tenant, username='farmer_a', role=Role.FARMER)
    item = inventory_item_factory(tenant=tenant, quantity=25, unit_cost=45)
    inventory_transaction_factory(item=item, transaction_type='OUT', quantity=2, unit_cost=45, logged_by=user.id)
    db.session.commit()

    token = _login(client, 'farmer_a')

    response = client.get(
        f'/api/v1/dashboard/summary?tenant_id={tenant.id}',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == 200
    payload = json.loads(response.data.decode())
    assert payload['today_feed_cost_kes'] > 0
    assert payload['net_margin_kes'] <= payload['today_revenue_kes']


def test_dashboard_rejects_cross_tenant_query(client, tenant_factory, user_factory):
    tenant_a = tenant_factory(name='Farm A')
    tenant_b = tenant_factory(name='Farm B')
    user_factory(tenant=tenant_a, username='farmer_a', role=Role.FARMER)
    db.session.commit()

    token = _login(client, 'farmer_a')

    response = client.get(
        f'/api/v1/dashboard/summary?tenant_id={tenant_b.id}',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == 403


def test_herdsman_task_complete_uses_orm_and_stays_in_tenant(client, tenant_factory, user_factory, routine_factory):
    tenant = tenant_factory(name='Farm A')
    user = user_factory(tenant=tenant, username='herdsman_a', role=Role.FARM_HAND)
    routine = routine_factory(tenant=tenant)
    db.session.commit()

    token = _login(client, 'herdsman_a')

    response = client.post(
        f'/api/v1/tasks/{routine.id}/complete',
        data=json.dumps({
            'tenant_id': tenant.id,
            'user_id': user.id,
            'issue_tag': 'None',
        }),
        content_type='application/json',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == 200
    payload = json.loads(response.data.decode())
    assert payload['message'] == 'Logged successfully.'

    logs = DailyTaskLog.query.filter_by(tenant_id=tenant.id, routine_id=routine.id, herdsman_id=user.id).all()
    assert len(logs) == 1
    assert logs[0].status == 'Completed'


def test_herdsman_rejects_cross_tenant_payload(client, tenant_factory, user_factory, routine_factory):
    tenant_a = tenant_factory(name='Farm A')
    tenant_b = tenant_factory(name='Farm B')
    user = user_factory(tenant=tenant_a, username='herdsman_a', role=Role.FARM_HAND)
    routine = routine_factory(tenant=tenant_a)
    db.session.commit()

    token = _login(client, 'herdsman_a')

    response = client.post(
        f'/api/v1/tasks/{routine.id}/complete',
        data=json.dumps({
            'tenant_id': tenant_b.id,
            'user_id': user.id,
            'issue_tag': 'None',
        }),
        content_type='application/json',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == 403


def test_herdsman_rejects_unauthorized_role(client, tenant_factory, user_factory, routine_factory):
    tenant = tenant_factory(name='Farm A')
    user = user_factory(tenant=tenant, username='customer_a', role=Role.CUSTOMER)
    routine = routine_factory(tenant=tenant)
    db.session.commit()

    token = _login(client, 'customer_a')

    response = client.post(
        f'/api/v1/tasks/{routine.id}/complete',
        data=json.dumps({
            'tenant_id': tenant.id,
            'user_id': user.id,
            'issue_tag': 'None',
        }),
        content_type='application/json',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == 403
