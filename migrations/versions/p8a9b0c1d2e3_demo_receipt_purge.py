"""Let the daily demo refresh delete the demo farm's own receipts

The receipt triggers (receipts_immutable, receipt_audit_logs_immutable) refuse every DELETE. The
demo workspace is rebuilt each morning (DemoSeedService), and it now issues receipts, so its purge
must be able to remove them. A DELETE is allowed only when BOTH hold:

* the transaction set ``app.purging_demo_tenant`` to that row's tenant id (DemoDataPurger does,
  with set_config(..., true), so it lasts for its transaction only), and
* that tenant is flagged ``is_demo``.

Real farms' receipts stay undeletable whatever the setting says. Databases created from the
squashed initial schema have no such triggers; this migration leaves them unchanged.

Revision ID: p8a9b0c1d2e3
Revises: o7a8b9c0d1e2
Create Date: 2026-11-20
"""
from alembic import op

revision = 'p8a9b0c1d2e3'
down_revision = 'o7a8b9c0d1e2'
branch_labels = None
depends_on = None

_DEMO_PURGE = """
                IF current_setting('app.purging_demo_tenant', true) = OLD.tenant_id::text
                   AND EXISTS (SELECT 1 FROM tenants WHERE id = OLD.tenant_id AND is_demo) THEN
                    RETURN OLD;
                END IF;"""

# The bodies below the DELETE check are unchanged from the live functions.
_RECEIPT_RULES = """
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
            RAISE EXCEPTION 'Issued receipts are immutable';"""


def _receipt_function(demo_purge: bool) -> str:
    return f"""
        CREATE OR REPLACE FUNCTION prevent_receipt_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN{_DEMO_PURGE if demo_purge else ''}
                RAISE EXCEPTION 'Issued receipts cannot be deleted';
            END IF;{_RECEIPT_RULES}
        END;
        $$ LANGUAGE plpgsql;
    """


def _audit_function(demo_purge: bool) -> str:
    purge = f"""
            IF TG_OP = 'DELETE' THEN{_DEMO_PURGE}
            END IF;""" if demo_purge else ''
    return f"""
        CREATE OR REPLACE FUNCTION prevent_receipt_audit_mutation() RETURNS trigger AS $$
        BEGIN{purge}
            RAISE EXCEPTION 'Receipt audit records are append-only';
        END;
        $$ LANGUAGE plpgsql;
    """


def _replace_if_present(function_name: str, sql: str) -> None:
    # Only databases that already carry the trigger function are changed.
    op.execute(f"""
        DO $outer$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = '{function_name}') THEN
                EXECUTE $sql${sql}$sql$;
            END IF;
        END
        $outer$;
    """)


def upgrade():
    if op.get_bind().dialect.name != 'postgresql':
        return
    _replace_if_present('prevent_receipt_mutation', _receipt_function(demo_purge=True))
    _replace_if_present('prevent_receipt_audit_mutation', _audit_function(demo_purge=True))


def downgrade():
    if op.get_bind().dialect.name != 'postgresql':
        return
    _replace_if_present('prevent_receipt_mutation', _receipt_function(demo_purge=False))
    _replace_if_present('prevent_receipt_audit_mutation', _audit_function(demo_purge=False))
