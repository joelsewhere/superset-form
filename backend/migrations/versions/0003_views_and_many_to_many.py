"""Views, dashboard bindings, and many-to-many form<->dashboard links.

Replaces the single `app_config` binding with first-class resources:

  * dashboard_bindings  : Superset dashboards this app can embed
  * form_dashboard_links: many-to-many, a form can feed several dashboards
  * views / view_panels : saved workspaces holding any number of panels

`form_definitions` loses `is_active` (panels reference forms directly) and
gains a unique name. `submissions` gains `form_definition_id`.

The existing app_config row, if it points anywhere, is migrated into a
dashboard_binding so a configured stack is not silently reset.

Revision ID: 0003
Revises: 0002
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- dashboard bindings -------------------------------------------------
    op.create_table(
        "dashboard_bindings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("superset_dashboard_id", sa.String(64), nullable=True),
        sa.Column("embed_uuid", sa.String(64), nullable=True),
        sa.Column("filter_id", sa.String(128), nullable=True),
        sa.Column(
            "auto_created", sa.Boolean, nullable=False, server_default=sa.false()
        ),
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

    # --- form_definitions: drop is_active, require unique names -------------
    op.drop_index("uq_form_definitions_one_active", table_name="form_definitions")
    op.drop_column("form_definitions", "is_active")

    # Names were not unique before; disambiguate duplicates before adding the
    # constraint rather than letting the migration fail on real data.
    op.execute(
        """
        UPDATE form_definitions f SET name = f.name || '-' || f.id
        WHERE EXISTS (
            SELECT 1 FROM form_definitions o
            WHERE o.name = f.name AND o.id < f.id
        )
        """
    )
    op.create_unique_constraint(
        "uq_form_definitions_name", "form_definitions", ["name"]
    )

    # --- many-to-many -------------------------------------------------------
    op.create_table(
        "form_dashboard_links",
        sa.Column(
            "form_definition_id",
            sa.Integer,
            sa.ForeignKey("form_definitions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "dashboard_binding_id",
            sa.Integer,
            sa.ForeignKey("dashboard_bindings.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    # --- views --------------------------------------------------------------
    op.create_table(
        "views",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("layout", postgresql.JSONB, nullable=True),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.false()),
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
    # At most one default view, enforced in the database rather than trusted
    # to every write path.
    op.create_index(
        "uq_views_one_default",
        "views",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.create_table(
        "view_panels",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "view_id",
            sa.Integer,
            sa.ForeignKey("views.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("panel_key", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "form_definition_id",
            sa.Integer,
            sa.ForeignKey("form_definitions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "dashboard_binding_id",
            sa.Integer,
            sa.ForeignKey("dashboard_bindings.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.UniqueConstraint("view_id", "panel_key", name="uq_view_panels_key"),
        # A panel points at exactly one resource, matching its kind. Without
        # this a 'form' panel could carry a dashboard id and render nothing.
        sa.CheckConstraint(
            "(kind = 'form' AND form_definition_id IS NOT NULL "
            " AND dashboard_binding_id IS NULL) OR "
            "(kind = 'dashboard' AND dashboard_binding_id IS NOT NULL "
            " AND form_definition_id IS NULL)",
            name="ck_view_panels_kind_target",
        ),
    )

    # --- submissions know which form produced them --------------------------
    op.add_column(
        "submissions",
        sa.Column(
            "form_definition_id",
            sa.Integer,
            sa.ForeignKey("form_definitions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # --- carry the old single binding forward -------------------------------
    op.execute(
        """
        INSERT INTO dashboard_bindings
            (name, superset_dashboard_id, embed_uuid, filter_id, auto_created)
        SELECT
            COALESCE(dashboard_title, 'Dashboard'),
            dashboard_id, embed_uuid, filter_id, false
        FROM app_config
        WHERE id = 1 AND embed_uuid IS NOT NULL
        """
    )
    # Link it to every existing form, preserving the old behaviour where the
    # one active form fed the one configured dashboard.
    op.execute(
        """
        INSERT INTO form_dashboard_links (form_definition_id, dashboard_binding_id)
        SELECT f.id, d.id FROM form_definitions f CROSS JOIN dashboard_bindings d
        """
    )

    op.drop_table("app_config")

    # --- expose the form on the view Superset reads -------------------------
    op.execute("DROP VIEW IF EXISTS v_submissions")
    op.execute(
        """
        CREATE VIEW v_submissions AS
        SELECT
            s.id,
            s.form_definition_id,
            f.name AS form_name,
            s.region,
            s.product,
            s.units,
            s.unit_price,
            (s.units * s.unit_price) AS revenue,
            s.sale_date,
            s.notes,
            s.payload,
            s.created_at
        FROM submissions s
        LEFT JOIN form_definitions f ON f.id = s.form_definition_id
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
        SELECT id, region, product, units, unit_price,
               (units * unit_price) AS revenue,
               sale_date, notes, payload, created_at
        FROM submissions
        """
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
        sa.CheckConstraint("id = 1", name="ck_app_config_single_row"),
    )
    op.execute("INSERT INTO app_config (id) VALUES (1)")

    op.drop_column("submissions", "form_definition_id")
    op.drop_table("view_panels")
    op.drop_index("uq_views_one_default", table_name="views")
    op.drop_table("views")
    op.drop_table("form_dashboard_links")
    op.drop_constraint("uq_form_definitions_name", "form_definitions", type_="unique")
    op.add_column(
        "form_definitions",
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "uq_form_definitions_one_active",
        "form_definitions",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.drop_table("dashboard_bindings")
