from datetime import date, time

import pytest

from app import create_app, db
from app.models.farm import Farm
from app.models.livestock import HerdsmanRoutineTemplate
from app.models.supply import InventoryItem, InventoryTransaction, MilkLog
from app.models.tenant import Tenant
from app.models.user import User
from config import TestConfig


@pytest.fixture
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.session.remove()
        db.drop_all()
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def tenant_factory(app):
    def _create(*, name='Tenant', tenant_type='single'):
        tenant = Tenant(name=name, tenant_type=tenant_type)
        db.session.add(tenant)
        db.session.flush()
        return tenant

    return _create


@pytest.fixture
def farm_factory(app):
    def _create(*, tenant, name='Farm'):
        farm = Farm(tenant_id=tenant.id, name=name)
        db.session.add(farm)
        db.session.flush()
        return farm

    return _create


@pytest.fixture
def user_factory(app):
    def _create(*, tenant, username, password='password', role='FARMER', name=None, email=None, identifier=None):
        user = User(
            tenant_id=tenant.id,
            identifier=identifier or f'{username}_id',
            username=username,
            name=name or username,
            email=email or f'{username}@example.com',
            role=role,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()
        return user

    return _create


@pytest.fixture
def routine_factory(app):
    def _create(*, tenant, task_title='Morning milking', display_order=1, is_active=True):
        routine = HerdsmanRoutineTemplate(
            tenant_id=tenant.id,
            start_time=time(6, 0),
            end_time=time(8, 0),
            task_title=task_title,
            task_description=f'{task_title} description',
            display_order=display_order,
            is_active=is_active,
        )
        db.session.add(routine)
        db.session.flush()
        return routine

    return _create


@pytest.fixture
def inventory_item_factory(app):
    def _create(*, tenant, name='Cotton Seed Cake', quantity=0, unit_cost=0, minimum_threshold=10):
        item = InventoryItem(
            tenant_id=tenant.id,
            name=name,
            category='Feed',
            unit='kg',
            current_qty=quantity,
            minimum_threshold=minimum_threshold,
            energy_mj_per_kg=0,
            protein_grams_per_kg=0,
            fiber_grams_per_kg=0,
            cost_per_kg=unit_cost,
        )
        db.session.add(item)
        db.session.flush()
        return item

    return _create


@pytest.fixture
def inventory_transaction_factory(app):
    def _create(*, item, transaction_type='OUT', quantity=1, unit_cost=0, logged_by=None):
        txn = InventoryTransaction(
            item_id=item.id,
            transaction_type=transaction_type,
            quantity=quantity,
            unit_cost=unit_cost,
            logged_by=logged_by,
        )
        db.session.add(txn)
        db.session.flush()
        return txn

    return _create


@pytest.fixture
def milk_log_factory(app):
    def _create(*, tenant, cow_id, amount_liters=0, session_name='Morning', recorded_by=None, day=None):
        log = MilkLog(
            tenant_id=tenant.id,
            cow_id=cow_id,
            amount_liters=amount_liters,
            session=session_name,
            recorded_by=recorded_by,
        )
        if day is not None:
            log.timestamp = day
        db.session.add(log)
        db.session.flush()
        return log

    return _create
