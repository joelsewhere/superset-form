"""Database access for views, forms, and dashboard bindings.

Kept separate from the routers so the same operations can be reused by
provisioning (which creates resources as a side effect of a form arriving from
an external builder) without going through HTTP.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.form_schema import DEFAULT_FIELDS, FormField
from app.models import DashboardBinding, FormDefinition, View, ViewPanel

DEFAULT_VIEW_NAME = "Default"
SEED_FORM_NAME = "default"


# --- forms -----------------------------------------------------------------


async def list_forms(session: AsyncSession) -> list[FormDefinition]:
    result = await session.execute(select(FormDefinition).order_by(FormDefinition.name))
    return list(result.scalars().all())


async def get_form(session: AsyncSession, form_id: int) -> FormDefinition | None:
    return await session.get(FormDefinition, form_id)


async def get_form_by_name(session: AsyncSession, name: str) -> FormDefinition | None:
    result = await session.execute(
        select(FormDefinition).where(FormDefinition.name == name)
    )
    return result.scalar_one_or_none()


async def upsert_form(
    session: AsyncSession, *, name: str, fields: list[FormField]
) -> tuple[FormDefinition, bool]:
    """Create or replace a form by name. Returns (form, created)."""
    serialised = [f.model_dump(mode="json") for f in fields]
    existing = await get_form_by_name(session, name)

    if existing is not None:
        existing.fields = serialised
        await session.commit()
        await session.refresh(existing)
        return existing, False

    form = FormDefinition(name=name, fields=serialised)
    session.add(form)
    await session.commit()
    await session.refresh(form)
    return form, True


def form_fields(form: FormDefinition) -> list[FormField]:
    return [FormField.model_validate(f) for f in form.fields]


# --- dashboards ------------------------------------------------------------


async def list_dashboards(session: AsyncSession) -> list[DashboardBinding]:
    result = await session.execute(
        select(DashboardBinding).order_by(DashboardBinding.name)
    )
    return list(result.scalars().all())


async def get_dashboard(
    session: AsyncSession, dashboard_id: int
) -> DashboardBinding | None:
    return await session.get(DashboardBinding, dashboard_id)


async def create_dashboard_binding(
    session: AsyncSession,
    *,
    name: str,
    superset_dashboard_id: str | None = None,
    embed_uuid: str | None = None,
    filter_id: str | None = None,
    auto_created: bool = False,
) -> DashboardBinding:
    binding = DashboardBinding(
        name=name,
        superset_dashboard_id=superset_dashboard_id,
        embed_uuid=embed_uuid,
        filter_id=filter_id,
        auto_created=auto_created,
    )
    session.add(binding)
    await session.commit()
    await session.refresh(binding)
    return binding


async def link_form_dashboard(
    session: AsyncSession, form: FormDefinition, binding: DashboardBinding
) -> None:
    if binding not in form.dashboards:
        form.dashboards.append(binding)
        await session.commit()


async def unlink_form_dashboard(
    session: AsyncSession, form: FormDefinition, binding: DashboardBinding
) -> None:
    if binding in form.dashboards:
        form.dashboards.remove(binding)
        await session.commit()


# --- views -----------------------------------------------------------------


async def list_views(session: AsyncSession) -> list[View]:
    result = await session.execute(select(View).order_by(View.name))
    return list(result.scalars().all())


async def get_view(session: AsyncSession, view_id: int) -> View | None:
    return await session.get(View, view_id)


async def get_default_view(session: AsyncSession) -> View | None:
    result = await session.execute(select(View).where(View.is_default.is_(True)))
    return result.scalar_one_or_none()


async def create_view(
    session: AsyncSession, *, name: str, is_default: bool = False
) -> View:
    if is_default:
        # Only one default; the partial unique index would reject a second.
        current = await get_default_view(session)
        if current is not None:
            current.is_default = False
            await session.flush()

    view = View(name=name, is_default=is_default)
    session.add(view)
    await session.commit()
    await session.refresh(view)
    return view


async def add_panel(
    session: AsyncSession,
    view: View,
    *,
    kind: str,
    form_definition_id: int | None = None,
    dashboard_binding_id: int | None = None,
    title: str | None = None,
    panel_key: str | None = None,
) -> ViewPanel:
    if kind == "form":
        key = panel_key or f"form-{form_definition_id}"
    else:
        key = panel_key or f"dashboard-{dashboard_binding_id}"

    panel = ViewPanel(
        view_id=view.id,
        panel_key=key,
        kind=kind,
        title=title,
        position=len(view.panels),
        form_definition_id=form_definition_id,
        dashboard_binding_id=dashboard_binding_id,
    )
    session.add(panel)
    await session.commit()
    await session.refresh(view)
    return panel


async def ensure_default_view(session: AsyncSession) -> View:
    """The view the app opens with, created on first access."""
    view = await get_default_view(session)
    if view is not None:
        return view

    result = await session.execute(select(View).order_by(View.id).limit(1))
    view = result.scalar_one_or_none()
    if view is not None:
        view.is_default = True
        await session.commit()
        await session.refresh(view)
        return view

    return await create_view(session, name=DEFAULT_VIEW_NAME, is_default=True)


async def ensure_seed_form(session: AsyncSession) -> FormDefinition:
    """Seed a starter form so a cold stack has something to render."""
    existing = await get_form_by_name(session, SEED_FORM_NAME)
    if existing is not None:
        return existing
    form, _ = await upsert_form(session, name=SEED_FORM_NAME, fields=DEFAULT_FIELDS)
    return form
