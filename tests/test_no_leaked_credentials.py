"""No credential that leaked through the public git history may appear in a tracked file.

The values are kept only as SHA-256 digests. All of them have been (or must be)
rotated, so a digest guards nothing that still works; it only lets this test
recognise the old value if someone pastes it back in.
"""
import hashlib
import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

LEAKED_SHA256 = {
    # Neon `neondb_owner` password: import_data.py and the `sa` screenshot.
    '7e0b19d1818836f31d5754a4fc860e8be15b90943c07e2466ecbe85773b7180f',
    # Default super admin password: app/utils/db_init.py ensure_super_admin_account().
    '9451d5e482b10cb2143be8bc9fffce4e360d3ddc6044c348d045b8fe029fdd40',
    # jivu_admin password: app/utils/db_init.py seed_roles().
    'ee08f12b93a298c0a1601b1fe7d566306c353683b117a172962393c2dbb927da',
}

# Runs of characters a password can contain; URL separators (: @ /) and quotes split tokens.
TOKEN = re.compile(r"[^\s'\"`<>()\[\]{},;=:/@\\]{6,}")


def _tracked_files():
    output = subprocess.run(
        ['git', 'ls-files', '-z'], cwd=REPO_ROOT, capture_output=True, check=True,
    ).stdout
    return [REPO_ROOT / name for name in output.decode().split('\0') if name]


def _digests(text: str):
    for token in TOKEN.findall(text):
        # Also try without trailing punctuation that often follows a value in prose.
        for candidate in {token, token.rstrip('.,!?')}:
            yield hashlib.sha256(candidate.encode()).hexdigest()


class NoLeakedCredentialsTestCase(unittest.TestCase):

    def test_no_tracked_file_contains_a_leaked_credential(self):
        offenders = []
        for path in _tracked_files():
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding='utf-8')
            except (UnicodeDecodeError, OSError):
                continue
            if any(digest in LEAKED_SHA256 for digest in _digests(text)):
                offenders.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual(offenders, [], 'A leaked credential is back in these files')

    def test_known_binary_capture_is_not_tracked(self):
        # `sa` was a screenshot showing the production database URL.
        self.assertFalse(REPO_ROOT / 'sa' in _tracked_files(), '`sa` is tracked again')

    def test_detector_recognises_a_value_inside_a_url(self):
        fake = 'not-a-real-password'
        digest = hashlib.sha256(fake.encode()).hexdigest()
        self.assertIn(digest, set(_digests(f'url = "postgresql://user:{fake}@host/db"')))
