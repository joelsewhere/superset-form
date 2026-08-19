"""Create submissions table and the v_submissions view.

Charts point at the view rather than the table so the physical schema can
change later without breaking saved Superset charts.

Revision ID: 0001
Revises:
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "submissions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("region", sa.String(64), nullable=False),
        sa.Column("product", sa.String(64), nullable=False),
        sa.Column("units", sa.Numeric(12, 2), nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("sale_date", sa.Date, nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_submissions_created_at", "submissions", ["created_at"])

    # revenue is computed here so every chart agrees on its definition.
    op.execute(
        """
        CREATE OR REPLACE VIEW v_submissions AS
        SELECT
            id,
            region,
            product,
            units,
            unit_price,
            (units * unit_price) AS revenue,
            sale_date,
            notes,
            created_at
        FROM submissions
        """
    )

    # The view is created after the role's default privileges are set, but
    # ALTER DEFAULT PRIVILEGES does not cover views — grant explicitly.
    # Guarded so migrations still run against a database that was not built
    # by postgres/init (a bare test database, for instance).
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
    op.drop_index("ix_submissions_created_at", table_name="submissions")
    op.drop_table("submissions")
