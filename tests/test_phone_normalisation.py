import pytest

from app.utils.phone import InvalidPhoneNumber, from_wa_id, phone_identifier, phone_username, to_e164, to_wa_id
from app.utils.phone_backfill import UserPhoneRecord, plan_phone_backfill


@pytest.mark.parametrize('raw', [
    '0712345678', '712345678', '254712345678', '+254712345678', '+254 712 345 678',
    '0712-345-678', '00254712345678',
])
def test_kenyan_mobile_formats_normalise_to_e164(raw):
    assert to_e164(raw) == '+254712345678'


@pytest.mark.parametrize('raw', ['0112345678', '112345678', '+254112345678'])
def test_01_prefix_numbers_normalise(raw):
    assert to_e164(raw) == '+254112345678'


def test_international_numbers_are_kept():
    assert to_e164('+447911123456') == '+447911123456'
    assert to_e164('447911123456') == '+447911123456'


@pytest.mark.parametrize('raw', ['', None, 'testuser', '0712', '0712345678x', '2547123456789', 'abc@example.com'])
def test_invalid_numbers_are_rejected(raw):
    with pytest.raises(InvalidPhoneNumber):
        to_e164(raw)


def test_wa_id_round_trip_and_derived_values():
    assert to_wa_id('+254712345678') == '254712345678'
    assert from_wa_id('254712345678') == '+254712345678'
    assert from_wa_id('') is None
    assert phone_identifier('+254712345678') == 'phone_254712345678'
    assert phone_username('+254712345678') == '254712345678'


def _record(user_id, phone=None, identifier=None, username=None):
    return UserPhoneRecord(user_id, phone, identifier or f'user_{user_id}', username or f'user{user_id}')


def test_backfill_normalises_existing_phone_numbers():
    plan = plan_phone_backfill([_record(1, phone='254712345678'), _record(2, phone='+254712345679')])
    assert plan.changes == {1: '+254712345678'}
    assert plan.issues == []


def test_backfill_copies_phone_from_legacy_identifier_and_username():
    plan = plan_phone_backfill([
        _record(1, identifier='phone_254712345678'),
        _record(2, username='0712345679'),
        _record(3, username='farmer_jane'),
    ])
    assert plan.changes == {1: '+254712345678', 2: '+254712345679'}


def test_backfill_column_owner_wins_and_fallback_claimant_is_reported():
    plan = plan_phone_backfill([
        _record(1, phone='254712345678'),
        _record(2, identifier='phone_0712345678'),
    ])
    assert plan.changes == {1: '+254712345678'}
    [issue] = plan.issues
    assert (issue.user_id, issue.issue_type, issue.conflicting_user_id) == (2, 'DUPLICATE_PHONE', 1)


def test_backfill_ambiguous_numbers_are_assigned_to_nobody():
    plan = plan_phone_backfill([
        _record(1, phone='0712345678'),
        _record(2, phone='254712345678'),
    ])
    assert plan.changes == {1: None, 2: None}
    assert sorted((i.user_id, i.issue_type) for i in plan.issues) == [(1, 'AMBIGUOUS_PHONE'), (2, 'AMBIGUOUS_PHONE')]


def test_backfill_reports_invalid_values_without_losing_them():
    plan = plan_phone_backfill([_record(1, phone='12345')])
    assert plan.changes == {1: None}
    [issue] = plan.issues
    assert (issue.issue_type, issue.raw_value) == ('INVALID_PHONE', '12345')


def test_backfill_falls_back_when_column_value_is_invalid():
    plan = plan_phone_backfill([_record(1, phone='n/a', identifier='phone_254712345678')])
    assert plan.changes == {1: '+254712345678'}
    assert [i.issue_type for i in plan.issues] == ['INVALID_PHONE']
