"""Form definitions: the integration seam for an external form builder.

`PUT /api/forms/{name}` creates or replaces a form by name. A form arriving
with no dashboard gets a blank one provisioned and linked, which is the
"every form points at a dashboard" default.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import provisioning, store
from app.db import get_session
from app.form_schema import FormField
from app.models import FormDefinition, Submission
from app.schemas import FormRead, FormSummary, FormWrite

router = APIRouter(prefix="/api/forms", tags=["forms"])


def column_names() -> set[str]:
    """Columns a submission field can be stored in directly."""
    reserved = {"id", "created_at", "payload", "form_definition_id"}
    return {c.name for c in Submission.__table__.columns} - reserved


def to_read(form: FormDefinition) -> FormRead:
    fields = store.form_fields(form)
    columns = column_names()
    return FormRead(
        id=form.id,
        name=form.name,
        fields=fields,
        dashboard_ids=[d.id for d in form.dashboards],
        updated_at=form.updated_at,
        mapped_columns=sorted(f.name for f in fields if f.name in columns),
        payload_fields=sorted(f.name for f in fields if f.name not in columns),
    )


@router.get("", response_model=list[FormSummary])
async def list_forms(session: AsyncSession = Depends(get_session)) -> list[FormSummary]:
    forms = await store.list_forms(session)
    return [
        FormSummary(
            id=f.id,
            name=f.name,
            field_count=len(f.fields),
            dashboard_ids=[d.id for d in f.dashboards],
        )
        for f in forms
    ]


@router.get("/{form_id}", response_model=FormRead)
async def get_form(
    form_id: int, session: AsyncSession = Depends(get_session)
) -> FormRead:
    form = await store.get_form(session, form_id)
    if form is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such form.")
    return to_read(form)


@router.get("/{form_id}/schema", response_model=list[FormField])
async def get_form_schema(
    form_id: int, session: AsyncSession = Depends(get_session)
) -> list[FormField]:
    """Just the field list, for rendering."""
    form = await store.get_form(session, form_id)
    if form is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such form.")
    return store.form_fields(form)


@router.put("/{name}", response_model=FormRead)
async def put_form(
    name: str,
    payload: FormWrite,
    session: AsyncSession = Depends(get_session),
) -> FormRead:
    """Create or replace a form. This is the form-builder seam.

    Fields whose names match a `submissions` column are stored in that column;
    everything else goes to the JSONB `payload`. The response reports which is
    which, so a builder can see the consequences of its definition.
    """
    if payload.name != name:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Body name {payload.name!r} does not match path name {name!r}.",
        )

    form, _created = await store.upsert_form(
        session, name=name, fields=payload.fields
    )

    if payload.provision_dashboard:
        await provisioning.ensure_form_has_dashboard(session, form)
        await session.refresh(form)

    return to_read(form)


@router.post("/{form_id}/dashboards/{dashboard_id}", response_model=FormRead)
async def link_dashboard(
    form_id: int,
    dashboard_id: int,
    session: AsyncSession = Depends(get_session),
) -> FormRead:
    form = await store.get_form(session, form_id)
    binding = await store.get_dashboard(session, dashboard_id)
    if form is None or binding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such form or dashboard.")

    await store.link_form_dashboard(session, form, binding)
    await session.refresh(form)
    return to_read(form)


@router.delete("/{form_id}/dashboards/{dashboard_id}", response_model=FormRead)
async def unlink_dashboard(
    form_id: int,
    dashboard_id: int,
    session: AsyncSession = Depends(get_session),
) -> FormRead:
    form = await store.get_form(session, form_id)
    binding = await store.get_dashboard(session, dashboard_id)
    if form is None or binding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such form or dashboard.")

    await store.unlink_form_dashboard(session, form, binding)
    await session.refresh(form)
    return to_read(form)
