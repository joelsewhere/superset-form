"""Runtime config, externally-supplied form definitions, and a payload column.

Adds:
  - app_config          : the app <-> Superset dashboard binding, set from the
                          setup page instead of the environment.
  - form_definitions    : field definitions supplied by an external form
                          builder over PUT /api/form-schema.
  - submissions.payload : where fields with no dedicated column land, so a new
                          form does not require a migration.

Revision ID: 0002
Revises: 0001
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "submissions",
        sa.Column(
            "payload",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_table(
        "form_definitions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("fields", postgresql.JSONB, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    # At most one active definition. A partial unique index enforces that in
    # the database rather than trusting every write path to get it right.
    op.create_index(
        "uq_form_definitions_one_active",
        "form_definitions",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "app_config",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("dashboard_id", sa.String(64), nullable=True),
        sa.Column("dashboard_title", sa.String(255), nullable=True),
        sa.Column("embed_uuid", sa.String(64), nullable=True),
        sa.Column("filter_id", sa.String(128), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Single-row table; the check keeps a second row from ever appearing.
        sa.CheckConstraint("id = 1", name="ck_app_config_single_row"),
    )
    op.execute("INSERT INTO app_config (id) VALUES (1)")

    # Rebuild the view so payload is queryable from Superset.
    #
    # DROP then CREATE, not CREATE OR REPLACE: Postgres only lets REPLACE
    # append columns to the end of a view, and `payload` goes before
    # `created_at`. REPLACE fails with "cannot change name of view column".
    op.execute("DROP VIEW IF EXISTS v_submissions")
    op.execute(
        """
        CREATE VIEW v_submissions AS
        SELECT
            id,
            region,
            product,
            units,
            unit_price,
            (units * unit_price) AS revenue,
            sale_date,
            notes,
            payload,
            created_at
        FROM submissions
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'superset_ro') THEN
                GRANT SELECT ON v_submissions TO superset_ro;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_submissions")
    op.execute(
        """
        CREATE VIEW v_submissions AS
        SELECT
            id, region, product, units, unit_price,
            (units * unit_price) AS revenue,
            sale_date, notes, created_at
        FROM submissions
        """
    )
    op.drop_table("app_config")
    op.drop_index("uq_form_definitions_one_active", table_name="form_definitions")
    op.drop_table("form_definitions")
    op.drop_column("submissions", "payload")
