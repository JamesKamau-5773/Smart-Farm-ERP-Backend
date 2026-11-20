"""Move files saved on the server's disk to Cloudinary, and point the database at them.

Run once on the server that still holds the files, with CLOUDINARY_URL set:

    python scripts/move_uploads_to_cloudinary.py            # dry run: lists what it would do
    python scripts/move_uploads_to_cloudinary.py --confirm  # uploads and updates the rows

Covers cow photos and AI certificates (public, under UPLOAD_ROOT) and receipt photos on ledger
entries (private: they become authenticated Cloudinary files). Rows already on Cloudinary are
skipped, so running it twice is safe. A row whose file is missing is reported and left as it is;
with --clear-missing, missing cow photos and certificates are cleared so the app shows no image
instead of a broken one. Receipt photo rows are never cleared (the ledger keeps them).
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import current_app  # noqa: E402

from app import create_app, db  # noqa: E402
from app.models.finance import TransactionAttachment  # noqa: E402
from app.models.livestock import BreedingLog, Cow  # noqa: E402
from app.services.media_storage import CLOUDINARY_KEY_PREFIX, MediaStorage, uses_cloudinary  # noqa: E402
from app.services.private_file_storage import PrivateFileStorage  # noqa: E402
from config import Config  # noqa: E402


def _local_public_file(url: str):
    """The disk path behind an /uploads/... link, and the folder and name to keep on Cloudinary."""
    relative = url.split('/uploads/', 1)[1]
    folder, filename = os.path.split(relative)
    name, extension = os.path.splitext(filename)
    return os.path.join(current_app.config['UPLOAD_ROOT'], relative), folder, name, extension


def _move_public(rows, attribute: str, label: str, *, confirm: bool, clear_missing: bool, counts: Counter):
    for row in rows:
        url = getattr(row, attribute)
        if not url or not url.startswith('/uploads/'):
            continue
        path, folder, name, extension = _local_public_file(url)
        if not os.path.isfile(path):
            counts[f'{label}: missing'] += 1
            print(f'  missing  {label} #{row.id}: {url}')
            if confirm and clear_missing:
                setattr(row, attribute, None)
            continue
        counts[f'{label}: moved'] += 1
        print(f'  move     {label} #{row.id}: {url}')
        if confirm:
            setattr(row, attribute, MediaStorage.save_public(path, folder=folder, name=name, extension=extension))
            db.session.commit()


def _move_private(confirm: bool, counts: Counter):
    # Corrected ledger entries share their original's file, so each stored path moves once.
    by_path: dict[str, list] = {}
    for attachment in TransactionAttachment.query.order_by(TransactionAttachment.id):
        if attachment.stored_path and not attachment.stored_path.startswith(CLOUDINARY_KEY_PREFIX):
            by_path.setdefault(attachment.stored_path, []).append(attachment)
    for stored_path, attachments in by_path.items():
        path = PrivateFileStorage.resolve(stored_path)
        ids = ', '.join(f'#{a.id}' for a in attachments)
        if path is None:
            counts['receipt photos: missing'] += 1
            print(f'  missing  receipt photo {ids}: {stored_path}')
            continue
        counts['receipt photos: moved'] += 1
        print(f'  move     receipt photo {ids}: {stored_path}')
        if confirm:
            folder, filename = os.path.split(stored_path)
            name, extension = os.path.splitext(filename)
            key = MediaStorage.save_private(path, folder=folder, name=name, extension=extension)
            for attachment in attachments:
                attachment.stored_path = key
            db.session.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--confirm', action='store_true', help='Upload the files and update the rows.')
    parser.add_argument('--clear-missing', action='store_true',
                        help='With --confirm: clear cow photos and certificates whose file is gone.')
    args = parser.parse_args()

    app = create_app(Config)
    with app.app_context():
        if not uses_cloudinary():
            parser.error('MEDIA_STORAGE is not cloudinary: set CLOUDINARY_URL first.')
        print('Moving uploads to Cloudinary' if args.confirm else 'Dry run (nothing changes; add --confirm)')
        counts: Counter = Counter()
        _move_public(Cow.query.order_by(Cow.id), 'photo_url', 'cow photo',
                     confirm=args.confirm, clear_missing=args.clear_missing, counts=counts)
        _move_public(BreedingLog.query.order_by(BreedingLog.id), 'certificate_image_url', 'AI certificate',
                     confirm=args.confirm, clear_missing=args.clear_missing, counts=counts)
        _move_private(args.confirm, counts)
        if args.confirm and args.clear_missing:
            db.session.commit()
        print('Summary:', ', '.join(f'{key} {value}' for key, value in sorted(counts.items())) or 'nothing to move')


if __name__ == '__main__':
    main()
