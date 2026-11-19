"""management, persistent charges, identities and audit

Revision ID: 0008_management
Revises: 0007_person_aliases
"""
from alembic import op

revision = "0008_management"
down_revision = "0007_person_aliases"
branch_labels = None
depends_on = None


def upgrade():
    sql = """
    CREATE TABLE people (id uuid PRIMARY KEY, name text NOT NULL, normalized_name text UNIQUE NOT NULL, active boolean NOT NULL DEFAULT true);
    CREATE TABLE fred_accounts (uid text PRIMARY KEY, username text NOT NULL, name text NOT NULL, email text NOT NULL DEFAULT '', is_admin boolean NOT NULL DEFAULT false, person_id uuid UNIQUE REFERENCES people(id));
    CREATE TABLE charges (id uuid PRIMARY KEY, person_id uuid NOT NULL REFERENCES people(id), type text NOT NULL, reference_date date NOT NULL, amount_cents integer NOT NULL CHECK(amount_cents >= 0), status text NOT NULL DEFAULT 'pending', paid_at timestamptz, CONSTRAINT uq_charge_person_period UNIQUE(person_id,type,reference_date));
    CREATE TABLE audit_events (id uuid PRIMARY KEY, occurred_at timestamptz NOT NULL, recorded_at timestamptz NOT NULL DEFAULT now(), actor_uid text, actor_name text NOT NULL, source text NOT NULL, action text NOT NULL, entity_type text NOT NULL, entity_id text NOT NULL, person_id uuid REFERENCES people(id), before json NOT NULL DEFAULT '{}', after json NOT NULL DEFAULT '{}', status text NOT NULL DEFAULT 'applied');
    CREATE INDEX ix_audit_person_time ON audit_events(person_id,occurred_at);
    CREATE TABLE entity_revisions (key text PRIMARY KEY, occurred_at timestamptz NOT NULL);
    ALTER TABLE monthly_subscribers ADD COLUMN person_id uuid REFERENCES people(id), ADD COLUMN deleted_at timestamptz;
    ALTER TABLE weekly_attendances ADD COLUMN starts_at timestamptz;
    ALTER TABLE weekly_attendance_entries ADD COLUMN person_id uuid REFERENCES people(id), ADD COLUMN deleted_at timestamptz, ADD COLUMN joined_at timestamptz;
    ALTER TABLE monthly_subscribers DROP CONSTRAINT uq_monthly_subscribers_month_year_position;
    CREATE UNIQUE INDEX uq_monthly_active_position ON monthly_subscribers(month,year,position) WHERE deleted_at IS NULL;
    ALTER TABLE weekly_attendance_entries DROP CONSTRAINT uq_weekly_attendance_entries_source;
    CREATE UNIQUE INDEX uq_weekly_active_source ON weekly_attendance_entries(attendance_id,source_section,source_position) WHERE deleted_at IS NULL;
    INSERT INTO people(id,name,normalized_name) SELECT gen_random_uuid(), min(name), normalized_name FROM (SELECT name,normalized_name FROM monthly_subscribers UNION ALL SELECT name,normalized_name FROM weekly_attendance_entries) names GROUP BY normalized_name;
    UPDATE monthly_subscribers m SET person_id=p.id FROM people p WHERE p.normalized_name=m.normalized_name;
    UPDATE weekly_attendance_entries e SET person_id=p.id, joined_at=e.created_at FROM people p WHERE p.normalized_name=e.normalized_name;
    UPDATE weekly_attendances SET starts_at=(game_date + time '19:30') AT TIME ZONE 'America/Sao_Paulo';
    INSERT INTO charges(id,person_id,type,reference_date,amount_cents,status,paid_at) SELECT gen_random_uuid(),person_id,'monthly',make_date(year,month,1),1250,CASE WHEN bool_or(has_paid) THEN 'paid' ELSE 'pending' END,CASE WHEN bool_or(has_paid) THEN max(updated_at) ELSE NULL END FROM monthly_subscribers GROUP BY person_id,year,month;
    INSERT INTO charges(id,person_id,type,reference_date,amount_cents,status) SELECT gen_random_uuid(),e.person_id,'single',w.game_date,max(coalesce(e.single_payment_amount_cents,750)),'pending' FROM weekly_attendance_entries e JOIN weekly_attendances w ON w.id=e.attendance_id WHERE e.owes_single_payment GROUP BY e.person_id,w.game_date;
    INSERT INTO audit_events(id,occurred_at,actor_name,source,action,entity_type,entity_id,person_id,before,after,status)
    SELECT gen_random_uuid(),now(),'Migração inicial','migration','baseline','charge',id::text,person_id,'{}',json_build_object('type',type,'reference_date',reference_date,'amount_cents',amount_cents,'status',status,'note','Estado importado na migração, não representa auditoria retroativa'),'applied' FROM charges;
    INSERT INTO entity_revisions(key,occurred_at) SELECT 'monthly:'||person_id||':'||make_date(year,month,1),max(updated_at) FROM monthly_subscribers GROUP BY person_id,year,month;
    INSERT INTO entity_revisions(key,occurred_at) SELECT 'weekly:'||e.person_id||':'||w.game_date,max(e.updated_at) FROM weekly_attendance_entries e JOIN weekly_attendances w ON w.id=e.attendance_id GROUP BY e.person_id,w.game_date;
    """
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade():
    sql = """DELETE FROM weekly_attendance_entries WHERE deleted_at IS NOT NULL;
    DELETE FROM monthly_subscribers WHERE deleted_at IS NOT NULL;
    ALTER TABLE weekly_attendance_entries DROP COLUMN joined_at, DROP COLUMN deleted_at, DROP COLUMN person_id;
    ALTER TABLE weekly_attendances DROP COLUMN starts_at;
    ALTER TABLE monthly_subscribers DROP COLUMN deleted_at, DROP COLUMN person_id;
    ALTER TABLE monthly_subscribers ADD CONSTRAINT uq_monthly_subscribers_month_year_position UNIQUE(month,year,position);
    ALTER TABLE weekly_attendance_entries ADD CONSTRAINT uq_weekly_attendance_entries_source UNIQUE(attendance_id,source_section,source_position);
    DROP TABLE entity_revisions, audit_events, charges, fred_accounts, people;"""
    for statement in sql.split(";"):
        if statement.strip():
            op.execute(statement)
