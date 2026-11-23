"""The test-database guard (tests/db_guard.py). Pure checks: no database needed."""
import unittest

import pytest

from tests.db_guard import assert_safe_test_database, problems

LOCAL_TEST = 'postgresql+psycopg://postgres:pw@localhost:5433/jivu_farm_db_test'
LOCAL_DEV = 'postgresql+psycopg://postgres:pw@localhost:5433/jivu_farm_db'


class TestDatabaseGuard(unittest.TestCase):

    def test_separate_local_test_database_is_allowed(self):
        self.assertEqual(problems({'TEST_DATABASE_URL': LOCAL_TEST, 'DATABASE_URL': LOCAL_DEV}), [])

    def test_docker_compose_service_host_is_allowed(self):
        env = {
            'TEST_DATABASE_URL': 'postgresql://maziwa:pw@db:5432/maziwa_test',
            'DATABASE_URL': 'postgresql://maziwa:pw@db:5432/maziwa',
        }
        self.assertEqual(problems(env), [])

    def test_missing_url_is_refused(self):
        self.assertTrue(problems({}))
        self.assertTrue(problems({'TEST_DATABASE_URL': '  '}))

    def test_same_database_as_the_app_is_refused(self):
        env = {'TEST_DATABASE_URL': LOCAL_TEST, 'DATABASE_URL': LOCAL_TEST.replace('+psycopg', '')}
        self.assertIn('same database', ' '.join(problems(env)))

    def test_neon_host_is_refused(self):
        env = {'TEST_DATABASE_URL': 'postgresql://u:pw@ep-x-pooler.eu-central-1.aws.neon.tech/neondb_test'}
        self.assertIn('Neon', ' '.join(problems(env)))

    def test_other_remote_host_is_refused(self):
        env = {'TEST_DATABASE_URL': 'postgresql://u:pw@dpg-abc.oregon-postgres.render.com/app_test'}
        self.assertIn('non-local host', ' '.join(problems(env)))

    def test_extra_local_host_can_be_allowed(self):
        env = {
            'TEST_DATABASE_URL': 'postgresql://u:pw@postgres-test:5432/app_test',
            'TEST_DATABASE_LOCAL_HOSTS': 'postgres-test',
        }
        self.assertEqual(problems(env), [])

    def test_database_name_without_test_is_refused(self):
        env = {'TEST_DATABASE_URL': 'postgresql://u:pw@localhost/jivu_farm_db'}
        self.assertIn('contains "test"', ' '.join(problems(env)))

    def test_messages_never_include_the_password(self):
        env = {'TEST_DATABASE_URL': 'postgresql://u:s3cret-value@ep-x.neon.tech/prod', 'DATABASE_URL': ''}
        self.assertNotIn('s3cret-value', ' '.join(problems(env)))

    def test_assert_raises_with_every_reason(self):
        with pytest.raises(RuntimeError) as error:
            assert_safe_test_database({'TEST_DATABASE_URL': 'postgresql://u:pw@ep-x.neon.tech/neondb'})
        self.assertIn('non-local host', str(error.value))
        self.assertIn('contains "test"', str(error.value))
