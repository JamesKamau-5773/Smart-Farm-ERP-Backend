import pytest

from app.utils.auth_errors import WeakPasswordError
from app.utils.password_policy import PasswordPolicy


def test_strong_password_passes():
    assert PasswordPolicy.violations('Maziwa2026x') == []


@pytest.mark.parametrize('password, rule', [
    ('Ab1', 'min_length'),
    ('a1' * 65, 'max_length'),
    ('onlyletters', 'letter_and_digit'),
    ('1234567890', 'letter_and_digit'),
    ('Password123', 'not_common'),
])
def test_rules(password, rule):
    assert rule in PasswordPolicy.violations(password)


def test_rejects_personal_values():
    assert 'not_personal' in PasswordPolicy.violations('jane2026!', personal_values=['jane', None])
    assert 'not_personal' in PasswordPolicy.violations('x712345678y', personal_values=['+254712345678'])
    assert PasswordPolicy.violations('Maziwa2026x', personal_values=['jane', '+254712345678']) == []


def test_enforce_raises_with_violation_ids():
    with pytest.raises(WeakPasswordError) as excinfo:
        PasswordPolicy.enforce('short')
    assert excinfo.value.code == 'WEAK_PASSWORD'
    assert 'min_length' in excinfo.value.extra['violations']
