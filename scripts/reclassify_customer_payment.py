"""Correct a confirmed customer payment that was recorded as ledger revenue."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.services.ledger_correction_service import LedgerCorrectionService
from config import Config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tenant-id', required=True, type=int)
    parser.add_argument('--transaction-id', required=True, type=int)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--corrected-by', type=int)
    parser.add_argument('--confirm', action='store_true', help='Required to apply the correction.')
    args = parser.parse_args()
    if not args.confirm:
        parser.error('--confirm is required to change accounting records.')

    app = create_app(Config)
    with app.app_context():
        replacement = LedgerCorrectionService.reclassify_customer_revenue_as_payment(
            tenant_id=args.tenant_id,
            transaction_id=args.transaction_id,
            payment_reference=args.reference,
            corrected_by=args.corrected_by,
        )
        print(f'Voided revenue transaction {args.transaction_id}; created payment transaction {replacement.id}.')


if __name__ == '__main__':
    main()
