"""Test package. Importing it checks that the test database is safe to wipe (tests/db_guard.py)."""
import os

from dotenv import load_dotenv

from tests.db_guard import assert_safe_test_database

# config.py loads .env too; load it here first so the guard sees the same values.
load_dotenv()
assert_safe_test_database(os.environ)
