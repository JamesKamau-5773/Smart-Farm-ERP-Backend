"""Process calving events and fix historical data

Revision ID: b1c2d3e4f5a6
Revises: a3f10cb7f5db
Create Date: 2026-08-17 19:05:10.123456

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text
from datetime import date, timedelta


# revision identifiers, used by Alembic.
revision = 'b1c2d3e4f5a6'
down_revision = 'a3f10cb7f5db'
branch_labels = None
depends_on = None


def upgrade():
    """
    This data migration corrects the status and dates for specific cows (Princess,
    Joyce, Sofia) that were recorded before the application logic was updated to
    automatically handle state transitions from timeline events.
    """
    conn = op.get_bind()

    # --- Data Fix for Princess ---
    # Find the most recent 'Pending' breeding log for Princess to get her insemination date.
    princess_log = conn.execute(text(
        "SELECT bl.insemination_date FROM breeding_logs bl "
        "JOIN cows c ON c.id = bl.cow_id "
        "WHERE c.name = 'Princess' AND bl.status = 'Pending' "
        "ORDER BY bl.insemination_date DESC LIMIT 1"
    )).fetchone()

    if princess_log and princess_log.insemination_date:
        insemination_date = princess_log.insemination_date
        due_date = insemination_date + timedelta(days=280)

        # Update Princess's master record to 'Pregnant'
        op.execute(text(
            f"UPDATE cows SET pregnancy_status = 'Pregnant', due_date = '{due_date.isoformat()}' "
            f"WHERE name = 'Princess'"
        ))

    # --- Data Fix for Joyce and Sofia ---
    # Set their status to Lactating.
    op.execute(text(
        "UPDATE cows SET status = 'Lactating' WHERE name IN ('Joyce', 'Sofia')"
    ))

    # Backfill their last_calving_date from the most recent 'calving' timeline event.
    for cow_name in ['Joyce', 'Sofia']:
        calving_event = conn.execute(text(
            "SELECT ate.event_date, c.id as cow_id, c.tenant_id FROM animal_events ate "
            "JOIN cows c ON c.id = ate.cow_id "
            f"WHERE c.name = '{cow_name}' AND ate.event_type = 'calving' "
            "ORDER BY ate.event_date DESC LIMIT 1"
        )).fetchone()

        if calving_event and calving_event.event_date:
            last_calving_date = calving_event.event_date.date()
            op.execute(text(
                f"UPDATE cows SET last_calving_date = '{last_calving_date.isoformat()}' "
                f"WHERE name = '{cow_name}'"
            ))

            # Also ensure a lactation cycle exists for this calving
            cycle_exists = conn.execute(text(
                "SELECT id FROM lactation_cycles "
                f"WHERE cow_id = {calving_event.cow_id} AND actual_calving_date = '{last_calving_date.isoformat()}'"
            )).fetchone()

            if not cycle_exists:
                op.execute(text(
                    "INSERT INTO lactation_cycles (cow_id, tenant_id, start_date, actual_calving_date) "
                    f"VALUES ({calving_event.cow_id}, {calving_event.tenant_id}, '{last_calving_date.isoformat()}', '{last_calving_date.isoformat()}')"
                ))


def downgrade():
    # Downgrading data fixes is often unsafe. This is a no-op.
    pass
