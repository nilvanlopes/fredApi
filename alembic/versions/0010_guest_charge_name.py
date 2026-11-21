"""Store the invited guest separately from the person responsible for payment.

Revision ID: 0010_guest_charge_name
Revises: 0009_whatsapp_list_history
"""
from alembic import op


revision = "0010_guest_charge_name"
down_revision = "0009_whatsapp_list_history"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE charges ADD COLUMN guest_name text")
    # Earlier manually recorded guest charges kept the guest's name in the
    # audit reason, for example: "Thiago convidado por Elissandro, lista ...".
    op.execute("""
        UPDATE charges AS c
        SET guest_name = source.guest_name
        FROM (
            SELECT DISTINCT ON (entity_id)
                entity_id,
                substring(after->>'reason' FROM '^(.+?) convidado por ') AS guest_name
            FROM audit_events
            WHERE entity_type = 'charge'
              AND after->>'type' = 'guest'
              AND after->>'reason' ~* '^.+ convidado por .+'
            ORDER BY entity_id, recorded_at DESC, occurred_at DESC
        ) AS source
        WHERE c.id::text = source.entity_id
          AND c.type = 'guest'
    """)


def downgrade():
    op.execute("ALTER TABLE charges DROP COLUMN guest_name")
