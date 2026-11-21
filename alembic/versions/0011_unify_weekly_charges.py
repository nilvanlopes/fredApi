"""Consolidate legacy guest charges into the corresponding weekly charges.

Revision ID: 0011_unify_weekly_charges
Revises: 0010_guest_charge_name
"""
from alembic import op


revision = "0011_unify_weekly_charges"
down_revision = "0010_guest_charge_name"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("LOCK TABLE charges IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$
        DECLARE
            legacy_charge charges%ROWTYPE;
            single_charge charges%ROWTYPE;
            current_charge charges%ROWTYPE;
            participant weekly_attendance_entries%ROWTYPE;
            cancellation_reason text;
            legacy_key text;
            single_key text;
            legacy_revision_at timestamptz;
            single_revision_at timestamptz;
        BEGIN
            FOR legacy_charge IN SELECT * FROM charges WHERE type = 'guest' ORDER BY id LOOP
                SELECT * INTO single_charge
                FROM charges
                WHERE person_id = legacy_charge.person_id
                  AND reference_date = legacy_charge.reference_date
                  AND type = 'single';

                SELECT after->>'reason' INTO cancellation_reason
                FROM audit_events
                WHERE entity_type = 'charge'
                  AND entity_id = single_charge.id::text
                  AND status = 'applied'
                  AND action = 'update'
                  AND before->>'status' IS DISTINCT FROM after->>'status'
                ORDER BY recorded_at DESC, occurred_at DESC, id DESC
                LIMIT 1;

                SELECT entry.* INTO participant
                FROM weekly_attendance_entries entry
                JOIN weekly_attendances game ON game.id = entry.attendance_id
                WHERE entry.person_id = legacy_charge.person_id
                  AND game.game_date = legacy_charge.reference_date
                  AND entry.deleted_at IS NULL
                ORDER BY entry.updated_at DESC, entry.display_order, entry.id
                LIMIT 1
                FOR UPDATE OF entry;

                -- Only undo the cancellation made when the inviter was charged separately.
                IF single_charge.id IS NULL
                   OR single_charge.status <> 'cancelled'
                   OR single_charge.paid_at IS NOT NULL
                   OR legacy_charge.status <> 'pending'
                   OR legacy_charge.paid_at IS NOT NULL
                   OR single_charge.amount_cents <> legacy_charge.amount_cents
                   OR COALESCE(cancellation_reason NOT LIKE 'Convidado cobrado ao convidante %', true)
                   OR participant.id IS NULL
                   OR participant.status <> 'main'
                   OR participant.is_monthly_subscriber
                   OR NULLIF(btrim(participant.invited_by), '') IS NULL
                THEN
                    RAISE EXCEPTION 'Cobrança legada % exige revisão antes da consolidação',
                        legacy_charge.id;
                END IF;

                legacy_key := concat('charge:', legacy_charge.person_id, ':guest:', legacy_charge.reference_date);
                single_key := concat('charge:', single_charge.person_id, ':single:', single_charge.reference_date);
                SELECT occurred_at INTO legacy_revision_at FROM entity_revisions WHERE key = legacy_key;
                SELECT occurred_at INTO single_revision_at FROM entity_revisions WHERE key = single_key;

                UPDATE charges
                SET status = legacy_charge.status
                WHERE id = single_charge.id
                RETURNING * INTO current_charge;

                UPDATE weekly_attendance_entries entry
                SET owes_single_payment = entry.status = 'main' AND NOT entry.is_monthly_subscriber,
                    single_payment_amount_cents = current_charge.amount_cents
                WHERE entry.person_id = current_charge.person_id
                  AND entry.attendance_id = participant.attendance_id
                  AND entry.deleted_at IS NULL;

                INSERT INTO audit_events (
                    id, occurred_at, actor_name, source, action, entity_type,
                    entity_id, person_id, before, after, status
                ) VALUES (
                    gen_random_uuid(), now(), 'Migração de cobranças semanais', 'migration',
                    'update', 'charge', single_charge.id::text, single_charge.person_id,
                    to_jsonb(single_charge) || jsonb_build_object(
                        'superseded_charge', to_jsonb(legacy_charge),
                        'single_revision_at', single_revision_at, 'legacy_revision_at', legacy_revision_at
                    ),
                    to_jsonb(current_charge) || jsonb_build_object(
                        'superseded_charge_id', legacy_charge.id,
                        'invited_by', participant.invited_by,
                        'reason', 'Consolidação da cobrança semanal do convidado'
                    ),
                    'applied'
                );

                INSERT INTO entity_revisions(key, occurred_at)
                VALUES (single_key, COALESCE(GREATEST(legacy_revision_at, single_revision_at), now()))
                ON CONFLICT(key) DO UPDATE
                SET occurred_at = GREATEST(entity_revisions.occurred_at, EXCLUDED.occurred_at);

                DELETE FROM entity_revisions WHERE key = legacy_key;
                DELETE FROM charges WHERE id = legacy_charge.id;
            END LOOP;
        END $$;
    """)
    op.create_check_constraint("ck_charge_type", "charges", "type IN ('monthly', 'single')")


def downgrade():
    # The previous app can read weekly charges in the consolidated form.
    # Reintroducing duplicate charges would overwrite newer payment changes.
    op.drop_constraint("ck_charge_type", "charges", type_="check")
