"""ORM models.

The shape, in one picture:

    View 1---* ViewPanel *---1 FormDefinition *---* DashboardBinding
                         *---1 DashboardBinding

  * A **View** is a saved workspace: a dock layout plus the panels in it.
  * A **ViewPanel** is one panel in that layout, showing either a form or a
    dashboard. `panel_key` matches the id dockview uses in its layout JSON.
  * A **FormDefinition** is a field list, normally supplied by an external
    form builder.
  * A **DashboardBinding** is a Superset dashboard this app knows how to embed.
  * Forms and dashboards are linked many-to-many: a submission to a form
    refreshes every dashboard linked to it.

`Submission`'s typed columns are the ones the charts read; fields a form
defines beyond them land in `payload` and need no migration.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# JSONB on Postgres (indexable, queryable from Superset), plain JSON elsewhere
# so the models can be exercised against SQLite in tests. Migrations always
# emit JSONB — this variant only affects metadata-driven table creation.
JSONColumn = JSONB().with_variant(JSON(), "sqlite")


# Many-to-many: one form can feed several dashboards, and one dashboard can be
# fed by several forms.
form_dashboard_links = Table(
    "form_dashboard_links",
    Base.metadata,
    Column(
        "form_definition_id",
        ForeignKey("form_definitions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "dashboard_binding_id",
        ForeignKey("dashboard_bindings.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class DashboardBinding(Base):
    """A Superset dashboard this app can embed."""

    __tablename__ = "dashboard_bindings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Superset's numeric dashboard id.
    superset_dashboard_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # UUID from Superset's embed config — NOT the numeric id above. Using the
    # numeric id here yields a silently blank iframe.
    embed_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Native filter the in-place refresh drives.
    filter_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # True when this app created the dashboard itself, rather than adopting an
    # existing one. Only auto-created dashboards are safe to delete on cleanup.
    auto_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    forms: Mapped[list[FormDefinition]] = relationship(
        secondary=form_dashboard_links, back_populates="dashboards", lazy="selectin"
    )


class FormDefinition(Base):
    """A form's field definitions, normally supplied by an external builder."""

    __tablename__ = "form_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    # A JSON array of FormField objects, validated against that contract on
    # write so a malformed definition is rejected at the API rather than
    # breaking the form at render time.
    fields: Mapped[list] = mapped_column(JSONColumn, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    dashboards: Mapped[list[DashboardBinding]] = relationship(
        secondary=form_dashboard_links, back_populates="forms", lazy="selectin"
    )


class View(Base):
    """A saved workspace: a dock layout plus the panels arranged in it."""

    __tablename__ = "views"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    # Serialised dockview layout. Null until the user first arranges the view,
    # at which point the panels are laid out from their declared order.
    layout: Mapped[dict | None] = mapped_column(JSONColumn, nullable=True)

    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    panels: Mapped[list[ViewPanel]] = relationship(
        back_populates="view",
        cascade="all, delete-orphan",
        order_by="ViewPanel.position",
        lazy="selectin",
    )


class ViewPanel(Base):
    """One panel inside a view: either a form or a dashboard."""

    __tablename__ = "view_panels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    view_id: Mapped[int] = mapped_column(
        ForeignKey("views.id", ondelete="CASCADE"), nullable=False
    )

    # Matches the panel id inside the view's dockview layout JSON.
    panel_key: Mapped[str] = mapped_column(String(64), nullable=False)

    # 'form' | 'dashboard'. Exactly one of the two ids below is set; enforced
    # by a check constraint in the migration.
    kind: Mapped[str] = mapped_column(String(16), nullable=False)

    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    form_definition_id: Mapped[int | None] = mapped_column(
        ForeignKey("form_definitions.id", ondelete="CASCADE"), nullable=True
    )
    dashboard_binding_id: Mapped[int | None] = mapped_column(
        ForeignKey("dashboard_bindings.id", ondelete="CASCADE"), nullable=True
    )

    view: Mapped[View] = relationship(back_populates="panels")
    form: Mapped[FormDefinition | None] = relationship(lazy="selectin")
    dashboard: Mapped[DashboardBinding | None] = relationship(lazy="selectin")


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Which form produced this row. Nullable so rows submitted before forms
    # were first-class are not orphaned, and SET NULL so deleting a form does
    # not delete its history.
    form_definition_id: Mapped[int | None] = mapped_column(
        ForeignKey("form_definitions.id", ondelete="SET NULL"), nullable=True
    )

    region: Mapped[str] = mapped_column(String(64), nullable=False)
    product: Mapped[str] = mapped_column(String(64), nullable=False)
    units: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    sale_date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Fields a form defines that have no dedicated column land here, so a new
    # form does not require a migration.
    payload: Mapped[dict] = mapped_column(JSONColumn, nullable=False, default=dict)

    # Indexed: every chart filters and groups on this, and the in-place refresh
    # drives a time-range filter over it.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
