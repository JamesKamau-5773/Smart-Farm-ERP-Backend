"""Restyle stored receipt PDFs to the current document template with audit records."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app, db
from app.services.receipt_service import ReceiptService
from config import Config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tenant-id', type=int, help='Limit the upgrade to one tenant.')
    parser.add_argument('--performed-by', type=int, help='User ID recorded in the receipt audit trail.')
    parser.add_argument('--confirm', action='store_true', help='Required to replace stored PDF artifacts.')
    args = parser.parse_args()
    if not args.confirm:
        parser.error('--confirm is required to replace stored PDF artifacts.')

    app = create_app(Config)
    with app.app_context():
        count = ReceiptService.rerender_documents_to_current_template(
            tenant_id=args.tenant_id,
            performed_by=args.performed_by,
        )
        db.session.commit()
        print(f'Restyled {count} receipt PDF artifact(s) to template {ReceiptService.TEMPLATE_VERSION}.')


if __name__ == '__main__':
    main()
