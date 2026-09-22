import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import render_template
from weasyprint import HTML

from app import create_app, db
from app.models.finance import Receipt, ReceiptAuditLog
from app.services.receipt_service import ReceiptService


def backfill_receipt_artifacts():
    receipts = Receipt.query.filter(Receipt.document_content.is_(None)).order_by(Receipt.id).all()
    for receipt in receipts:
        document = HTML(
            string=render_template('pdf/receipt.html', receipt=ReceiptService.serialize(receipt))
        ).write_pdf()
        receipt.document_content = document
        receipt.document_sha256 = hashlib.sha256(document).hexdigest()
        db.session.add(ReceiptAuditLog(
            tenant_id=receipt.tenant_id,
            receipt_id=receipt.id,
            action='ARTIFACT_BACKFILLED',
            details={'document_sha256': receipt.document_sha256},
        ))
    db.session.commit()
    return len(receipts)


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        count = backfill_receipt_artifacts()
        print(f'Backfilled {count} receipt artifact(s).')
