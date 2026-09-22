"""allow audited receipt pdf restyles

Revision ID: c6b2d3e4f5a6
Revises: c5a1e2b3d4f5
Create Date: 2026-08-31
"""

from alembic import op


revision = 'c6b2d3e4f5a6'
down_revision = 'c5a1e2b3d4f5'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_receipt_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Issued receipts cannot be deleted';
            END IF;
            IF OLD.document_content IS NULL
               AND NEW.document_content IS NOT NULL
               AND NEW.document_sha256 IS NOT NULL
               AND NEW.tenant_id = OLD.tenant_id
               AND NEW.transaction_id = OLD.transaction_id
               AND NEW.snapshot = OLD.snapshot
               AND NEW.receipt_number = OLD.receipt_number
               AND NEW.status = OLD.status THEN
                RETURN NEW;
            END IF;
            IF current_setting('app.allow_receipt_document_restyle', true) = 'on'
               AND NEW.tenant_id = OLD.tenant_id
               AND NEW.transaction_id = OLD.transaction_id
               AND NEW.snapshot = OLD.snapshot
               AND NEW.receipt_number = OLD.receipt_number
               AND NEW.status = OLD.status
               AND NEW.farm_id IS NOT DISTINCT FROM OLD.farm_id
               AND NEW.currency = OLD.currency
               AND NEW.voided_at IS NOT DISTINCT FROM OLD.voided_at
               AND NEW.voided_by IS NOT DISTINCT FROM OLD.voided_by
               AND NEW.void_reason IS NOT DISTINCT FROM OLD.void_reason
               AND NEW.template_version IS DISTINCT FROM OLD.template_version
               AND NEW.document_content IS NOT NULL
               AND NEW.document_sha256 IS NOT NULL THEN
                RETURN NEW;
            END IF;
            IF OLD.status = 'ISSUED'
               AND NEW.status = 'VOIDED'
               AND NEW.voided_at IS NOT NULL
               AND NEW.voided_by IS NOT NULL
               AND NULLIF(BTRIM(NEW.void_reason), '') IS NOT NULL
               AND NEW.snapshot = OLD.snapshot
               AND NEW.receipt_number = OLD.receipt_number
               AND NEW.tenant_id = OLD.tenant_id
               AND NEW.transaction_id = OLD.transaction_id
               AND NEW.farm_id IS NOT DISTINCT FROM OLD.farm_id
               AND NEW.currency = OLD.currency
               AND NEW.template_version = OLD.template_version
               AND NEW.document_content IS NOT DISTINCT FROM OLD.document_content
               AND NEW.document_sha256 IS NOT DISTINCT FROM OLD.document_sha256 THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Issued receipts are immutable';
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade():
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_receipt_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Issued receipts cannot be deleted';
            END IF;
            IF OLD.document_content IS NULL
               AND NEW.document_content IS NOT NULL
               AND NEW.document_sha256 IS NOT NULL
               AND NEW.tenant_id = OLD.tenant_id
               AND NEW.transaction_id = OLD.transaction_id
               AND NEW.snapshot = OLD.snapshot
               AND NEW.receipt_number = OLD.receipt_number
               AND NEW.status = OLD.status THEN
                RETURN NEW;
            END IF;
            IF OLD.status = 'ISSUED'
               AND NEW.status = 'VOIDED'
               AND NEW.voided_at IS NOT NULL
               AND NEW.voided_by IS NOT NULL
               AND NULLIF(BTRIM(NEW.void_reason), '') IS NOT NULL
               AND NEW.snapshot = OLD.snapshot
               AND NEW.receipt_number = OLD.receipt_number
               AND NEW.tenant_id = OLD.tenant_id
               AND NEW.transaction_id = OLD.transaction_id
               AND NEW.farm_id IS NOT DISTINCT FROM OLD.farm_id
               AND NEW.currency = OLD.currency
               AND NEW.template_version = OLD.template_version
               AND NEW.document_content IS NOT DISTINCT FROM OLD.document_content
               AND NEW.document_sha256 IS NOT DISTINCT FROM OLD.document_sha256 THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Issued receipts are immutable';
        END;
        $$ LANGUAGE plpgsql;
    """)
